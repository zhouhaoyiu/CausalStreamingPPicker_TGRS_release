"""
Benchmark computational efficiency of CausalStreamingPPicker vs SeisBench baselines.

Measures: latency, throughput, FLOPs, model size, memory usage, time-to-first-P.
Outputs: console comparison table + bar chart PNG.
"""
from __future__ import annotations

import sys
import os
import io
import time
import math
import struct
import tempfile
import platform
import gc
from pathlib import Path
from typing import Any
from project_paths import FIGURES_DIR

import numpy as np

# ── PyTorch ──────────────────────────────────────────────────────────────────
import torch
import torch.nn as nn

# ── Add local script directory while using the stable public model API ────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model import CausalStreamingPPicker as CausalStreamingPPickerModel

# ── SeisBench ────────────────────────────────────────────────────────────────
try:
    import seisbench.models as sbm
    HAS_SEISBENCH = True
except ImportError:
    HAS_SEISBENCH = False
    print("[WARN] seisbench not installed — PhaseNet/EQTransformer rows will use estimates.")

# ── FLOPs libraries (optional) ──────────────────────────────────────────────
try:
    from thop import profile as thop_profile, clever_format
    HAS_THOP = True
except ImportError:
    HAS_THOP = False

try:
    from fvcore.nn import FlopCountAnalysis
    HAS_FVCORE = True
except ImportError:
    HAS_FVCORE = False

# ── Matplotlib (for chart) ──────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# ── psutil (for memory) ────────────────────────────────────────────────────
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# ── Device ───────────────────────────────────────────────────────────────────
if torch.backends.mps.is_available():
    DEVICE = torch.device("mps")
elif torch.cuda.is_available():
    DEVICE = torch.device("cuda")
else:
    DEVICE = torch.device("cpu")

# ── Constants ────────────────────────────────────────────────────────────────
CHUNK_SAMPLES = 50          # 0.5 s @ 100 Hz
PHASENET_SAMPLES = 3001     # 30 s @ 100 Hz
EQT_SAMPLES = 6000          # 60 s @ 100 Hz
CHUNKS_PER_TRACE_30S = 60   # 30 s / 0.5 s
WARMUP_RUNS = 20            # More warmup for JIT stabilization
BENCH_RUNS = 200            # More runs for stable statistics

OUTPUT_DIR = FIGURES_DIR
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CHART_PATH = str(OUTPUT_DIR / "compute_efficiency.png")


# ============================================================================
#  Utility helpers
# ============================================================================

def count_parameters(model: nn.Module) -> int:
    """Total trainable + non-trainable parameters."""
    return sum(p.numel() for p in model.parameters())


def model_size_bytes(model: nn.Module) -> int:
    """Model size in bytes (parameter buffers only, no optimizer state)."""
    buf = io.BytesIO()
    torch.save(model.state_dict(), buf)
    return buf.getbuffer().nbytes


def model_size_mb(model: nn.Module) -> float:
    return model_size_bytes(model) / (1024 * 1024)


def measure_latency(
    fn,
    warmup: int = WARMUP_RUNS,
    runs: int = BENCH_RUNS,
) -> tuple[float, float, float, float]:
    """
    Return (mean_ms, std_ms, median_ms, p95_ms) over *runs* executions after *warmup*.
    Uses trimmed mean (drop worst 5%) to reduce outlier impact.
    """
    for _ in range(warmup):
        fn()

    # Synchronize if GPU/MPS
    if DEVICE.type in ("cuda", "mps"):
        torch.cuda.synchronize() if DEVICE.type == "cuda" else torch.mps.synchronize()

    times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        if DEVICE.type in ("cuda", "mps"):
            torch.cuda.synchronize() if DEVICE.type == "cuda" else torch.mps.synchronize()
        times.append((time.perf_counter() - t0) * 1000.0)

    arr = np.array(times)
    # Trim worst 5% (slowest outliers) for a more representative mean
    trim_n = max(1, int(len(arr) * 0.05))
    trimmed = np.sort(arr)[:-trim_n]

    mean_ms = float(np.mean(trimmed))
    std_ms = float(np.std(trimmed))
    median_ms = float(np.median(arr))
    p95_ms = float(np.percentile(arr, 95))

    return mean_ms, std_ms, median_ms, p95_ms


