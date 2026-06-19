from __future__ import annotations
"""
First-P Detection Delay CDF Evaluation
=======================================

Analyzes the first-P detection delay for CausalStreamingPPicker,
SeisBench PhaseNet (streaming sim), and recursive STA/LTA baseline.

Outputs:
  1. CDF plot (PNG) of detection delay for all three models
  2. Summary statistics table printed to console
  3. Optional per-chunk probability curves (--debug flag)

Usage:
    python eval_first_p_delay_cdf.py \
        --checkpoint models/checkpoints/multidomain_best.pt \
        --phasenet-weights instance \
        --n-traces 1000 \
        --device cpu

    # With K-NET data
    python eval_first_p_delay_cdf.py \
        --checkpoint models/checkpoints/multidomain_best.pt \
        --phasenet-weights instance \
        --n-traces 1000 \
        --knet-dir data/knet_accel

    # Debug mode (per-chunk probability curves)
    python eval_first_p_delay_cdf.py \
        --checkpoint models/checkpoints/multidomain_best.pt \
        --debug
"""
import argparse
import gc
import math
import os
import sys
import time
from pathlib import Path
from typing import Optional
from project_paths import DATA_DIR, FIGURES_DIR

import numpy as np
import torch
import torch.nn as nn

# ── Ensure local imports work ──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import CHUNK_SEC, TARGET_SR, SAMPLES_PER_CHUNK, P_ARRIVAL_COL_CANDIDATES
from data_streaming import normalize_packet_causal
from model import CausalStreamingPPicker as CausalStreamingPPickerModel

# ── SeisBench imports ──
try:
    import seisbench.models as sbm
    from seisbench.data import InstanceGM
    HAS_SEISBENCH = True
except ImportError:
    HAS_SEISBENCH = False
    print("WARNING: seisbench not installed. PhaseNet comparison will be disabled.")

# ── matplotlib ──
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# ── Constants ──
SPC = SAMPLES_PER_CHUNK  # 50
CAUSAL_THRESHOLD = 0.30
SB_THRESHOLD = 0.50
STA_DURATION_SEC = 1.0
LTA_DURATION_SEC = 15.0
STA_LTA_THRESHOLD = 4.0


# ═══════════════════════════════════════════════════════════════
#  Font Setup (Noto Sans SC for Chinese labels)
# ═══════════════════════════════════════════════════════════════

def setup_matplotlib_fonts():
    """Configure matplotlib to use a proper CJK-capable font.

    Priority order:
      1. Known CJK fonts (Noto Sans SC, Noto Sans CJK SC, etc.)
      2. System CJK fonts (STHeiti, PingFang SC, etc.)
      3. Generic CJK search (must contain 'CJK' or 'SC' to avoid false matches
         like 'Noto Sans Inscriptional Parthian')
      4. Safe Latin fallback (Arial, Helvetica, DejaVu Sans)
    """
    preferred_fonts = [
        "Noto Sans SC",
        "Noto Sans CJK SC",
        "PingFang SC",
        "STHeiti",
        "WenQuanYi Micro Hei",
        "SimHei",
        "Microsoft YaHei",
    ]
    # Safe Latin fallbacks (always available on macOS / Linux)
    latin_fallbacks = ["Arial", "Helvetica", "DejaVu Sans"]

    available = {f.name for f in fm.fontManager.ttflist}
    chosen = None
    for name in preferred_fonts:
        if name in available:
            chosen = name
            break
    if chosen:
        plt.rcParams["font.sans-serif"] = [chosen] + latin_fallbacks + plt.rcParams.get("font.sans-serif", [])
        plt.rcParams["axes.unicode_minus"] = False
        print(f"  matplotlib font: {chosen}")
    else:
        # Fallback: find a REAL CJK font (must contain 'CJK' or 'SC' in name,
        # which excludes 'Noto Sans Inscriptional Parthian' etc.)
        cjk_fonts = [f.name for f in fm.fontManager.ttflist
                     if any(k in f.name for k in ["CJK", "SC", "Hei", "Song", "Ming", "Gothic"])
                     and "Inscriptional" not in f.name
                     and "Phags" not in f.name
                     and "Yi" not in f.name
                     and "Lisu" not in f.name
                     and "Miao" not in f.name]
        if cjk_fonts:
            chosen = cjk_fonts[0]
            plt.rcParams["font.sans-serif"] = [chosen] + latin_fallbacks + plt.rcParams.get("font.sans-serif", [])
            plt.rcParams["axes.unicode_minus"] = False
            print(f"  matplotlib font (fallback): {chosen}")
        else:
            # No CJK font at all — use safe Latin fallbacks
            plt.rcParams["font.sans-serif"] = latin_fallbacks + plt.rcParams.get("font.sans-serif", [])
            plt.rcParams["axes.unicode_minus"] = False
            print("  WARNING: No CJK font found. Using Latin fallbacks. Chinese labels may not render.")


# ═══════════════════════════════════════════════════════════════
#  Data Loading
# ═══════════════════════════════════════════════════════════════

