"""Spike-injected pseudo-continuous false-alarm stress test.

The existing continuous false-alarm replay uses real K-NET pre-P noise
fragments. This script keeps the same station-wise replay protocol, but injects
one deterministic synthetic transient into each fragment before replay. The goal
is to test whether isolated spikes or short packet-scale bursts can create
confirmed false triggers under the same operating rules used in the manuscript.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "scripts" / "evaluation"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from eval_continuous_false_alarm_sim import (  # noqa: E402
    CHUNK_SEC,
    SAMPLES_PER_CHUNK,
    collect_noise_segments,
    load_model,
    normalize_packet_causal,
    parse_csv_floats,
    parse_csv_ints,
)


def robust_rms(wave: np.ndarray) -> float:
    centered = wave - np.median(wave, axis=1, keepdims=True)
    mad = np.median(np.abs(centered))
    if np.isfinite(mad) and mad > 0:
        return float(1.4826 * mad)
    rms = float(np.sqrt(np.mean(centered**2)))
    return max(rms, 1e-8)


def stable_seed(base_seed: int, station: str, scenario: str) -> int:
    digest = hashlib.sha256(f"{base_seed}|{station}|{scenario}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "little", signed=False)


def choose_injection_chunk(n_chunks: int, boundary_exclude_chunks: int, rng: np.random.Generator) -> int | None:
    lo = max(boundary_exclude_chunks, 0)
    hi = n_chunks - 1
    if hi < lo:
        return None
    return int(rng.integers(lo, hi + 1))


def inject_transient(
    wave: np.ndarray,
    scenario: str,
    boundary_exclude_chunks: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, int | None, str]:
    """Return a copy of wave with one injected transient and its chunk index."""
    out = wave.copy()
    n_chunks = out.shape[1] // SAMPLES_PER_CHUNK
    inj_chunk = choose_injection_chunk(n_chunks, boundary_exclude_chunks, rng)
    if inj_chunk is None:
        return out, None, "none"

    scale = robust_rms(out)
    start = inj_chunk * SAMPLES_PER_CHUNK
    stop = start + SAMPLES_PER_CHUNK
    polarity = -1.0 if rng.random() < 0.5 else 1.0

    if scenario == "clean":
        return out, None, "none"
    if scenario == "impulse_x20":
        channel = int(rng.integers(0, min(3, out.shape[0])))
        sample = int(rng.integers(start, stop))
        out[channel, sample] += polarity * 20.0 * scale
        return out, inj_chunk, f"channel={channel};sample={sample-start};scale=20"
    if scenario == "impulse_x50":
        channel = int(rng.integers(0, min(3, out.shape[0])))
        sample = int(rng.integers(start, stop))
        out[channel, sample] += polarity * 50.0 * scale
        return out, inj_chunk, f"channel={channel};sample={sample-start};scale=50"
    if scenario == "packet_burst_x20":
        width = min(8, SAMPLES_PER_CHUNK)
        offset = int(rng.integers(0, SAMPLES_PER_CHUNK - width + 1))
        window = np.hanning(width + 2)[1:-1].astype(np.float32)
        channels = np.arange(min(3, out.shape[0]))
        signs = rng.choice(np.array([-1.0, 1.0], dtype=np.float32), size=len(channels))
        for ch, sign in zip(channels, signs):
            out[int(ch), start + offset : start + offset + width] += sign * 20.0 * scale * window
        return out, inj_chunk, f"channels=all;width={width};offset={offset};scale=20"
    raise ValueError(f"Unknown spike scenario: {scenario}")


@torch.inference_mode()
def replay_scenario(
    model,
    station_segments,
    scenario: str,
    device: torch.device,
    boundary_exclude_chunks: int,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict] = []
    injection_rows: list[dict] = []

    for station in sorted(station_segments):
        h = None
        prev_feat = None
        running_stats = None
        station_chunk = 0
        rng = np.random.default_rng(stable_seed(seed, station, scenario))
        segments = sorted(
            station_segments[station],
            key=lambda item: (item[0].event_name, item[0].trace_name, item[0].metadata_index),
        )

        for seg_pos, (info, noise) in enumerate(segments):
            injected, inj_chunk, inj_detail = inject_transient(
                noise,
                scenario=scenario,
                boundary_exclude_chunks=boundary_exclude_chunks,
                rng=rng,
            )
            injection_rows.append(
                {
                    **asdict(info),
                    "scenario": scenario,
                    "segment_position": seg_pos,
                    "injection_chunk": -1 if inj_chunk is None else inj_chunk,
                    "injection_detail": inj_detail,
                }
            )

            n_chunks = injected.shape[1] // SAMPLES_PER_CHUNK
            for local_chunk in range(n_chunks):
                a = local_chunk * SAMPLES_PER_CHUNK
                b = a + SAMPLES_PER_CHUNK
                raw = injected[:, a:b].astype(np.float64, copy=False)
                normed, running_stats = normalize_packet_causal(raw, running_stats)
                pkt = torch.from_numpy(normed.astype(np.float32)).to(device).unsqueeze(0)
                logit, h, prev_feat = model.forward_streaming_packet(
                    pkt,
                    h_prev=h,
                    packet_idx=station_chunk,
                    prev_feat=prev_feat,
                )
                prob = float(torch.sigmoid(logit.reshape(-1)[0]).item())
                rows.append(
                    {
                        "scenario": scenario,
                        "station_code": station,
                        "segment_id": info.segment_id,
                        "trace_name": info.trace_name,
                        "event_name": info.event_name,
                        "segment_position": seg_pos,
                        "local_chunk": local_chunk,
                        "station_chunk": station_chunk,
                        "time_sec": station_chunk * CHUNK_SEC,
                        "prob": prob,
                        "boundary_excluded": bool(local_chunk < boundary_exclude_chunks),
                        "is_injection_chunk": bool(inj_chunk is not None and local_chunk == inj_chunk),
                        "is_post_injection_2pkt": bool(
                            inj_chunk is not None and inj_chunk <= local_chunk <= inj_chunk + 1
                        ),
                    }
                )
                station_chunk += 1

        if device.type == "mps":
            torch.mps.empty_cache()

    return pd.DataFrame(rows), pd.DataFrame(injection_rows)


def episode_rows(station_df: pd.DataFrame, threshold: float, confirm: int) -> list[dict]:
    rows: list[dict] = []
    active = (
        (~station_df["boundary_excluded"].to_numpy(dtype=bool))
        & (station_df["prob"].to_numpy(dtype=np.float64) >= threshold)
    )
    run_start: int | None = None
    run_len = 0
    for i, is_active in enumerate(active):
        if bool(is_active):
            if run_start is None:
                run_start = i
                run_len = 1
            else:
                run_len += 1
        else:
            if run_start is not None and run_len >= confirm:
                sub = station_df.iloc[run_start : run_start + run_len]
                rows.append(
                    {
                        "station_code": str(station_df["station_code"].iloc[0]),
                        "start_station_chunk": int(sub["station_chunk"].iloc[0]),
                        "duration_chunks": int(run_len),
                        "max_prob": float(sub["prob"].max()),
                        "contains_injection_chunk": bool(sub["is_injection_chunk"].any()),
                        "contains_post_injection_2pkt": bool(sub["is_post_injection_2pkt"].any()),
                    }
                )
            run_start = None
            run_len = 0
    if run_start is not None and run_len >= confirm:
        sub = station_df.iloc[run_start : run_start + run_len]
        rows.append(
            {
                "station_code": str(station_df["station_code"].iloc[0]),
                "start_station_chunk": int(sub["station_chunk"].iloc[0]),
                "duration_chunks": int(run_len),
                "max_prob": float(sub["prob"].max()),
                "contains_injection_chunk": bool(sub["is_injection_chunk"].any()),
                "contains_post_injection_2pkt": bool(sub["is_post_injection_2pkt"].any()),
            }
        )
    return rows


def summarize_probs(probs_df: pd.DataFrame, thresholds: list[float], confirms: list[int]) -> pd.DataFrame:
    rows: list[dict] = []
    valid = ~probs_df["boundary_excluded"].to_numpy(dtype=bool)
    hours = float(valid.sum()) * CHUNK_SEC / 3600.0
    stations = int(probs_df["station_code"].nunique())
    segments = int(probs_df["segment_id"].nunique())
    injection_chunks = probs_df["is_injection_chunk"].to_numpy(dtype=bool)
    post_injection = probs_df["is_post_injection_2pkt"].to_numpy(dtype=bool)

    for threshold in thresholds:
        over = valid & (probs_df["prob"].to_numpy(dtype=np.float64) >= threshold)
        injected_over = int((over & injection_chunks).sum())
        post_injected_over = int((over & post_injection).sum())
        for confirm in confirms:
            episodes: list[dict] = []
            for _, station_df in probs_df.groupby("station_code", sort=False):
                episodes.extend(episode_rows(station_df, threshold=threshold, confirm=confirm))
            ep_df = pd.DataFrame(episodes)
            if ep_df.empty:
                alarm_episodes = 0
                stations_with_alarm = 0
                injection_related = 0
            else:
                alarm_episodes = int(len(ep_df))
                stations_with_alarm = int(ep_df["station_code"].nunique())
                injection_related = int(ep_df["contains_post_injection_2pkt"].sum())
            rows.append(
                {
                    "scenario": str(probs_df["scenario"].iloc[0]),
                    "threshold": threshold,
                    "confirm_chunks": confirm,
                    "segments": segments,
                    "stations": stations,
                    "boundary_excluded_chunks": int(valid.sum()),
                    "boundary_excluded_hours": hours,
                    "over_threshold_chunks": int(over.sum()),
                    "over_threshold_rate_percent": float(over.sum() / valid.sum() * 100.0) if valid.sum() else 0.0,
                    "injection_chunks_over_threshold": injected_over,
                    "post_injection_2pkt_over_threshold": post_injected_over,
                    "alarm_episodes": alarm_episodes,
                    "alarm_episodes_per_hour": alarm_episodes / hours if hours else 0.0,
                    "injection_related_alarm_episodes": injection_related,
                    "stations_with_alarm": stations_with_alarm,
                    "station_alarm_rate_percent": stations_with_alarm / stations * 100.0 if stations else 0.0,
                }
            )
    return pd.DataFrame(rows)


def markdown_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)

    def fmt(value) -> str:
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(fmt(row[col]) for col in cols) + " |")
    return "\n".join(lines)


def write_report(out_dir: Path, summary: pd.DataFrame, metadata: dict) -> Path:
    report = out_dir / "spike_false_alarm_stress_report.md"
    lines = [
        "# Spike-Injected False-Alarm Stress Test",
        "",
        "This offline test augments K-NET pre-P noise fragments with one deterministic synthetic transient per fragment, then replays station-wise streams with causal model state.",
        "",
        "## Protocol",
        "",
        f"- Checkpoint: `{metadata['checkpoint']}`",
        f"- K-NET filter: split={metadata['split']}, min_mag={metadata['min_mag']}, max_dist={metadata['max_dist']}",
        f"- Guard before P: {metadata['guard_chunks']} packets; boundary exclusion: {metadata['boundary_exclude_chunks']} packets",
        f"- Scenarios: {', '.join(metadata['scenarios'])}",
        "- False-trigger episodes are counted after boundary exclusion and require the stated number of consecutive above-threshold packets.",
        "- Injection-related episodes are runs that overlap the injected chunk or the immediately following packet.",
        "",
        "## Summary",
        "",
        markdown_table(summary),
        "",
        "## Interpretation Boundary",
        "",
        "This is a stress test for isolated transient artifacts in event-window pre-P noise, not a substitute for station-day continuous non-event replay. A public alert still requires station association and source-consistency checks outside the single-station picker.",
    ]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", type=Path, default=ROOT / "models/checkpoints/multidomain_best.pt")
    ap.add_argument("--knet-dir", type=Path, default=ROOT / "data/knet_accel")
    ap.add_argument("--split", default="test", choices=["train", "dev", "test"])
    ap.add_argument("--min-mag", type=float, default=4.0)
    ap.add_argument("--max-dist", type=float, default=200.0)
    ap.add_argument("--guard-chunks", type=int, default=5)
    ap.add_argument("--min-noise-chunks", type=int, default=5)
    ap.add_argument("--boundary-exclude-chunks", type=int, default=2)
    ap.add_argument("--thresholds", default="0.55")
    ap.add_argument("--confirm-list", default="1,2,3")
    ap.add_argument("--scenarios", default="clean,impulse_x20,impulse_x50,packet_burst_x20")
    ap.add_argument("--max-segments", type=int, default=0)
    ap.add_argument("--seed", type=int, default=20260616)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--output-dir", type=Path, default=ROOT / "outputs/evaluation/spike_false_alarm_stress")
    args = ap.parse_args()

    if args.device == "mps" and not torch.backends.mps.is_available():
        args.device = "cpu"
    device = torch.device(args.device)
    thresholds = parse_csv_floats(args.thresholds)
    confirms = parse_csv_ints(args.confirm_list)
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    model = load_model(args.checkpoint, device)
    _, segments, station_segments = collect_noise_segments(
        args.knet_dir,
        split=args.split,
        min_mag=args.min_mag,
        max_dist=args.max_dist,
        guard_chunks=args.guard_chunks,
        min_noise_chunks=args.min_noise_chunks,
        max_segments=args.max_segments,
    )
    if not segments:
        raise RuntimeError("No usable pre-P noise segments found.")
    print(
        f"Segments: {len(segments)}, stations: {len(station_segments)}, "
        f"raw duration: {sum(s.noise_seconds for s in segments) / 3600:.3f} h"
    )

    summary_frames: list[pd.DataFrame] = []
    all_injections: list[pd.DataFrame] = []
    for scenario in scenarios:
        print(f"\nScenario: {scenario}", flush=True)
        probs_df, injections_df = replay_scenario(
            model,
            station_segments,
            scenario=scenario,
            device=device,
            boundary_exclude_chunks=args.boundary_exclude_chunks,
            seed=args.seed,
        )
        summary = summarize_probs(probs_df, thresholds=thresholds, confirms=confirms)
        summary_frames.append(summary)
        all_injections.append(injections_df)
        probs_df.to_csv(args.output_dir / f"{scenario}_chunk_probs.csv", index=False)
        injections_df.to_csv(args.output_dir / f"{scenario}_injections.csv", index=False)
        print(summary.to_string(index=False))

    summary_df = pd.concat(summary_frames, ignore_index=True)
    injections_all = pd.concat(all_injections, ignore_index=True)
    summary_path = args.output_dir / "spike_false_alarm_stress_summary.csv"
    injection_path = args.output_dir / "spike_false_alarm_stress_injections.csv"
    meta_path = args.output_dir / "spike_false_alarm_stress_summary.json"
    summary_df.to_csv(summary_path, index=False)
    injections_all.to_csv(injection_path, index=False)
    metadata = {
        "protocol": "K-NET spike-injected pseudo-continuous pre-P noise replay",
        "checkpoint": str(args.checkpoint),
        "knet_dir": str(args.knet_dir),
        "split": args.split,
        "min_mag": args.min_mag,
        "max_dist": args.max_dist,
        "guard_chunks": args.guard_chunks,
        "min_noise_chunks": args.min_noise_chunks,
        "boundary_exclude_chunks": args.boundary_exclude_chunks,
        "thresholds": thresholds,
        "confirm_chunks": confirms,
        "scenarios": scenarios,
        "chunk_sec": CHUNK_SEC,
        "seed": args.seed,
        "device": str(device),
        "segments": len(segments),
        "stations": len(station_segments),
        "elapsed_sec": time.time() - started,
        "outputs": {
            "summary_csv": str(summary_path),
            "injections_csv": str(injection_path),
            "report_md": str(args.output_dir / "spike_false_alarm_stress_report.md"),
        },
    }
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = write_report(args.output_dir, summary_df, metadata)
    print(f"\nWrote:\n  {summary_path}\n  {injection_path}\n  {meta_path}\n  {report}")


if __name__ == "__main__":
    main()