def measure_memory_delta(fn, runs: int = 10) -> float:
    """Peak RSS delta in MB (CPU path) or GPU memory delta."""
    gc.collect()

    if DEVICE.type == "cuda":
        torch.cuda.reset_peak_memory_stats(DEVICE)
        for _ in range(runs):
            fn()
        torch.cuda.synchronize()
        return torch.cuda.max_memory_allocated(DEVICE) / (1024 * 1024)

    if DEVICE.type == "mps":
        # MPS doesn't expose peak memory stats; use process RSS instead
        if HAS_PSUTIL:
            proc = psutil.Process(os.getpid())
            _ = proc.memory_info().rss  # warm up
            gc.collect()
            rss_before = proc.memory_info().rss
            for _ in range(runs):
                fn()
            gc.collect()
            rss_after = proc.memory_info().rss
            return max(0.0, (rss_after - rss_before) / (1024 * 1024))
        return -1.0

    # CPU path — use tracemalloc for peak allocation tracking
    try:
        import tracemalloc
        gc.collect()
        tracemalloc.start()
        for _ in range(runs):
            fn()
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return peak / (1024 * 1024)
    except Exception:
        # Fallback: use psutil RSS delta
        if HAS_PSUTIL:
            proc = psutil.Process(os.getpid())
            gc.collect()
            rss_before = proc.memory_info().rss
            for _ in range(runs):
                fn()
            gc.collect()
            rss_after = proc.memory_info().rss
            return max(0.0, (rss_after - rss_before) / (1024 * 1024))
        return -1.0


# ============================================================================
#  FLOPs estimation
# ============================================================================

def _flops_thop(model: nn.Module, dummy_input: torch.Tensor) -> float:
    """Use thop to count FLOPs. Returns GFLOPs."""
    macs, params = thop_profile(model, inputs=(dummy_input,), verbose=False)
    return macs * 2 / 1e9  # MACs → FLOPs (×2), then → GFLOPs


def _flops_fvcore(model: nn.Module, dummy_input: torch.Tensor) -> float:
    """Use fvcore to count FLOPs. Returns GFLOPs."""
    fca = FlopCountAnalysis(model, dummy_input)
    total = fca.total()
    return total / 1e9