def load_ig_test(min_mag: float = 4.0, n_traces: int = 1000, seed: int = 42):
    """Load InstanceGM test traces filtered by magnitude."""
    import pandas as pd

    print("Loading InstanceGM...")
    ds = InstanceGM(cache="trace", metadata_cache=True, component_order="ZNE")

    p_col = None
    for col in P_ARRIVAL_COL_CANDIDATES:
        if col in ds.metadata.columns:
            p_col = col
            break
    if p_col is None:
        print("  ERROR: No P-arrival column found in InstanceGM metadata")
        return []

    # If P arrival is in seconds, convert to sample index
    if p_col == "trace_P_arrival":
        ds.metadata["trace_P_arrival_sample"] = (
            ds.metadata[p_col] * ds.metadata["trace_sampling_rate_hz"]
        ).round().astype("Int64")
        p_col = "trace_P_arrival_sample"

    print(f"  P column: {p_col}")

    # Filter by test subset, valid P arrival, and magnitude.
    te = ds.metadata["split"] == "test"
    te &= ds.metadata[p_col].notna()
    if min_mag > 0 and "source_magnitude" in ds.metadata.columns:
        te &= ds.metadata["source_magnitude"].notna()
        te &= ds.metadata["source_magnitude"] >= min_mag
    all_te = np.where(te)[0]
    print(f"  Test candidates after filter: {len(all_te)}")

    # Sample
    if n_traces and len(all_te) > n_traces:
        rng = np.random.RandomState(seed)
        all_te = all_te[rng.choice(len(all_te), size=n_traces, replace=False)]

    # Load traces
    traces = []
    for i in all_te:
        row = ds.metadata.iloc[i]
        try:
            wave = ds.get_waveforms(int(i)).astype(np.float32)
        except Exception:
            continue
        if wave.shape[0] < 3:
            continue
        wave = wave[:3]
        p_s = float(row[p_col])
        if p_s < 0 or p_s >= wave.shape[1]:
            continue
        # Filter: P arrival not at very start or very end (at least 2s margin)
        if p_s < 2 * TARGET_SR or p_s > wave.shape[1] - 2 * TARGET_SR:
            continue
        traces.append({"wave": wave, "p_sample": p_s, "source": "InstanceGM", "idx": int(i)})

    print(f"  Loaded {len(traces)} valid InstanceGM test traces")
    return traces


def load_knet_test(knet_dir: str, min_mag: float = 4.0):
    """Load K-NET test traces from HDF5+CSV."""
    import pandas as pd
    import h5py

    knet_path = Path(knet_dir)
    csv_path = knet_path / "metadata.csv"
    hdf5_path = knet_path / "waveforms.hdf5"

    if not csv_path.exists() or not hdf5_path.exists():
        print(f"  K-NET data not found at {knet_dir}")
        return []

    print(f"Loading K-NET from {knet_dir}...")
    metadata = pd.read_csv(csv_path)

    p_col = None
    for col in P_ARRIVAL_COL_CANDIDATES:
        if col in metadata.columns:
            p_col = col
            break
    if p_col is None and "trace_p_arrival_sample" in metadata.columns:
        p_col = "trace_p_arrival_sample"
    if p_col is None:
        print("  ERROR: No P-arrival column in K-NET metadata")
        return []

    print(f"  P column: {p_col}")

    mask = metadata["split"] == "test"
    mask &= metadata[p_col].notna()
    if min_mag > 0 and "source_magnitude" in metadata.columns:
        mask &= metadata["source_magnitude"].notna()
        mask &= metadata["source_magnitude"] >= min_mag
    indices = np.where(mask)[0]
    print(f"  K-NET test candidates: {len(indices)}")

    hf = h5py.File(hdf5_path, "r")
    traces = []
    for idx in indices:
        row = metadata.iloc[idx]
        try:
            wave = hf["data"][row["trace_name"]][:].astype(np.float32)
        except Exception:
            continue
        if wave.shape[0] < 3:
            wave = wave[:3]
        native_sr = float(row.get("trace_sampling_rate_hz", 100.0))
        if native_sr != TARGET_SR and native_sr > 0:
            from scipy.signal import resample
            tn = int(wave.shape[1] * TARGET_SR / native_sr)
            if tn > 0:
                wave = resample(wave, tn, axis=1).astype(np.float32)
        p_s = float(row[p_col])
        if native_sr != TARGET_SR and native_sr > 0:
            p_s = p_s * TARGET_SR / native_sr
        if p_s < 0 or p_s >= wave.shape[1]:
            continue
        # Filter: P arrival not at very start or very end
        if p_s < 2 * TARGET_SR or p_s > wave.shape[1] - 2 * TARGET_SR:
            continue
        traces.append({"wave": wave, "p_sample": p_s, "source": "K-NET", "idx": int(idx)})

    hf.close()
    print(f"  Loaded {len(traces)} valid K-NET test traces")
    return traces


# ═══════════════════════════════════════════════════════════════
#  Model Evaluation: CausalStreamingPPicker
# ═══════════════════════════════════════════════════════════════

