#!/usr/bin/env python3
"""Small external labeled waveform smoke benchmark via SeisBench.

This script uses SeisBench labels. It never creates P labels.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import SAMPLES_PER_CHUNK, TARGET_SR  # noqa: E402
from data_streaming import normalize_packet_causal  # noqa: E402
from eval_multidomain_test import DOMAIN_KNET_STRONG, load_model  # noqa: E402

CHUNK_SEC = SAMPLES_PER_CHUNK / TARGET_SR
DATASET_CACHE_DIR = {
    "CWA": "cwa",
    "InstanceGM": "instancegm",
    "Iquique": "iquique",
    "PNWAccelerometers": "pnwaccelerometers",
}

P_SAMPLE_COLUMNS = [
    "trace_p_arrival_sample",
    "trace_P_arrival_sample",
    "p_arrival_sample",
    "P_arrival_sample",
    "trace_p_arrival_samples",
]

P_UNCERTAINTY_COLUMNS = [
    "trace_p_arrival_uncertainty_s",
    "trace_P_arrival_uncertainty_s",
    "p_arrival_uncertainty_s",
    "P_arrival_uncertainty_s",
]


def first_existing(columns: list[str], candidates: list[str]) -> str | None:
    lower = {c.lower(): c for c in columns}
    for name in candidates:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def min_pipe_float(value: Any) -> float:
    try:
        vals = [float(v) for v in str(value).split("|") if v != ""]
    except ValueError:
        return float("nan")
    return min(vals) if vals else float("nan")


def looks_tsmip(row: pd.Series) -> bool:
    text = " ".join(str(v) for k, v in row.items() if any(s in k.lower() for s in ["network", "station", "channel", "instrument"]))
    return "TSMIP" in text.upper()


def category(gap: int | None, margin: int) -> str:
    if gap is None:
        return "miss"
    if abs(gap) <= 1:
        return "perfect"
    if abs(gap) <= margin:
        return "good"
    return "early" if gap < -margin else "late"


def first_confirmed(probs: np.ndarray, threshold: float, confirm_chunks: int) -> tuple[int | None, float]:
    for i in range(max(0, len(probs) - confirm_chunks + 1)):
        if np.all(probs[i : i + confirm_chunks] >= threshold):
            j = i + confirm_chunks - 1
            return j, float(probs[j])
    return None, float("nan")


def to_cw(wave: np.ndarray) -> np.ndarray:
    wave = np.asarray(wave, dtype=np.float32)
    if wave.ndim != 2:
        raise ValueError(f"expected 2D waveform, got shape={wave.shape}")
    if wave.shape[0] > wave.shape[1]:
        wave = wave.T
    if wave.shape[0] < 3:
        pad = np.zeros((3 - wave.shape[0], wave.shape[1]), dtype=np.float32)
        wave = np.vstack([wave, pad])
    return wave[:3]


def chunk_trace(trace: np.ndarray, max_chunks: int) -> tuple[torch.Tensor, int]:
    npts = trace.shape[1]
    n_chunks = min((npts + SAMPLES_PER_CHUNK - 1) // SAMPLES_PER_CHUNK, max_chunks)
    chunks = np.zeros((max_chunks, 3, SAMPLES_PER_CHUNK), dtype=np.float32)
    running = None
    for k in range(n_chunks):
        a = k * SAMPLES_PER_CHUNK
        b = min((k + 1) * SAMPLES_PER_CHUNK, npts)
        seg = trace[:, a:b]
        valid = None
        if b - a < SAMPLES_PER_CHUNK:
            valid = b - a
            seg = np.pad(seg, ((0, 0), (0, SAMPLES_PER_CHUNK - (b - a))))
        normed, running = normalize_packet_causal(seg.astype(np.float64), running, valid_samples=valid)
        chunks[k] = normed.astype(np.float32)
    return torch.from_numpy(chunks), n_chunks


def summarize(rows: list[dict[str, Any]], margin: int) -> dict[str, Any]:
    cats = Counter(r["category"] for r in rows)
    n = len(rows)
    detected = n - cats.get("miss", 0)
    usable = cats.get("perfect", 0) + cats.get("good", 0)
    gaps = np.asarray([r["gap_chunks"] for r in rows if r["gap_chunks"] is not None], dtype=float)
    out: dict[str, Any] = {
        "status": "ok" if n else "no_rows",
        "n": n,
        "detected": detected,
        "usable": usable,
        "detect_rate": detected / n * 100 if n else 0.0,
        "usable_rate": usable / n * 100 if n else 0.0,
        "perfect_rate": cats.get("perfect", 0) / n * 100 if n else 0.0,
        "categories": dict(cats),
        "margin_chunks": margin,
        "boundary": f"{rows[0].get('dataset', 'SeisBench')} labeled smoke benchmark; not full external validation until scaled and frozen." if rows else "SeisBench labeled smoke benchmark; no rows.",
    }
    if len(gaps):
        out.update(
            {
                "median_gap_chunks": float(np.median(gaps)),
                "mean_gap_chunks": float(np.mean(gaps)),
                "p95_abs_gap_chunks": float(np.percentile(np.abs(gaps), 95)),
            }
        )
    return out


def write_text_report(args: argparse.Namespace, summary: dict[str, Any], rows_path: Path, error: str | None = None) -> str:
    lines = [
            "External labeled waveform smoke benchmark",
        "=" * 52,
        f"dataset: {args.dataset}",
        f"chunks: {args.chunks}",
        f"max_samples: {args.max_samples}",
        f"threshold: {args.threshold}",
        f"confirm_chunks: {args.confirm_chunks}",
        f"min_snr_db: {args.min_snr_db}",
        f"min_magnitude: {args.min_magnitude}",
        f"max_p_uncertainty_s: {args.max_p_uncertainty_s}",
        f"decision_start_offset_chunks: {args.decision_start_offset_chunks}",
        f"rows: {rows_path}",
        "",
    ]
    if error:
        lines += [f"STATUS: {summary.get('status', 'error')}", error]
    else:
        lines += [
            f"n: {summary['n']}",
            f"detected: {summary['detected']}/{summary['n']} = {summary['detect_rate']:.1f}%",
            f"usable: {summary['usable']}/{summary['n']} = {summary['usable_rate']:.1f}%",
            f"perfect: {summary['perfect_rate']:.1f}%",
            f"categories: {summary['categories']}",
            f"median_gap_chunks: {summary.get('median_gap_chunks')}",
            "",
            f"Boundary: {summary['boundary']}",
        ]
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=sorted(DATASET_CACHE_DIR), default="InstanceGM")
    p.add_argument("--chunks", default="", help="Comma-separated SeisBench chunks. For CWA use _2021 etc.; for PNWAccelerometers leave empty.")
    p.add_argument("--checkpoint", type=Path, default=Path("models/checkpoints/multidomain_physics/multidomain_best.pt"))
    p.add_argument("--out-dir", type=Path, default=Path("outputs/evaluation/external_labeled_accel_smoke"))
    p.add_argument("--tag", default="theta055_confirm2_firstp")
    p.add_argument("--max-samples", type=int, default=50)
    p.add_argument("--max-chunks", type=int, default=120)
    p.add_argument("--threshold", type=float, default=0.55)
    p.add_argument("--confirm-chunks", type=int, default=2)
    p.add_argument("--margin", type=int, default=3)
    p.add_argument("--min-snr-db", type=float, default=None)
    p.add_argument("--min-magnitude", type=float, default=None)
    p.add_argument("--max-p-uncertainty-s", type=float, default=None)
    p.add_argument("--decision-start-offset-chunks", type=int, default=None, help="If set, first-trigger search starts at the labeled P-arrival chunk plus this offset. Use only for near-P-arrival sensitivity checks, not false-trigger auditing.")
    p.add_argument("--seed", type=int, default=20260617)
    p.add_argument("--device", default="cpu")
    p.add_argument("--allow-all-cwa", action="store_true", help="Run on all CWA rows if TSMIP rows cannot be identified.")
    p.add_argument("--download", action="store_true", help="Allow SeisBench to download missing chunks. CWA chunks can be tens of GB.")
    return p.parse_args()


def missing_cache_files(dataset: str, chunks: list[str]) -> list[Path]:
    import seisbench

    root = Path(seisbench.cache_root) / "datasets" / DATASET_CACHE_DIR[dataset]
    missing = []
    for chunk in chunks:
        suffix = chunk.lstrip("_")
        names = [f"waveforms{chunk}.hdf5", f"waveforms_{suffix}.hdf5", "waveforms.hdf5"]
        if not any((root / name).exists() for name in names):
            missing.append(root / names[0])
    return missing


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = args.out_dir / f"{args.tag}_rows.csv"
    summary_path = args.out_dir / f"{args.tag}_summary.txt"
    json_path = args.out_dir / f"{args.tag}_summary.json"

    import seisbench.data as sbd

    chunks = [c.strip() for c in args.chunks.split(",") if c.strip()]
    if not chunks:
        chunks = [""]
    if not args.download:
        missing = missing_cache_files(args.dataset, chunks)
        if missing:
            summary = {
                "status": "missing_local_seisbench_cache",
                "dataset": args.dataset,
                "missing_waveform_files": [str(p) for p in missing],
                "message": "Re-run with --download only if you intentionally want to fetch missing SeisBench data.",
            }
            json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
            summary_path.write_text(write_text_report(args, summary, rows_path, summary["message"]), encoding="utf-8")
            print(summary_path)
            return
    dataset_cls = getattr(sbd, args.dataset)
    dataset_kwargs = dict(sampling_rate=TARGET_SR, component_order="ZNE", cache=None)
    if args.dataset in {"CWA", "PNWAccelerometers"}:
        dataset_kwargs["chunks"] = chunks
        dataset_kwargs["dimension_order"] = "NCW"
    ds = dataset_cls(**dataset_kwargs)
    meta = ds.metadata.reset_index(drop=True)
    p_col = first_existing(list(meta.columns), P_SAMPLE_COLUMNS)
    if p_col is None:
        summary = {"status": "missing_p_label_column", "columns": list(meta.columns)}
        json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        summary_path.write_text(write_text_report(args, summary, rows_path, "No P-arrival sample column found."), encoding="utf-8")
        raise SystemExit(2)

    mask = meta[p_col].notna()
    p_unc_col = first_existing(list(meta.columns), P_UNCERTAINTY_COLUMNS)
    if args.min_snr_db is not None:
        if "trace_snr_db" not in meta:
            raise SystemExit("--min-snr-db requested, but trace_snr_db is missing.")
        mask &= meta["trace_snr_db"].map(min_pipe_float).ge(args.min_snr_db)
    if args.min_magnitude is not None:
        if "preferred_source_magnitude" not in meta:
            raise SystemExit("--min-magnitude requested, but preferred_source_magnitude is missing.")
        mask &= meta["preferred_source_magnitude"].ge(args.min_magnitude)
    if args.max_p_uncertainty_s is not None:
        if p_unc_col is None:
            raise SystemExit("--max-p-uncertainty-s requested, but P uncertainty column is missing.")
        mask &= meta[p_unc_col].le(args.max_p_uncertainty_s)
    tsmip_mask = meta.apply(looks_tsmip, axis=1)
    if args.dataset == "CWA" and tsmip_mask.any():
        mask &= tsmip_mask
    elif args.dataset == "CWA" and not args.allow_all_cwa:
        summary = {"status": "no_tsmip_rows_identified", "p_label_column": p_col, "columns": list(meta.columns)}
        json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        summary_path.write_text(write_text_report(args, summary, rows_path, "No rows were identifiable as TSMIP. Re-run with --allow-all-cwa to smoke-test all CWA rows."), encoding="utf-8")
        raise SystemExit(2)

    candidates = meta.index[mask].to_numpy().copy()
    rng = np.random.default_rng(args.seed)
    rng.shuffle(candidates)
    candidates = candidates[: args.max_samples]

    device = torch.device(args.device)
    model = load_model(args.checkpoint, device)
    model.eval()
    rows: list[dict[str, Any]] = []
    with torch.inference_mode():
        for idx in candidates:
            wave, sample_meta = ds.get_sample(int(idx), sampling_rate=TARGET_SR)
            trace = to_cw(wave)
            chunks_tensor, n_chunks = chunk_trace(trace, args.max_chunks)
            x = chunks_tensor.unsqueeze(0).to(device)
            domain_ids = None
            if getattr(model, "uses_domain_ids", False):
                domain_ids = torch.full((1,), DOMAIN_KNET_STRONG, device=device, dtype=torch.long)
            logits, _, _ = model(x, domain_ids=domain_ids)
            probs = torch.sigmoid(logits[0, :n_chunks]).detach().cpu().numpy()
            target_chunk = int(round(float(sample_meta[p_col]) / SAMPLES_PER_CHUNK))
            decision_start = 0 if args.decision_start_offset_chunks is None else max(0, target_chunk + args.decision_start_offset_chunks)
            first, first_prob = first_confirmed(probs[decision_start:], args.threshold, args.confirm_chunks)
            if first is not None:
                first += decision_start
            gap = None if first is None else int(first - target_chunk)
            rows.append(
                {
                    "dataset_index": int(idx),
                    "dataset": args.dataset,
                    "trace_name": sample_meta.get("trace_name", ""),
                    "p_label_column": p_col,
                    "target_chunk": target_chunk,
                    "decision_start_chunk": decision_start,
                    "first_trigger_chunk": first,
                    "gap_chunks": gap,
                    "gap_seconds": None if gap is None else gap * CHUNK_SEC,
                    "category": category(gap, args.margin),
                    "first_prob": first_prob,
                    "n_chunks": n_chunks,
                    "preferred_source_magnitude": sample_meta.get("preferred_source_magnitude", ""),
                    "snr_min_db": min_pipe_float(sample_meta.get("trace_snr_db", "")),
                    "p_uncertainty_s": sample_meta.get(p_unc_col, "") if p_unc_col else "",
                    "label_boundary": f"SeisBench {args.dataset} P label; smoke subset",
                }
            )

    pd.DataFrame(rows).to_csv(rows_path, index=False)
    summary = summarize(rows, args.margin)
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(write_text_report(args, summary, rows_path), encoding="utf-8")
    print(summary_path)


if __name__ == "__main__":
    main()