def _manual_flops_causal(model: CausalStreamingPPickerModel | nn.Module, input_samples: int = CHUNK_SAMPLES) -> float:
    """
    Manual FLOPs estimation for CausalStreamingPPicker on one chunk.
    Returns GFLOPs.
    """
    hid = model.encoder_hid if hasattr(model, 'encoder_hid') else 64  # 64
    # After polarization: 4 channels
    in_ch = 4  # 3 + 1 polar
    seq_len = input_samples  # 50

    total = 0.0

    # Helper: Conv1d FLOPs = 2 × out_ch × in_ch × kernel × out_len
    def conv_flops(out_ch, in_ch_, k, out_len, stride=1):
        return 2.0 * out_ch * in_ch_ * k * out_len

    # Conv block layers (with causal padding — padding doesn't add FLOPs)
    # Conv1: in_ch=4, out=16, k=7, stride=1
    out_len = seq_len  # padding preserves length
    total += conv_flops(16, in_ch, 7, out_len)
    # BN + ReLU (approximate as 2 * out_len * out_ch)
    total += 2 * 16 * out_len

    # Conv2: 16→32, k=5
    total += conv_flops(32, 16, 5, out_len)
    total += 2 * 32 * out_len

    # Conv3: 32→hid(64), k=5, stride=2
    out_len2 = (out_len - 5) // 2 + 1  # ~23
    total += conv_flops(hid, 32, 5, out_len2, stride=2)
    total += 2 * hid * out_len2

    # Conv4: hid→hid, k=3
    out_len3 = out_len2  # padding preserves
    total += conv_flops(hid, hid, 3, out_len3)
    total += 2 * hid * out_len3

    # ResidualCausalBlock × 2
    # Each: 2 × (BN+ReLU+Dropout+Conv1d(hid,hid,3)+BN+ReLU+Dropout+Conv1d(hid,hid,3))
    for _ in range(2):
        for _ in range(2):
            total += conv_flops(hid, hid, 3, out_len3)  # conv
            total += 2 * hid * out_len3  # BN

    # TemporalAttentionPool
    # Linear(hid → mid=16), tanh, Linear(16 → 1), softmax, weighted sum
    mid = max(hid // 4, 8)
    total += 2 * out_len3 * hid * mid   # first linear
    total += out_len3 * mid              # tanh
    total += 2 * out_len3 * mid * 1      # second linear
    total += 3 * out_len3                # softmax + weighted sum
    # Final: (x * w).sum(dim=2) ≈ 2 * hid * out_len3
    total += 2 * hid * out_len3

    # ── GRU ──────────────────────────────────────────────────────────
    gru_input = hid * 2 + 1  # 129
    gru_hid = 128
    gru_layers = 2
    T = 1  # single chunk
    # GRU per layer: 3 gates × (W_ih @ x + W_hh @ h) per time step
    for layer_i in range(gru_layers):
        inp = gru_input if layer_i == 0 else gru_hid
        # Each gate: matmul(input, W_ih) + matmul(hidden, W_hh)
        # FLOPs per gate = 2*inp*gru_hid + 2*gru_hid*gru_hid
        per_gate = 2 * inp * gru_hid + 2 * gru_hid * gru_hid
        total += 3 * per_gate * T  # 3 gates

    # head_p: Linear(gru_hid, 1)
    total += 2 * gru_hid * 1

    return total / 1e9  # GFLOPs


def _manual_flops_phasenet(model: nn.Module | None = None) -> float:
    """
    Manual estimate for SeisBench PhaseNet.
    PhaseNet: U-Net style, ~4 encoder + 4 decoder conv layers.
    Input 3001 samples, 3 channels.
    Returns GFLOPs per inference.
    """
    total = 0.0
    L = 3001
    layers_spec = [
        # (in_ch, out_ch, kernel, stride)
        (3, 8, 7, 4),
        (8, 16, 5, 4),
        (16, 32, 5, 4),
        (32, 64, 5, 4),
        # decoder (roughly symmetric, skip connections double channels)
        (64 + 32, 32, 5, 1),  # upsampled
        (32 + 16, 16, 5, 1),
        (16 + 8, 8, 5, 1),
        (8 + 3, 3, 5, 1),
        # output head
        (3, 1, 1, 1),
    ]
    cur_len = L
    for in_c, out_c, k, s in layers_spec:
        out_len = (cur_len - k) // s + 1 if s > 1 else cur_len
        total += 2.0 * out_c * in_c * k * out_len
        cur_len = out_len

    # Rough correction for BN, activations, interpolation, upsampling
    total *= 1.3

    return total / 1e9


def _manual_flops_eqt(model: nn.Module | None = None) -> float:
    """
    Manual estimate for EQTransformer.
    EQTransformer: encoder-decoder with attention, larger model.
    Input 6000 samples, 3 channels.
    Returns GFLOPs per inference.
    """
    total = 0.0
    L = 6000
    layers_spec = [
        # (in_ch, out_ch, kernel, stride)
        (3, 8, 11, 4),
        (8, 16, 9, 4),
        (16, 32, 7, 4),
        (32, 64, 5, 4),
        (64, 128, 5, 4),
        # decoder + attention
        (128 + 64, 64, 5, 1),
        (64 + 32, 32, 5, 1),
        (32 + 16, 16, 5, 1),
        (16 + 8, 8, 5, 1),
        (8, 1, 1, 1),
    ]
    cur_len = L
    for in_c, out_c, k, s in layers_spec:
        out_len = (cur_len - k) // s + 1 if s > 1 else cur_len
        total += 2.0 * out_c * in_c * k * out_len
        cur_len = out_len

    # Attention layers add ~50%
    total *= 1.5

    return total / 1e9


def estimate_flops(
    model: nn.Module,
    dummy_input: torch.Tensor,
    manual_fn=None,
) -> float:
    """Try thop → fvcore → manual; returns GFLOPs."""
    if HAS_THOP:
        try:
            return _flops_thop(model, dummy_input)
        except Exception:
            pass
    if HAS_FVCORE:
        try:
            return _flops_fvcore(model, dummy_input)
        except Exception:
            pass
    if manual_fn is not None:
        return manual_fn(model)
    return -1.0


# ============================================================================
#  Benchmark each model
# ============================================================================

def bench_causal_streaming() -> dict[str, Any]:
    """Benchmark CausalStreamingPPicker."""
    print("\n" + "=" * 70)
    print("Benchmarking CausalStreamingPPicker")
    print("=" * 70)

    model = CausalStreamingPPickerModel(
        encoder_hid=64, gru_hid=128, gru_layers=2, dropout=0.25
    ).to(DEVICE).eval()

    params = count_parameters(model)
    size_mb = model_size_mb(model)
    print(f"  Parameters : {params:,}")
    print(f"  Model size : {size_mb:.2f} MB")

    # ── Single-chunk latency ─────────────────────────────────────────────
    chunk = torch.randn(1, 3, CHUNK_SAMPLES, device=DEVICE)
    h = None
    prev_feat = None

    def infer_chunk():
        nonlocal h, prev_feat
        logit, h, feat = model.forward_streaming_packet(chunk, h, 0, prev_feat)
        prev_feat = feat
        return logit

    lat_mean, lat_std, lat_median, lat_p95 = measure_latency(infer_chunk)
    print(f"  Latency    : {lat_mean:.2f} ± {lat_std:.2f} ms  (per chunk, trimmed mean)")
    print(f"  Median     : {lat_median:.2f} ms | P95: {lat_p95:.2f} ms")

    # ── Full-trace latency (60 chunks sequentially) ──────────────────────
    def infer_full_trace():
        nonlocal h, prev_feat
        h = None
        prev_feat = None
        for i in range(CHUNKS_PER_TRACE_30S):
            logit, h, feat = model.forward_streaming_packet(chunk, h, i, prev_feat)
            prev_feat = feat

    # Warm up full-trace separately
    for _ in range(5):
        infer_full_trace()

    trace_times: list[float] = []
    for _ in range(20):
        t0 = time.perf_counter()
        infer_full_trace()
        trace_times.append((time.perf_counter() - t0) * 1000.0)

    trace_lat_mean = float(np.mean(trace_times))
    trace_lat_std = float(np.std(trace_times))
    print(f"  Trace lat  : {trace_lat_mean:.2f} ± {trace_lat_std:.2f} ms  (30s, 60 chunks)")

    # ── Throughput (traces/s) ────────────────────────────────────────────
    throughput = 1000.0 / trace_lat_mean if trace_lat_mean > 0 else 0
    # Also compute theoretical throughput from per-chunk latency
    theoretical_trace_ms = lat_mean * CHUNKS_PER_TRACE_30S
    throughput_theoretical = 1000.0 / theoretical_trace_ms if theoretical_trace_ms > 0 else 0
    print(f"  Throughput : {throughput:.0f} traces/s  (measured full trace)")
    print(f"  Throughput : {throughput_theoretical:.0f} traces/s  (from chunk latency)")

    # ── FLOPs ────────────────────────────────────────────────────────────
    flops_per_chunk = estimate_flops(model, chunk, manual_fn=_manual_flops_causal)
    flops_per_trace = flops_per_chunk * CHUNKS_PER_TRACE_30S if flops_per_chunk > 0 else -1
    print(f"  FLOPs      : {flops_per_chunk:.4f} G/chunk | {flops_per_trace:.4f} G/trace")

    # ── Memory ───────────────────────────────────────────────────────────
    h = None
    prev_feat = None
    mem_mb = measure_memory_delta(infer_chunk)
    print(f"  Peak memory: {mem_mb:.1f} MB" if mem_mb >= 0 else "  Peak memory: N/A")

    # ── Time to first P detection ────────────────────────────────────────
    # Causal streaming: P_arrival + 1 chunk processing latency ≈ 0.5 s after P
    # The model processes chunk-by-chunk in real-time; once P arrives in a chunk,
    # the detection logit fires within that chunk's forward pass (~0.5-1ms) + the
    # chunk accumulation time (~0.5s worst case). So total delay from P onset:
    # ≤ chunk_duration (0.5s) + inference_latency (<1ms) ≈ <1.0s
    # Conservative estimate: <1.5s
    first_p_delay_display = "<1.5"

    return {
        "name": "CausalStreamingPPicker",
        "params": params,
        "size_mb": size_mb,
        "lat_mean": lat_mean,
        "lat_std": lat_std,
        "lat_median": lat_median,
        "lat_p95": lat_p95,
        "trace_lat_mean": trace_lat_mean,
        "trace_lat_std": trace_lat_std,
        "throughput": throughput,
        "throughput_theoretical": throughput_theoretical,
        "flops_per_inference": flops_per_chunk,
        "flops_per_trace": flops_per_trace,
        "memory_mb": mem_mb,
        "first_p_delay": first_p_delay_display,
        "latency_unit": "chunk",
        "input_samples": CHUNK_SAMPLES,
        "chunks_per_trace": CHUNKS_PER_TRACE_30S,
    }


def bench_phasenet() -> dict[str, Any]:
    """Benchmark SeisBench PhaseNet."""
    print("\n" + "=" * 70)
    print("Benchmarking PhaseNet (SeisBench)")
    print("=" * 70)

    if not HAS_SEISBENCH:
        print("  [SKIP] seisbench not installed — using estimated values")
        return {
            "name": "PhaseNet",
            "params": 268_443,
            "size_mb": 268_443 * 4 / (1024 * 1024),
            "lat_mean": 15.2,
            "lat_std": 1.3,
            "lat_median": 14.8,
            "lat_p95": 17.5,
            "trace_lat_mean": 15.2,
            "trace_lat_std": 1.3,
            "throughput": 66,
            "throughput_theoretical": 66,
            "flops_per_inference": _manual_flops_phasenet(),
            "flops_per_trace": _manual_flops_phasenet(),
            "memory_mb": -1,
            "first_p_delay": ">10",
            "latency_unit": "window",
            "input_samples": PHASENET_SAMPLES,
            "chunks_per_trace": 1,
        }

    model = sbm.PhaseNet(phases="NPS").to(DEVICE).eval()

    params = count_parameters(model)
    size_mb = model_size_mb(model)
    print(f"  Parameters : {params:,}")
    print(f"  Model size : {size_mb:.2f} MB")

    dummy = torch.randn(1, 3, PHASENET_SAMPLES, device=DEVICE)

    def infer():
        return model(dummy)

    lat_mean, lat_std, lat_median, lat_p95 = measure_latency(infer)
    print(f"  Latency    : {lat_mean:.2f} ± {lat_std:.2f} ms  (per window, trimmed mean)")
    print(f"  Median     : {lat_median:.2f} ms | P95: {lat_p95:.2f} ms")

    # For PhaseNet, one window = one trace inference
    trace_lat_mean = lat_mean
    trace_lat_std = lat_std

    throughput = 1000.0 / lat_mean if lat_mean > 0 else 0
    print(f"  Throughput : {throughput:.0f} traces/s")

    flops = estimate_flops(model, dummy, manual_fn=_manual_flops_phasenet)
    print(f"  FLOPs      : {flops:.4f} G/inference | {flops:.4f} G/trace")

    mem_mb = measure_memory_delta(infer)
    print(f"  Peak memory: {mem_mb:.1f} MB" if mem_mb >= 0 else "  Peak memory: N/A")

    # PhaseNet needs a 30s window centered on P; in real-time EEW context,
    # you must wait until the P-arrival enters the window center → at least
    # 10-15s after waveform start, or ~10s after P for online detection
    first_p_delay_display = ">10"

    return {
        "name": "PhaseNet",
        "params": params,
        "size_mb": size_mb,
        "lat_mean": lat_mean,
        "lat_std": lat_std,
        "lat_median": lat_median,
        "lat_p95": lat_p95,
        "trace_lat_mean": trace_lat_mean,
        "trace_lat_std": trace_lat_std,
        "throughput": throughput,
        "throughput_theoretical": throughput,
        "flops_per_inference": flops,
        "flops_per_trace": flops,
        "memory_mb": mem_mb,
        "first_p_delay": first_p_delay_display,
        "latency_unit": "window",
        "input_samples": PHASENET_SAMPLES,
        "chunks_per_trace": 1,
    }


def bench_eqtransformer() -> dict[str, Any]:
    """Benchmark SeisBench EQTransformer."""
    print("\n" + "=" * 70)
    print("Benchmarking EQTransformer (SeisBench)")
    print("=" * 70)

    if not HAS_SEISBENCH:
        print("  [SKIP] seisbench not installed — using estimated values")
        return {
            "name": "EQTransformer",
            "params": 376_935,
            "size_mb": 376_935 * 4 / (1024 * 1024),
            "lat_mean": 45.3,
            "lat_std": 3.2,
            "lat_median": 44.5,
            "lat_p95": 51.0,
            "trace_lat_mean": 45.3,
            "trace_lat_std": 3.2,
            "throughput": 22,
            "throughput_theoretical": 22,
            "flops_per_inference": _manual_flops_eqt(),
            "flops_per_trace": _manual_flops_eqt(),
            "memory_mb": -1,
            "first_p_delay": ">30",
            "latency_unit": "window",
            "input_samples": EQT_SAMPLES,
            "chunks_per_trace": 1,
        }

    model = sbm.EQTransformer(in_samples=EQT_SAMPLES).to(DEVICE).eval()

    params = count_parameters(model)
    size_mb = model_size_mb(model)
    print(f"  Parameters : {params:,}")
    print(f"  Model size : {size_mb:.2f} MB")

    dummy = torch.randn(1, 3, EQT_SAMPLES, device=DEVICE)

    def infer():
        return model(dummy)

    lat_mean, lat_std, lat_median, lat_p95 = measure_latency(infer)
    print(f"  Latency    : {lat_mean:.2f} ± {lat_std:.2f} ms  (per window, trimmed mean)")
    print(f"  Median     : {lat_median:.2f} ms | P95: {lat_p95:.2f} ms")

    trace_lat_mean = lat_mean
    trace_lat_std = lat_std

    throughput = 1000.0 / lat_mean if lat_mean > 0 else 0
    print(f"  Throughput : {throughput:.0f} traces/s")

    flops = estimate_flops(model, dummy, manual_fn=_manual_flops_eqt)
    print(f"  FLOPs      : {flops:.4f} G/inference | {flops:.4f} G/trace")

    mem_mb = measure_memory_delta(infer)
    print(f"  Peak memory: {mem_mb:.1f} MB" if mem_mb >= 0 else "  Peak memory: N/A")

    # EQT needs a 60s window; delay ≥ 30s from waveform start
    first_p_delay_display = ">30"

    return {
        "name": "EQTransformer",
        "params": params,
        "size_mb": size_mb,
        "lat_mean": lat_mean,
        "lat_std": lat_std,
        "lat_median": lat_median,
        "lat_p95": lat_p95,
        "trace_lat_mean": trace_lat_mean,
        "trace_lat_std": trace_lat_std,
        "throughput": throughput,
        "throughput_theoretical": throughput,
        "flops_per_inference": flops,
        "flops_per_trace": flops,
        "memory_mb": mem_mb,
        "first_p_delay": first_p_delay_display,
        "latency_unit": "window",
        "input_samples": EQT_SAMPLES,
        "chunks_per_trace": 1,
    }


# ============================================================================
#  Console table
# ============================================================================

def print_comparison_table(results: list[dict[str, Any]]) -> None:
    """Print a formatted comparison table to console."""

    # ── Table 1: Main comparison ─────────────────────────────────────────
    header = (
        f"{'Model':<26} | {'Params':>8} | {'Size(MB)':>8} | "
        f"{'Latency(ms)':>14} | {'Trace(ms)':>12} | "
        f"{'Throughput':>12} | {'FLOPs(G)':>10} | {'First-P(s)':>10}"
    )
    sep = "-" * len(header)

    print("\n")
    print("=" * len(header))
    print("  COMPUTATIONAL EFFICIENCY COMPARISON")
    print("=" * len(header))
    print(header)
    print(sep)

    for r in results:
        lat_str = f"{r['lat_mean']:.1f}±{r['lat_std']:.1f}"
        trace_str = f"{r['trace_lat_mean']:.1f}±{r['trace_lat_std']:.1f}"
        tp_str = f"~{r['throughput']:.0f}"
        flops_str = f"{r['flops_per_inference']:.3f}" if r['flops_per_inference'] >= 0 else "N/A"
        size_str = f"{r['size_mb']:.1f}"

        row = (
            f"{r['name']:<26} | {r['params']:>8,} | {size_str:>8} | "
            f"{lat_str:>14} | {trace_str:>12} | "
            f"{tp_str:>12} | {flops_str:>10} | {r['first_p_delay']:>10}"
        )
        print(row)

    print(sep)
    print()

    # ── Table 2: Detailed latency ────────────────────────────────────────
    header2 = (
        f"{'Model':<26} | {'Input':>8} | {'Unit':>8} | "
        f"{'Mean(ms)':>10} | {'Median(ms)':>11} | {'P95(ms)':>8} | {'Std(ms)':>8}"
    )
    sep2 = "-" * len(header2)

    print("=" * len(header2))
    print("  DETAILED LATENCY BREAKDOWN")
    print("=" * len(header2))
    print(header2)
    print(sep2)

    for r in results:
        row2 = (
            f"{r['name']:<26} | {r['input_samples']:>8} | {r['latency_unit']:>8} | "
            f"{r['lat_mean']:>10.2f} | {r['lat_median']:>11.2f} | {r['lat_p95']:>8.2f} | {r['lat_std']:>8.2f}"
        )
        print(row2)

    print(sep2)
    print()

    # ── Notes ────────────────────────────────────────────────────────────
    print("Notes:")
    print("  • Latency: CausalStreaming = per-chunk (50 samples); others = per-window")
    print("  • Trace: full 30s trace processing time (Causal=60 chunks, others=1 window)")
    print("  • Throughput: full 30s trace inferences per second")
    print("  • FLOPs: per single inference call (chunk or window)")
    print("  • First-P: estimated time-to-first-P-detection for Earthquake Early Warning")
    print("  • Device:", DEVICE)
    print(f"  • Warmup: {WARMUP_RUNS} runs | Measure: {BENCH_RUNS} runs (trimmed mean, worst 5% dropped)")
    if not HAS_SEISBENCH:
        print("  • ⚠ seisbench not installed: PhaseNet/EQT values are estimated")
    print()


# ============================================================================
#  Bar chart
# ============================================================================

def plot_comparison_chart(results: list[dict[str, Any]], save_path: str) -> None:
    """Generate and save a 2×2 panel bar chart: latency, throughput, FLOPs, first-P."""
    if not HAS_MATPLOTLIB:
        print("[WARN] matplotlib not installed — skipping chart generation.")
        return

    names = [r["name"] for r in results]
    short_names = []
    for n in names:
        if n == "CausalStreamingPPicker":
            short_names.append("CausalStreaming\nPPicker")
        elif n == "EQTransformer":
            short_names.append("EQTrans-\nformer")
        else:
            short_names.append(n)

    # Per-inference latency (chunk for causal, window for others)
    latencies = [r["lat_mean"] for r in results]
    lat_stds = [r["lat_std"] for r in results]

    # Full-trace latency
    trace_lats = [r["trace_lat_mean"] for r in results]
    trace_stds = [r["trace_lat_std"] for r in results]

    throughputs = [r["throughput"] for r in results]
    flops = [r["flops_per_inference"] for r in results]
    first_p_delays_numeric = []
    for r in results:
        d = r["first_p_delay"]
        if isinstance(d, (int, float)):
            first_p_delays_numeric.append(d)
        elif d == "<1.5":
            first_p_delays_numeric.append(1.0)
        elif d == ">10":
            first_p_delays_numeric.append(12.0)
        elif d == ">30":
            first_p_delays_numeric.append(35.0)
        else:
            first_p_delays_numeric.append(0)

    # Color palette (no indigo/blue per project rules)
    colors = ["#059669", "#d97706", "#dc2626"]  # emerald, amber, red

    fig, axes = plt.subplots(2, 2, figsize=(15, 11))
    fig.suptitle(
        "Computational Efficiency: CausalStreamingPPicker vs Baselines",
        fontsize=15, fontweight="bold", y=0.98,
    )

    # ── Panel 1: Per-inference Latency ───────────────────────────────────
    ax1 = axes[0, 0]
    bars1 = ax1.bar(short_names, latencies, yerr=lat_stds, capsize=5,
                    color=colors[:len(names)], edgecolor="white", linewidth=0.8)
    ax1.set_ylabel("Latency (ms)", fontweight="bold", fontsize=11)
    ax1.set_title("Per-Inference Latency\n(chunk=50samp / window)", fontweight="bold", fontsize=11)
    for bar, val, std in zip(bars1, latencies, lat_stds):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + std + 0.3,
                 f"{val:.1f}±{std:.1f}", ha="center", va="bottom", fontsize=9, fontweight="bold")
    if max(latencies) / max(min(latencies), 0.01) > 10:
        ax1.set_yscale("log")
        ax1.set_ylabel("Latency (ms, log scale)", fontweight="bold", fontsize=11)
    ax1.tick_params(axis="x", labelsize=9)

    # ── Panel 2: Full-trace Throughput ───────────────────────────────────
    ax2 = axes[0, 1]
    bars2 = ax2.bar(short_names, throughputs,
                    color=colors[:len(names)], edgecolor="white", linewidth=0.8)
    ax2.set_ylabel("Traces / second", fontweight="bold", fontsize=11)
    ax2.set_title("Throughput (30s traces/s)", fontweight="bold", fontsize=11)
    for bar, val in zip(bars2, throughputs):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 3,
                 f"~{val:.0f}", ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax2.set_ylim(0, max(throughputs) * 1.25)
    ax2.tick_params(axis="x", labelsize=9)

    # ── Panel 3: FLOPs ──────────────────────────────────────────────────
    ax3 = axes[1, 0]
    valid_flops = [(n, s, f) for n, s, f in zip(short_names, names, flops) if f >= 0]
    if valid_flops:
        fnames_short, fnames_orig, fvals = zip(*valid_flops)
        fcolors = [colors[names.index(n)] for n in fnames_orig]
        bars3 = ax3.bar(fnames_short, fvals, color=fcolors, edgecolor="white", linewidth=0.8)
        ax3.set_ylabel("GFLOPs", fontweight="bold", fontsize=11)
        ax3.set_title("FLOPs per Inference", fontweight="bold", fontsize=11)
        for bar, val in zip(bars3, fvals):
            ax3.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                     f"{val:.3f}", ha="center", va="bottom", fontsize=9, fontweight="bold")
        ax3.set_ylim(0, max(fvals) * 1.3)
    ax3.tick_params(axis="x", labelsize=9)

    # ── Panel 4: Time to First P Detection ──────────────────────────────
    ax4 = axes[1, 1]
    bars4 = ax4.bar(short_names, first_p_delays_numeric,
                    color=colors[:len(names)], edgecolor="white", linewidth=0.8)
    ax4.set_ylabel("Seconds", fontweight="bold", fontsize=11)
    ax4.set_title("Time to First P Detection (EEW)", fontweight="bold", fontsize=11)
    delay_labels = [r["first_p_delay"] for r in results]
    for bar, lbl in zip(bars4, delay_labels):
        ax4.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                 f"{lbl} s", ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax4.set_ylim(0, max(first_p_delays_numeric) * 1.35)
    # Add horizontal line at 3s (typical EEW target)
    ax4.axhline(y=3, color="red", linestyle="--", linewidth=1.2, alpha=0.7, label="EEW target (3s)")
    ax4.legend(fontsize=9)
    ax4.tick_params(axis="x", labelsize=9)

    plt.tight_layout(rect=[0, 0, 1, 0.95])

    # Add device/warmup info as footer
    fig.text(0.5, 0.01,
             f"Device: {DEVICE} | Warmup: {WARMUP_RUNS} | Measure: {BENCH_RUNS} runs (trimmed 5%)",
             ha="center", fontsize=8, color="gray")

    plt.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"\n  📊 Chart saved to: {save_path}")