def eval_causal_streaming(
    model: CausalStreamingPPickerModel,
    wave: np.ndarray,
    p_arrival_sample: float,
    device: torch.device,
    threshold: float = CAUSAL_THRESHOLD,
    max_chunks: int = 320,
    return_all_probs: bool = False,
) -> dict:
    """
    Evaluate CausalStreamingPPicker in streaming mode.

    Feeds chunks one-by-one, records the chunk where prob first exceeds threshold.

    Returns dict with:
      - detected: bool
      - first_detect_chunk: int or None
      - delay_sec: float or None  (negative=early, positive=late)
      - p_chunk: int (true P chunk index)
      - all_probs: list[float] (only if return_all_probs=True)
    """
    model.eval()
    npts = wave.shape[1]
    p_chunk = int(p_arrival_sample / SPC)
    total_chunks = min((npts + SPC - 1) // SPC, max_chunks)

    h_prev = None
    prev_feat = None
    running_stats = None
    first_detect_chunk = None
    first_detect_prob = 0.0
    all_probs = [] if return_all_probs else None

    with torch.no_grad():
        for k in range(total_chunks):
            a, b = k * SPC, min((k + 1) * SPC, npts)
            seg = wave[:, a:b]
            is_padded = (b - a < SPC)
            valid_samples = (b - a) if is_padded else None
            if is_padded:
                pad = np.zeros((3, SPC - (b - a)), dtype=wave.dtype)
                seg = np.concatenate([seg, pad], axis=1)

            norm_chunk, running_stats = normalize_packet_causal(
                seg.astype(np.float64), running_stats, valid_samples=valid_samples
            )
            pkt = torch.from_numpy(norm_chunk).unsqueeze(0).to(device)  # (1, 3, 50)

            logit, h_prev, feat = model.forward_streaming_packet(
                pkt, h_prev, packet_idx=k, prev_feat=prev_feat
            )
            prob = torch.sigmoid(logit).item()

            if return_all_probs:
                all_probs.append(prob)

            prev_feat = feat

            if prob >= threshold and first_detect_chunk is None:
                first_detect_chunk = k
                first_detect_prob = prob

    detected = first_detect_chunk is not None
    if detected:
        delay = (first_detect_chunk - p_chunk) * CHUNK_SEC
    else:
        delay = None

    result = {
        "detected": detected,
        "first_detect_chunk": first_detect_chunk,
        "first_detect_prob": first_detect_prob,
        "delay_sec": delay,
        "p_chunk": p_chunk,
    }
    if return_all_probs:
        result["all_probs"] = all_probs
    return result


# ═══════════════════════════════════════════════════════════════
#  Model Evaluation: SeisBench PhaseNet (streaming sim)
# ═══════════════════════════════════════════════════════════════

def eval_phasenet_streaming(
    model,
    wave: np.ndarray,
    p_arrival_sample: float,
    device: torch.device,
    threshold: float = SB_THRESHOLD,
    max_chunks: int = 320,
    return_all_probs: bool = False,
) -> dict:
    """
    Simulate PhaseNet streaming inference.

    Starting from the minimum input length (3001 samples = 61 chunks),
    slide the window forward by 1 chunk each time and re-run full inference.
    Record the first chunk where P probability exceeds threshold.

    Returns dict with same fields as eval_causal_streaming.
    """
    model.eval()
    npts = wave.shape[1]
    p_chunk = int(p_arrival_sample / SPC)
    total_chunks = min((npts + SPC - 1) // SPC, max_chunks)

    in_samples = model.in_samples  # PhaseNet=3001
    sr = model.sampling_rate       # 100 Hz
    min_chunks_needed = int(math.ceil(in_samples / SPC))  # ~61 chunks for PhaseNet

    first_detect_chunk = None
    first_detect_prob = 0.0
    all_probs = [] if return_all_probs else None
    labels = getattr(model, "labels", None)
    if labels is None:
        labels = getattr(model, "_labels", None)
    if labels is None:
        labels = getattr(model, "phases", None)
    if labels is None:
        labels = "PSN"
    if not isinstance(labels, str):
        labels = "".join(labels)
    p_index = labels.index("P") if "P" in labels else 0

    with torch.no_grad():
        # Pad all_probs with None for chunks before min_chunks_needed
        if return_all_probs:
            all_probs = [0.0] * (min_chunks_needed - 1)

        for c in range(min_chunks_needed, total_chunks + 1):
            end_sample = min(c * SPC, npts)
            raw_window = wave[:, :end_sample]

            # PhaseNet needs fixed-length input
            if end_sample < in_samples:
                padded = np.zeros((3, in_samples), dtype=np.float32)
                padded[:, :end_sample] = raw_window
                input_data = padded
            else:
                input_data = raw_window[:, -in_samples:]

            # Per-channel normalization (SeisBench standard)
            norm_data = np.zeros_like(input_data, dtype=np.float32)
            for ch in range(3):
                d = input_data[ch]
                std = np.std(d)
                if std > 1e-8:
                    norm_data[ch] = (d - np.mean(d)) / std

            t_data = torch.from_numpy(norm_data).unsqueeze(0).to(device)

            try:
                output = model(t_data)
                if isinstance(output, dict):
                    probs = output.get("P", output.get("p", None))
                    if probs is None:
                        for k, v in output.items():
                            if isinstance(v, torch.Tensor):
                                probs = v
                                break
                else:
                    probs = output

                if probs.dim() == 3:
                    # SeisBench PhaseNet returns [batch, classes, samples].
                    # Keep a fallback for implementations that return [batch, samples, classes].
                    if probs.shape[1] <= 10 and probs.shape[2] > probs.shape[1]:
                        p_probs_tensor = probs[0, p_index, :]
                    else:
                        p_probs_tensor = probs[0, :, p_index]
                elif probs.dim() == 2:
                    p_probs_tensor = probs[0, :]
                else:
                    p_probs_tensor = probs.squeeze()

                max_prob = float(p_probs_tensor.max().item())
            except Exception:
                max_prob = 0.0

            if return_all_probs:
                all_probs.append(max_prob)

            if max_prob >= threshold and first_detect_chunk is None:
                first_detect_chunk = c
                first_detect_prob = max_prob

    detected = first_detect_chunk is not None
    if detected:
        delay = (first_detect_chunk - p_chunk) * CHUNK_SEC
    else:
        delay = None

    result = {
        "detected": detected,
        "first_detect_chunk": first_detect_chunk,
        "first_detect_prob": first_detect_prob,
        "delay_sec": delay,
        "p_chunk": p_chunk,
    }
    if return_all_probs:
        result["all_probs"] = all_probs
    return result


# ═══════════════════════════════════════════════════════════════
#  Baseline: Recursive STA/LTA
# ═══════════════════════════════════════════════════════════════

def recursive_sta_lta(
    data: np.ndarray,
    sta_samples: int,
    lta_samples: int,
    initial_lta: float = 1e-10,
) -> np.ndarray:
    """
    Recursive STA/LTA on a 1D trace.

    Uses the recursive formula:
        STA_n = STA_{n-1} * (1 - 1/n_sta) + x_n^2 / n_sta
        LTA_n = LTA_{n-1} * (1 - 1/n_lta) + x_n^2 / n_lta

    Returns the STA/LTA ratio array.
    """
    n = len(data)
    ratio = np.zeros(n, dtype=np.float64)

    c_sta = 1.0 / sta_samples
    c_lta = 1.0 / lta_samples

    sta_val = 0.0
    lta_val = initial_lta

    for i in range(n):
        x2 = float(data[i]) ** 2
        sta_val = sta_val * (1.0 - c_sta) + x2 * c_sta
        lta_val = lta_val * (1.0 - c_lta) + x2 * c_lta
        if lta_val > 1e-12:
            ratio[i] = sta_val / lta_val
        else:
            ratio[i] = 0.0

    return ratio


def eval_sta_lta(
    wave: np.ndarray,
    p_arrival_sample: float,
    threshold: float = STA_LTA_THRESHOLD,
    sta_sec: float = STA_DURATION_SEC,
    lta_sec: float = LTA_DURATION_SEC,
) -> dict:
    """
    Evaluate recursive STA/LTA detection on a 3-component trace.

    Uses the vertical (Z) component for STA/LTA.
    Detects when the STA/LTA ratio first exceeds the threshold.

    Returns dict with same fields as other eval functions.
    """
    npts = wave.shape[1]
    p_chunk = int(p_arrival_sample / SPC)
    total_chunks = min((npts + SPC - 1) // SPC, 320)

    sr = TARGET_SR
    sta_samples = max(int(sta_sec * sr), 1)
    lta_samples = max(int(lta_sec * sr), 1)

    # Use Z component (channel 0)
    z_data = wave[0].astype(np.float64)

    # Remove mean
    z_data = z_data - np.mean(z_data)

    # Compute STA/LTA
    ratio = recursive_sta_lta(z_data, sta_samples, lta_samples)

    # Find first sample where ratio exceeds threshold (after LTA has warmed up)
    warmup_samples = lta_samples  # Wait for LTA to stabilize
    first_detect_sample = None
    for i in range(warmup_samples, npts):
        if ratio[i] >= threshold:
            first_detect_sample = i
            break

    if first_detect_sample is not None:
        first_detect_chunk = first_detect_sample // SPC
        delay = (first_detect_chunk - p_chunk) * CHUNK_SEC
        detected = True
        first_detect_prob = float(ratio[first_detect_sample])
    else:
        first_detect_chunk = None
        delay = None
        detected = False
        first_detect_prob = 0.0

    return {
        "detected": detected,
        "first_detect_chunk": first_detect_chunk,
        "first_detect_prob": first_detect_prob,
        "delay_sec": delay,
        "p_chunk": p_chunk,
    }


# ═══════════════════════════════════════════════════════════════
#  CDF Computation and Plotting
# ═══════════════════════════════════════════════════════════════

def compute_cdf(delays: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute CDF from a list of delay values.

    Returns (sorted_delays, cdf_values) where cdf_values[i] = fraction of
    detected traces with delay <= sorted_delays[i].
    """
    if not delays:
        return np.array([]), np.array([])

    arr = np.sort(np.array(delays, dtype=np.float64))
    cdf = np.arange(1, len(arr) + 1, dtype=np.float64) / len(arr)
    return arr, cdf


def plot_cdf(
    model_results: dict[str, list[float]],
    output_path: str,
    title: str = "First-P Detection Delay CDF",
):
    """
    Plot CDF curves for all models.

    model_results: {model_name: list_of_delay_seconds}
    """
    setup_matplotlib_fonts()

    fig, ax = plt.subplots(1, 1, figsize=(10, 7))

    # Color and style mapping
    styles = {
        "CausalStreamingPPicker": {
            "color": "#E63946",       # Red
            "linestyle": "-",
            "linewidth": 2.5,
            "marker": "",
            "label": "CausalStreamingPPicker (ours)",
        },
        "PhaseNet": {
            "color": "#457B9D",       # Steel blue
            "linestyle": "--",
            "linewidth": 2.0,
            "marker": "",
            "label": "PhaseNet (streaming sim)",
        },
        "STA/LTA": {
            "color": "#2A9D8F",       # Teal
            "linestyle": "-.",
            "linewidth": 2.0,
            "marker": "",
            "label": "STA/LTA (recursive)",
        },
    }

    for model_name, delays in model_results.items():
        if not delays:
            continue
        x, y = compute_cdf(delays)
        s = styles.get(model_name, {"color": None, "linestyle": "-", "linewidth": 2.0, "label": model_name})
        ax.step(x, y, where="post",
                color=s.get("color"),
                linestyle=s.get("linestyle", "-"),
                linewidth=s.get("linewidth", 2.0),
                label=s.get("label", model_name),
                zorder=3)

    # Vertical line at P arrival (delay=0)
    ax.axvline(x=0, color="gray", linestyle=":", linewidth=1.5, alpha=0.7, zorder=2)
    ax.text(0.02, 0.02, "P arrival", transform=ax.get_yaxis_transform(),
            fontsize=10, color="gray", va="bottom", ha="left")

    # Shaded regions for ±0.5s, ±1.0s, ±1.5s
    for half_width, alpha in [(1.5, 0.05), (1.0, 0.05), (0.5, 0.05)]:
        ax.axvspan(-half_width, half_width, alpha=alpha, color="green", zorder=1)

    ax.set_xlabel("Detection Delay (s)  [negative = early, positive = late]", fontsize=12)
    ax.set_ylabel("Cumulative Fraction of Detections", fontsize=12)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlim(-5, 10)
    ax.set_ylim(0, 1.05)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", fontsize=11, framealpha=0.9)

    # Add detection count annotations
    info_lines = []
    for model_name, delays in model_results.items():
        if delays:
            info_lines.append(f"{model_name}: {len(delays)} detections")
    if info_lines:
        ax.text(0.02, 0.98, "\n".join(info_lines),
                transform=ax.transAxes, fontsize=9, va="top", ha="left",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="wheat", alpha=0.5))

    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  CDF plot saved to: {output_path}")


# ═══════════════════════════════════════════════════════════════
#  Debug: Per-Chunk Probability Curves
# ═══════════════════════════════════════════════════════════════

def plot_debug_curves(
    debug_traces: list[dict],
    output_dir: str,
):
    """Plot per-chunk probability curves for a few example traces."""
    setup_matplotlib_fonts()

    os.makedirs(output_dir, exist_ok=True)

    for i, dt in enumerate(debug_traces):
        fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

        source = dt.get("source", "unknown")
        trace_idx = dt.get("trace_idx", "?")
        p_chunk = dt.get("p_chunk", 0)

        # CausalStreamingPPicker
        ax = axes[0]
        probs = dt.get("causal_probs", [])
        if probs:
            chunks = np.arange(len(probs))
            ax.plot(chunks, probs, color="#E63946", linewidth=1.5, label="P(CausalStreamingPPicker)")
            ax.axhline(y=CAUSAL_THRESHOLD, color="#E63946", linestyle="--", alpha=0.5, label=f"threshold={CAUSAL_THRESHOLD}")
        ax.axvline(x=p_chunk, color="gray", linestyle=":", linewidth=1.5, alpha=0.7, label="P arrival")
        ax.set_ylabel("Probability")
        ax.set_title(f"Trace {i} (idx={trace_idx}, {source}) - CausalStreamingPPicker", fontsize=11)
        ax.legend(fontsize=9, loc="upper left")
        ax.grid(True, alpha=0.3)
        ax.set_ylim(-0.05, 1.05)

        # PhaseNet
        ax = axes[1]
        probs_pn = dt.get("phasenet_probs", [])
        if probs_pn:
            chunks_pn = np.arange(len(probs_pn))
            ax.plot(chunks_pn, probs_pn, color="#457B9D", linewidth=1.5, label="P(PhaseNet)")
            ax.axhline(y=SB_THRESHOLD, color="#457B9D", linestyle="--", alpha=0.5, label=f"threshold={SB_THRESHOLD}")
        ax.axvline(x=p_chunk, color="gray", linestyle=":", linewidth=1.5, alpha=0.7, label="P arrival")
        ax.set_ylabel("Probability")
        ax.set_title("PhaseNet (streaming sim)", fontsize=11)
        ax.legend(fontsize=9, loc="upper left")
        ax.grid(True, alpha=0.3)
        ax.set_ylim(-0.05, 1.05)

        # STA/LTA ratio (computed on-the-fly for debug)
        ax = axes[2]
        wave = dt.get("wave")
        if wave is not None:
            z_data = wave[0].astype(np.float64)
            z_data = z_data - np.mean(z_data)
            sta_samples = max(int(STA_DURATION_SEC * TARGET_SR), 1)
            lta_samples = max(int(LTA_DURATION_SEC * TARGET_SR), 1)
            ratio = recursive_sta_lta(z_data, sta_samples, lta_samples)
            # Downsample to chunk-level
            n_chunks = len(ratio) // SPC
            chunk_ratio = np.array([np.max(ratio[k*SPC:(k+1)*SPC]) for k in range(n_chunks)])
            ax.plot(np.arange(n_chunks), chunk_ratio, color="#2A9D8F", linewidth=1.5, label="STA/LTA ratio")
            ax.axhline(y=STA_LTA_THRESHOLD, color="#2A9D8F", linestyle="--", alpha=0.5, label=f"threshold={STA_LTA_THRESHOLD}")
        ax.axvline(x=p_chunk, color="gray", linestyle=":", linewidth=1.5, alpha=0.7, label="P arrival")
        ax.set_ylabel("STA/LTA Ratio")
        ax.set_xlabel("Chunk Index")
        ax.set_title("Recursive STA/LTA", fontsize=11)
        ax.legend(fontsize=9, loc="upper left")
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        fname = os.path.join(output_dir, f"debug_trace_{i}_idx{trace_idx}.png")
        plt.savefig(fname, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"    Debug plot saved: {fname}")


# ═══════════════════════════════════════════════════════════════
#  Summary Statistics
# ═══════════════════════════════════════════════════════════════

def print_summary(
    model_results: dict[str, dict],
    n_total: int,
):
    """Print summary statistics table for all models."""
    print(f"\n{'='*90}")
    print(f"  First-P Detection Delay Summary  (total traces = {n_total})")
    print(f"{'='*90}")

    header = (
        f"  {'Model':<30s} | {'Detect':>6s} {'Rate':>6s} "
        f"{'Mean':>7s} {'Median':>7s} {'P90':>7s} {'P95':>7s} "
        f"{'±0.5s':>6s} {'±1.0s':>6s} {'±1.5s':>6s}"
    )
    print(header)
    print(f"  {'-'*30} | {'-'*6} {'-'*6} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*6} {'-'*6} {'-'*6}")

    for model_name, res in model_results.items():
        delays = res["delays"]
        n_detected = len(delays)
        rate = n_detected / n_total if n_total > 0 else 0.0

        if n_detected > 0:
            arr = np.array(delays)
            mean_d = float(np.mean(arr))
            median_d = float(np.median(arr))
            p90 = float(np.percentile(arr, 90))
            p95 = float(np.percentile(arr, 95))

            within_05 = float(np.sum(np.abs(arr) <= 0.5)) / n_total
            within_10 = float(np.sum(np.abs(arr) <= 1.0)) / n_total
            within_15 = float(np.sum(np.abs(arr) <= 1.5)) / n_total
        else:
            mean_d = median_d = p90 = p95 = float("nan")
            within_05 = within_10 = within_15 = 0.0

        print(
            f"  {model_name:<30s} | {n_detected:>6d} {rate:>5.1%} "
            f"{mean_d:>+6.2f}s {median_d:>+6.2f}s {p90:>+6.2f}s {p95:>+6.2f}s "
            f"{within_05:>5.1%} {within_10:>5.1%} {within_15:>5.1%}"
        )

    print(f"{'='*90}")
    print(f"  Note: Delay = (first_detect_chunk - true_P_chunk) × {CHUNK_SEC}s")
    print(f"        Negative = early detection (before P arrival)")
    print(f"        Positive = late detection (after P arrival)")
    print(f"        ±Xs = fraction of ALL traces detected within Xs of P arrival")
    print(f"{'='*90}")


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="First-P Detection Delay CDF Evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--checkpoint", type=str, required=True,
                    help="Path to CausalStreamingPPicker checkpoint (.pt)")
    ap.add_argument("--phasenet-weights", type=str, default="instance",
                    help="PhaseNet pretrained weights name (default: instance)")
    ap.add_argument("--n-traces", type=int, default=1000,
                    help="Max number of test traces to evaluate (default: 1000)")
    ap.add_argument("--dataset", type=str, default="both",
                    choices=["ig", "knet", "both"],
                    help="Which dataset(s) to evaluate (default: both)")
    ap.add_argument("--knet-dir", type=str,
                    default=str(DATA_DIR / "knet_accel"),
                    help="Path to K-NET data directory")
    ap.add_argument("--min-mag", type=float, default=4.0,
                    help="Minimum magnitude filter (default: 4.0)")
    ap.add_argument("--device", type=str, default="cpu",
                    help="Device for inference (default: cpu)")
    ap.add_argument("--threshold-causal", type=float, default=CAUSAL_THRESHOLD,
                    help=f"Detection threshold for causal model (default: {CAUSAL_THRESHOLD})")
    ap.add_argument("--threshold-sb", type=float, default=SB_THRESHOLD,
                    help=f"Detection threshold for SeisBench models (default: {SB_THRESHOLD})")
    ap.add_argument("--threshold-stalta", type=float, default=STA_LTA_THRESHOLD,
                    help=f"Detection threshold for STA/LTA (default: {STA_LTA_THRESHOLD})")
    ap.add_argument("--max-chunks", type=int, default=320,
                    help="Maximum number of chunks per trace")
    ap.add_argument("--output", type=str,
                    default=str(FIGURES_DIR / "first_p_delay_cdf.png"),
                    help="Output CDF plot path")
    ap.add_argument("--debug", action="store_true",
                    help="Enable debug mode: save per-chunk probability curves for a few traces")
    ap.add_argument("--debug-n", type=int, default=5,
                    help="Number of debug traces to plot (default: 5)")
    ap.add_argument("--seed", type=int, default=42,
                    help="Random seed for trace sampling")
    args = ap.parse_args()

    # ── Device ──
    if args.device == "mps" and torch.backends.mps.is_available():
        device = torch.device("mps")
    elif args.device == "cuda" and torch.cuda.is_available():
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")
    print(f"Device: {device}")

    np.random.seed(args.seed)

    # ════════════════════════════════════════════════════════════
    #  Load CausalStreamingPPicker
    # ════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"  Loading CausalStreamingPPicker")
    print(f"{'='*70}")

    ckpt = torch.load(args.checkpoint, map_location=device, weights_only=False)
    if isinstance(ckpt, dict) and "model" in ckpt:
        sd = ckpt["model"]
        cfg = ckpt.get("config", {})
    else:
        sd = ckpt
        cfg = {}

    # Read model hyper-params from checkpoint config (fallback to defaults)
    encoder_hid = int(cfg.get("encoder_hid", 64))
    gru_hid = int(cfg.get("gru_hid", 128))
    gru_layers = int(cfg.get("gru_layers", 2))
    dropout = float(cfg.get("dropout", 0.25))
    max_chunks_ckpt = int(cfg.get("max_chunks", args.max_chunks))
    feature_mode = str(cfg.get("feature_mode", "zne"))

    causal_model = CausalStreamingPPickerModel(
        encoder_hid=encoder_hid, gru_hid=gru_hid,
        gru_layers=gru_layers, dropout=dropout,
        max_chunks=max_chunks_ckpt, feature_mode=feature_mode,
    ).to(device)

    model_sd = causal_model.state_dict()
    loaded, skipped = 0, 0
    for k, v in sd.items():
        if k in model_sd and v.shape == model_sd[k].shape:
            model_sd[k] = v
            loaded += 1
        else:
            skipped += 1
    causal_model.load_state_dict(model_sd)
    causal_model.eval()
    n_params = sum(p.numel() for p in causal_model.parameters())
    print(f"  Loaded: {args.checkpoint}")
    print(f"  Config: encoder_hid={encoder_hid}, gru_hid={gru_hid}, "
          f"gru_layers={gru_layers}, dropout={dropout}")
    print(f"  Parameters: {n_params:,} ({loaded} loaded, {skipped} skipped)")

    # ════════════════════════════════════════════════════════════
    #  Load SeisBench PhaseNet
    # ════════════════════════════════════════════════════════════
    has_phasenet = False
    phasenet = None
    if HAS_SEISBENCH and args.phasenet_weights:
        print(f"\n{'='*70}")
        print(f"  Loading PhaseNet (pretrained: {args.phasenet_weights})")
        print(f"{'='*70}")
        try:
            phasenet = sbm.PhaseNet.from_pretrained(args.phasenet_weights)
            phasenet = phasenet.to(device)
            phasenet.eval()
            pn_params = sum(p.numel() for p in phasenet.parameters())
            print(f"  Parameters: {pn_params:,}")
            print(f"  Input: {phasenet.in_samples} samples "
                  f"({phasenet.in_samples / phasenet.sampling_rate:.1f}s)")
            min_chunks_pn = int(math.ceil(phasenet.in_samples / SPC))
            print(f"  Min chunks before detection possible: {min_chunks_pn}")
            has_phasenet = True
        except Exception as e:
            print(f"  ERROR loading PhaseNet: {e}")
            has_phasenet = False

    # ════════════════════════════════════════════════════════════
    #  Load Test Data
    # ════════════════════════════════════════════════════════════
    all_traces = []

    if args.dataset in ("ig", "both"):
        n_ig = args.n_traces if args.dataset == "ig" else args.n_traces // 2
        ig_traces = load_ig_test(min_mag=args.min_mag, n_traces=n_ig, seed=args.seed)
        all_traces.extend(ig_traces)

    if args.dataset in ("knet", "both"):
        knet_traces = load_knet_test(args.knet_dir, min_mag=args.min_mag)
        if args.dataset == "both":
            # Fill remaining quota with K-NET
            remaining = args.n_traces - len(all_traces)
            if remaining > 0 and len(knet_traces) > remaining:
                rng = np.random.RandomState(args.seed)
                idx = rng.choice(len(knet_traces), size=remaining, replace=False)
                knet_traces = [knet_traces[i] for i in idx]
        all_traces.extend(knet_traces)

    if not all_traces:
        print("ERROR: No test traces loaded. Exiting.")
        return

    print(f"\n  Total traces to evaluate: {len(all_traces)}")

    # ════════════════════════════════════════════════════════════
    #  Run Evaluation
    # ════════════════════════════════════════════════════════════
    from tqdm import tqdm

    # Results storage
    causal_delays = []       # delay_sec for detected traces
    phasenet_delays = []
    stalta_delays = []

    causal_n_detected = 0
    phasenet_n_detected = 0
    stalta_n_detected = 0

    # Debug storage
    debug_traces_data = []
    debug_count = 0

    print(f"\n{'='*70}")
    print(f"  Running streaming evaluation")
    print(f"{'='*70}")

    for t_idx, trace_info in enumerate(tqdm(all_traces, desc="Evaluating", ncols=100)):
        wave = trace_info["wave"]
        p_s = trace_info["p_sample"]

        is_debug = args.debug and debug_count < args.debug_n

        # ── CausalStreamingPPicker ──
        try:
            r_causal = eval_causal_streaming(
                causal_model, wave, p_s, device,
                threshold=args.threshold_causal,
                max_chunks=args.max_chunks,
                return_all_probs=is_debug,
            )
            if r_causal["detected"]:
                causal_delays.append(r_causal["delay_sec"])
                causal_n_detected += 1
            if is_debug:
                debug_data = {
                    "source": trace_info["source"],
                    "trace_idx": trace_info["idx"],
                    "p_chunk": r_causal["p_chunk"],
                    "wave": wave,
                    "causal_probs": r_causal.get("all_probs", []),
                }
        except Exception as e:
            if is_debug:
                debug_data = {"source": trace_info["source"], "trace_idx": trace_info["idx"],
                              "p_chunk": int(p_s / SPC), "wave": wave, "causal_probs": []}

        # ── PhaseNet streaming sim ──
        if has_phasenet:
            try:
                r_pn = eval_phasenet_streaming(
                    phasenet, wave, p_s, device,
                    threshold=args.threshold_sb,
                    max_chunks=args.max_chunks,
                    return_all_probs=is_debug,
                )
                if r_pn["detected"]:
                    phasenet_delays.append(r_pn["delay_sec"])
                    phasenet_n_detected += 1
                if is_debug:
                    debug_data["phasenet_probs"] = r_pn.get("all_probs", [])
            except Exception as e:
                if is_debug:
                    debug_data["phasenet_probs"] = []

        # ── STA/LTA ──
        try:
            r_sl = eval_sta_lta(
                wave, p_s,
                threshold=args.threshold_stalta,
            )
            if r_sl["detected"]:
                stalta_delays.append(r_sl["delay_sec"])
                stalta_n_detected += 1
        except Exception:
            pass

        # Collect debug trace
        if is_debug:
            debug_traces_data.append(debug_data)
            debug_count += 1

        # ── MPS memory cleanup ──
        if device.type == "mps":
            gc.collect()
            torch.mps.empty_cache()

    n_total = len(all_traces)

    # ════════════════════════════════════════════════════════════
    #  Plot CDF
    # ════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"  Generating CDF plot")
    print(f"{'='*70}")

    cdf_data = {
        "CausalStreamingPPicker": causal_delays,
        "PhaseNet": phasenet_delays if has_phasenet else [],
        "STA/LTA": stalta_delays,
    }
    plot_cdf(cdf_data, args.output)

    # ════════════════════════════════════════════════════════════
    #  Print Summary Statistics
    # ════════════════════════════════════════════════════════════
    summary = {
        "CausalStreamingPPicker": {
            "delays": causal_delays,
        },
    }
    if has_phasenet:
        summary["PhaseNet"] = {"delays": phasenet_delays}
    summary["STA/LTA"] = {"delays": stalta_delays}

    print_summary(summary, n_total)

    # ════════════════════════════════════════════════════════════
    #  Detailed Per-Model Breakdown
    # ════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"  Detailed Per-Model Statistics")
    print(f"{'='*70}")

    for model_name, data in summary.items():
        delays = data["delays"]
        n_det = len(delays)
        rate = n_det / n_total if n_total > 0 else 0.0
        print(f"\n  {model_name}:")
        print(f"    Detection rate: {n_det}/{n_total} = {rate:.1%}")
        if n_det > 0:
            arr = np.array(delays)
            print(f"    Mean delay:    {np.mean(arr):+.3f}s")
            print(f"    Median delay:  {np.median(arr):+.3f}s")
            print(f"    Std delay:     {np.std(arr):.3f}s")
            print(f"    P10 delay:     {np.percentile(arr, 10):+.3f}s")
            print(f"    P25 delay:     {np.percentile(arr, 25):+.3f}s")
            print(f"    P75 delay:     {np.percentile(arr, 75):+.3f}s")
            print(f"    P90 delay:     {np.percentile(arr, 90):+.3f}s")
            print(f"    P95 delay:     {np.percentile(arr, 95):+.3f}s")
            print(f"    Min delay:     {np.min(arr):+.3f}s")
            print(f"    Max delay:     {np.max(arr):+.3f}s")

            # Within tolerance windows
            for tol in [0.5, 1.0, 1.5, 2.0, 3.0]:
                within = float(np.sum(np.abs(arr) <= tol)) / n_total
                print(f"    Within ±{tol:.1f}s: {within:.1%} of all traces")

            # Early vs late
            n_early = int(np.sum(arr < 0))
            n_late = int(np.sum(arr >= 0))
            n_ontime = int(np.sum(np.abs(arr) <= CHUNK_SEC))
            print(f"    Early (<0s):   {n_early}/{n_det} = {n_early/max(n_det,1):.1%}")
            print(f"    Late  (≥0s):   {n_late}/{n_det} = {n_late/max(n_det,1):.1%}")
            print(f"    On-time (±{CHUNK_SEC}s): {n_ontime}/{n_det} = {n_ontime/max(n_det,1):.1%}")

    # ════════════════════════════════════════════════════════════
    #  Debug Plots
    # ════════════════════════════════════════════════════════════
    if args.debug and debug_traces_data:
        print(f"\n{'='*70}")
        print(f"  Generating debug probability curves ({len(debug_traces_data)} traces)")
        print(f"{'='*70}")
        debug_dir = os.path.join(os.path.dirname(args.output), "debug_curves")
        plot_debug_curves(debug_traces_data, debug_dir)

    print(f"\n  Done! CDF plot: {args.output}")


if __name__ == "__main__":
    main()