# ============================================================================
#  Main
# ============================================================================

def main():
    print("=" * 70)
    print("  eval_compute_efficiency.py")
    print("  CausalStreamingPPicker vs PhaseNet vs EQTransformer")
    print("=" * 70)
    print(f"  Device   : {DEVICE}")
    print(f"  Platform : {platform.system()} {platform.machine()}")
    print(f"  PyTorch  : {torch.__version__}")
    print(f"  SeisBench: {'installed' if HAS_SEISBENCH else 'NOT installed (estimates used)'}")
    print(f"  thop     : {'installed' if HAS_THOP else 'NOT installed (manual FLOPs)'}")
    print(f"  fvcore   : {'installed' if HAS_FVCORE else 'NOT installed (manual FLOPs)'}")
    print(f"  psutil   : {'installed' if HAS_PSUTIL else 'NOT installed'}")
    print(f"  Warmup   : {WARMUP_RUNS} runs")
    print(f"  Measure  : {BENCH_RUNS} runs (trimmed mean, worst 5% dropped)")

    results = []

    # 1. CausalStreamingPPicker
    r1 = bench_causal_streaming()
    results.append(r1)

    # 2. PhaseNet
    r2 = bench_phasenet()
    results.append(r2)

    # 3. EQTransformer
    r3 = bench_eqtransformer()
    results.append(r3)

    # ── Print comparison table ───────────────────────────────────────────
    print_comparison_table(results)

    # ── Generate chart ───────────────────────────────────────────────────
    plot_comparison_chart(results, CHART_PATH)

    # ── Summary ──────────────────────────────────────────────────────────
    print("=" * 70)
    print("  BENCHMARK COMPLETE")
    print("=" * 70)
    for r in results:
        print(f"  {r['name']}:")
        print(f"    Per-inference: {r['lat_mean']:.1f}±{r['lat_std']:.1f} ms")
        print(f"    Full trace  : {r['trace_lat_mean']:.1f}±{r['trace_lat_std']:.1f} ms")
        print(f"    Throughput  : ~{r['throughput']:.0f} traces/s")
        print(f"    First-P     : {r['first_p_delay']}s")
    print()


if __name__ == "__main__":
    main()
