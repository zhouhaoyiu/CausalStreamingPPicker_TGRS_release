"""FDSN continuous strong-motion station-day false-alarm replay.

This experiment downloads real chronological strong-motion acceleration
channels from an FDSN service and replays them through the causal packet picker.
It is designed to close the gap between clip-based noise tests and station-day
deployment risk: the input is continuous station time, not event-window
fragments.

The default target is a small Southern California strong-motion pilot using
SCSN/CI HN? accelerometer channels. Event catalog screening is reported so that
true earthquake arrivals are not silently counted as false alarms.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from obspy import Stream, UTCDateTime, read
from obspy.clients.fdsn import Client

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "scripts" / "evaluation"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from data_streaming import normalize_packet_causal  # noqa: E402
from eval_artifact_gate_operating_points import (  # noqa: E402
    GATES,
    GateConfig,
    gate_flags,
    packet_features,
    robust_rms,
)
from eval_continuous_false_alarm_sim import (  # noqa: E402
    CHUNK_SEC,
    SAMPLES_PER_CHUNK,
    TARGET_SR,
    load_model,
    parse_csv_floats,
    parse_csv_ints,
    resample_if_needed,
)


@dataclass(frozen=True)
class StationTarget:
    network: str
    station: str
    location: str
    latitude: float | None
    longitude: float | None
    elevation_m: float | None


@dataclass(frozen=True)
class ReplayPolicy:
    reset_chunks: int
    boundary_exclude_chunks: int


def parse_csv_strings(text: str) -> list[str]:
    return [x.strip() for x in text.split(",") if x.strip()]


def safe_name(text: str) -> str:
    return (
        text.replace(":", "")
        .replace("-", "")
        .replace("/", "_")
        .replace("*", "x")
        .replace("?", "q")
        .replace(",", "_")
    )


def utc(text: str) -> UTCDateTime:
    return UTCDateTime(text)


def fdsn_client(name_or_url: str, timeout: float) -> Client:
    return Client(name_or_url, timeout=timeout)


def get_station_targets(
    client: Client,
    network: str,
    stations: list[str],
    channel: str,
    start: UTCDateTime,
    end: UTCDateTime,
) -> list[StationTarget]:
    inv = client.get_stations(
        network=network,
        station=",".join(stations),
        channel=channel,
        starttime=start,
        endtime=end,
        level="channel",
    )
    targets: list[StationTarget] = []
    seen: set[tuple[str, str, str]] = set()
    for net in inv:
        for sta in net:
            by_loc: dict[str, set[str]] = {}
            for ch in sta:
                by_loc.setdefault(ch.location_code or "", set()).add(ch.code)
            candidate_locs = sorted(
                by_loc,
                key=lambda loc: (
                    not {"HNE", "HNN", "HNZ"}.issubset(by_loc[loc]),
                    loc not in {"", "00"},
                    loc,
                ),
            )
            for loc in candidate_locs:
                if not {"HNE", "HNN", "HNZ"}.issubset(by_loc[loc]):
                    continue
                key = (net.code, sta.code, loc)
                if key in seen:
                    continue
                seen.add(key)
                targets.append(
                    StationTarget(
                        network=net.code,
                        station=sta.code,
                        location=loc,
                        latitude=float(sta.latitude) if sta.latitude is not None else None,
                        longitude=float(sta.longitude) if sta.longitude is not None else None,
                        elevation_m=float(sta.elevation) if sta.elevation is not None else None,
                    )
                )
                break
    missing = sorted(set(stations).difference({t.station for t in targets}))
    if missing:
        print(f"Warning: no complete HNE/HNN/HNZ triplet found for {missing}", flush=True)
    if not targets:
        raise RuntimeError("No complete strong-motion station targets found.")
    return targets


def download_station_stream(
    client: Client,
    target: StationTarget,
    start: UTCDateTime,
    end: UTCDateTime,
    channel: str,
    chunk_hours: float,
    cache_dir: Path,
    force_download: bool,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    loc_token = target.location if target.location else "blank"
    out = cache_dir / (
        f"{target.network}.{target.station}.{loc_token}.{safe_name(str(start))}_"
        f"{safe_name(str(end))}.{channel}.mseed"
    )
    if out.exists() and not force_download:
        return out

    st = Stream()
    step = max(float(chunk_hours) * 3600.0, 60.0)
    t0 = start
    while t0 < end:
        t1 = min(t0 + step, end)
        try:
            part = client.get_waveforms(
                network=target.network,
                station=target.station,
                location=target.location,
                channel=channel,
                starttime=t0,
                endtime=t1,
                attach_response=False,
            )
            st += part
        except Exception as exc:
            print(f"Download warning {target.network}.{target.station}.{target.location} {t0}-{t1}: {exc}")
        t0 = t1

    if len(st) == 0:
        raise RuntimeError(f"No waveforms downloaded for {target.network}.{target.station}.{target.location}")
    st.write(str(out), format="MSEED")
    return out


def choose_triplet(st: Stream, target: StationTarget) -> Stream:
    work = st.copy()
    work.merge(method=1, fill_value=0)
    if target.location:
        work = work.select(location=target.location)
    groups: dict[str, Stream] = {}
    for tr in work:
        groups.setdefault(tr.stats.location or "", Stream()).append(tr)
    loc_order = sorted(
        groups,
        key=lambda loc: (
            loc != target.location,
            loc not in {"", "00"},
            -sum(tr.stats.npts for tr in groups[loc]),
        ),
    )
    for loc in loc_order:
        g = groups[loc]
        if all(len(g.select(channel=ch)) > 0 for ch in ["HNZ", "HNN", "HNE"]):
            return g
    raise RuntimeError(f"No HNZ/HNN/HNE triplet in stream for {target.network}.{target.station}")


def stream_to_zne_array(
    mseed_path: Path,
    target: StationTarget,
    start: UTCDateTime,
    end: UTCDateTime,
) -> tuple[np.ndarray, dict]:
    st_raw = read(str(mseed_path))
    raw_gaps = st_raw.get_gaps()
    st = choose_triplet(st_raw, target)

    arrays: list[np.ndarray] = []
    channels: list[str] = []
    sampling_rates: list[float] = []
    for ch in ["HNZ", "HNN", "HNE"]:
        sub = st.select(channel=ch)
        if len(sub) == 0:
            raise RuntimeError(f"Missing {ch} for {target.network}.{target.station}")
        tr = sub[0].copy()
        tr.trim(starttime=start, endtime=end, pad=True, fill_value=0)
        data = tr.data.astype(np.float32)
        native_sr = float(tr.stats.sampling_rate)
        if not np.isclose(native_sr, TARGET_SR):
            data = resample_if_needed(data.reshape(1, -1), native_sr=native_sr)[0]
        arrays.append(data.astype(np.float32, copy=False))
        channels.append(tr.id)
        sampling_rates.append(native_sr)

    n = min(len(x) for x in arrays)
    n = (n // SAMPLES_PER_CHUNK) * SAMPLES_PER_CHUNK
    if n <= 0:
        raise RuntimeError(f"No complete packets for {target.network}.{target.station}")
    wave = np.stack([x[:n] for x in arrays], axis=0)
    meta = {
        "network": target.network,
        "station": target.station,
        "location": target.location,
        "channels": ",".join(channels),
        "start_time": str(start),
        "end_time": str(end),
        "samples": int(n),
        "duration_hours": float(n / TARGET_SR / 3600.0),
        "native_sampling_rates": ",".join(f"{x:.3f}" for x in sampling_rates),
        "raw_trace_count": int(len(st_raw)),
        "raw_gap_count": int(len(raw_gaps)),
        "raw_gap_seconds": float(sum(float(gap[6]) for gap in raw_gaps)) if raw_gaps else 0.0,
        "mseed_path": str(mseed_path),
        "latitude": target.latitude,
        "longitude": target.longitude,
        "elevation_m": target.elevation_m,
    }
    return wave, meta


def query_event_catalog(
    provider: str,
    start: UTCDateTime,
    end: UTCDateTime,
    targets: list[StationTarget],
    min_magnitude: float,
    padding_deg: float,
    timeout: float,
) -> pd.DataFrame:
    lats = [t.latitude for t in targets if t.latitude is not None]
    lons = [t.longitude for t in targets if t.longitude is not None]
    if not lats or not lons:
        return pd.DataFrame()
    minlat = min(lats) - padding_deg
    maxlat = max(lats) + padding_deg
    minlon = min(lons) - padding_deg
    maxlon = max(lons) + padding_deg
    try:
        client = fdsn_client(provider, timeout=timeout)
        cat = client.get_events(
            starttime=start,
            endtime=end,
            minmagnitude=min_magnitude,
            minlatitude=minlat,
            maxlatitude=maxlat,
            minlongitude=minlon,
            maxlongitude=maxlon,
        )
    except Exception as exc:
        text = str(exc)
        if "No data available" in text or "Status code: 204" in text or "HTTP Status code: 204" in text:
            return pd.DataFrame(
                columns=["time", "magnitude", "magnitude_type", "latitude", "longitude", "depth_km", "event_id"]
            )
        print(f"Event catalog warning: {exc}")
        return pd.DataFrame()

    rows = []
    for ev in cat:
        origin = ev.preferred_origin() or (ev.origins[0] if ev.origins else None)
        mag = ev.preferred_magnitude() or (ev.magnitudes[0] if ev.magnitudes else None)
        if origin is None or mag is None:
            continue
        rows.append(
            {
                "time": str(origin.time),
                "magnitude": float(mag.mag) if mag.mag is not None else math.nan,
                "magnitude_type": mag.magnitude_type or "",
                "latitude": float(origin.latitude) if origin.latitude is not None else math.nan,
                "longitude": float(origin.longitude) if origin.longitude is not None else math.nan,
                "depth_km": float(origin.depth / 1000.0) if origin.depth is not None else math.nan,
                "event_id": str(ev.resource_id),
            }
        )
    return pd.DataFrame(rows)


@torch.inference_mode()
def replay_continuous_waveforms(
    model,
    station_waves: list[tuple[StationTarget, np.ndarray, dict]],
    device: torch.device,
    start: UTCDateTime,
    policy: ReplayPolicy,
) -> pd.DataFrame:
    rows: list[dict] = []
    for target, wave, meta in station_waves:
        bg = robust_rms(wave)
        n_chunks = wave.shape[1] // SAMPLES_PER_CHUNK
        if policy.reset_chunks > 0:
            # The reset-window protocol is part of the deployment contract: it
            # keeps the normalized position feature inside the training range.
            # Batched inference is exactly aligned with that contract and avoids
            # a prohibitively slow per-packet Python loop for station-day data.
            for session_start in range(0, n_chunks, policy.reset_chunks):
                session_end = min(session_start + policy.reset_chunks, n_chunks)
                running_stats = None
                chunks: list[np.ndarray] = []
                feature_rows: list[dict] = []
                for k in range(session_start, session_end):
                    session_packet = k - session_start
                    a = k * SAMPLES_PER_CHUNK
                    b = a + SAMPLES_PER_CHUNK
                    raw = wave[:, a:b].astype(np.float64, copy=False)
                    feats = packet_features(raw, background_rms=bg)
                    normed, running_stats = normalize_packet_causal(raw, running_stats)
                    chunks.append(normed.astype(np.float32, copy=False))
                    abs_time = start + k * CHUNK_SEC
                    feature_rows.append(
                        {
                            "network": target.network,
                            "station_code": target.station,
                            "location": target.location,
                            "station_key": f"{target.network}.{target.station}.{target.location or '--'}",
                            "station_packet": int(k),
                            "session_packet": int(session_packet),
                            "time_sec": float(k * CHUNK_SEC),
                            "abs_time_epoch": float(abs_time.timestamp),
                            "abs_time_iso": str(abs_time),
                            "boundary_excluded": bool(session_packet < policy.boundary_exclude_chunks),
                            "duration_hours": float(meta["duration_hours"]),
                            **feats,
                        }
                    )
                batch = torch.from_numpy(np.stack(chunks, axis=0)).to(device).unsqueeze(0)
                logits, _, _ = model(batch)
                probs = torch.sigmoid(logits.reshape(-1)).detach().cpu().numpy()
                for base, prob in zip(feature_rows, probs, strict=True):
                    base["prob"] = float(prob)
                    rows.append(base)
        else:
            h = None
            prev_feat = None
            running_stats = None
            for k in range(n_chunks):
                a = k * SAMPLES_PER_CHUNK
                b = a + SAMPLES_PER_CHUNK
                raw = wave[:, a:b].astype(np.float64, copy=False)
                feats = packet_features(raw, background_rms=bg)
                normed, running_stats = normalize_packet_causal(raw, running_stats)
                pkt = torch.from_numpy(normed.astype(np.float32)).to(device).unsqueeze(0)
                logit, h, prev_feat = model.forward_streaming_packet(
                    pkt,
                    h_prev=h,
                    packet_idx=int(k),
                    prev_feat=prev_feat,
                )
                abs_time = start + k * CHUNK_SEC
                rows.append(
                    {
                        "network": target.network,
                        "station_code": target.station,
                        "location": target.location,
                        "station_key": f"{target.network}.{target.station}.{target.location or '--'}",
                        "station_packet": int(k),
                        "session_packet": int(k),
                        "time_sec": float(k * CHUNK_SEC),
                        "abs_time_epoch": float(abs_time.timestamp),
                        "abs_time_iso": str(abs_time),
                        "prob": float(torch.sigmoid(logit.reshape(-1)[0]).item()),
                        "boundary_excluded": bool(k < policy.boundary_exclude_chunks),
                        "duration_hours": float(meta["duration_hours"]),
                        **feats,
                    }
                )
        if device.type == "mps":
            torch.mps.empty_cache()
    return pd.DataFrame(rows)


def episode_rows(station_df: pd.DataFrame, prob_col: str, threshold: float, confirm: int) -> list[dict]:
    rows: list[dict] = []
    active = (
        (~station_df["boundary_excluded"].to_numpy(dtype=bool))
        & (station_df[prob_col].to_numpy(dtype=np.float64) >= threshold)
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
                        "network": str(sub["network"].iloc[0]),
                        "station_code": str(sub["station_code"].iloc[0]),
                        "location": str(sub["location"].iloc[0]),
                        "station_key": str(sub["station_key"].iloc[0]),
                        "start_station_packet": int(sub["station_packet"].iloc[0]),
                        "duration_packets": int(run_len),
                        "max_prob": float(sub[prob_col].max()),
                        "abs_time_epoch": float(sub["abs_time_epoch"].iloc[0]),
                        "abs_time_iso": str(sub["abs_time_iso"].iloc[0]),
                    }
                )
            run_start = None
            run_len = 0
    if run_start is not None and run_len >= confirm:
        sub = station_df.iloc[run_start : run_start + run_len]
        rows.append(
            {
                "network": str(sub["network"].iloc[0]),
                "station_code": str(sub["station_code"].iloc[0]),
                "location": str(sub["location"].iloc[0]),
                "station_key": str(sub["station_key"].iloc[0]),
                "start_station_packet": int(sub["station_packet"].iloc[0]),
                "duration_packets": int(run_len),
                "max_prob": float(sub[prob_col].max()),
                "abs_time_epoch": float(sub["abs_time_epoch"].iloc[0]),
                "abs_time_iso": str(sub["abs_time_iso"].iloc[0]),
            }
        )
    return rows


def summarize_gate(
    probs_df: pd.DataFrame,
    gate: GateConfig,
    threshold: float,
    confirms: list[int],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    gated = probs_df.copy()
    gated["artifact_gate"] = gate_flags(gated, gate)
    gated["prob_vetoed"] = np.where(gated["artifact_gate"].to_numpy(bool), 0.0, gated["prob"].to_numpy(float))
    valid = ~gated["boundary_excluded"].to_numpy(dtype=bool)
    valid_chunks = int(valid.sum())
    valid_hours = valid_chunks * CHUNK_SEC / 3600.0
    station_day_equiv = valid_hours / 24.0
    rows: list[dict] = []
    all_episodes: list[dict] = []
    for confirm in confirms:
        episodes: list[dict] = []
        for _, station_df in gated.groupby("station_key", sort=False):
            episodes.extend(episode_rows(station_df, "prob_vetoed", threshold, confirm))
        ep_df = pd.DataFrame(episodes)
        if not ep_df.empty:
            ep_df.insert(0, "confirm_chunks", int(confirm))
            ep_df.insert(0, "threshold", float(threshold))
            ep_df.insert(0, "gate", gate.name)
            all_episodes.extend(ep_df.to_dict(orient="records"))

        over = valid & (gated["prob_vetoed"].to_numpy(float) >= threshold)
        rows.append(
            {
                "gate": gate.name,
                "threshold": float(threshold),
                "confirm_chunks": int(confirm),
                "valid_chunks": valid_chunks,
                "valid_hours": valid_hours,
                "station_day_equivalent": station_day_equiv,
                "over_threshold_chunks": int(over.sum()),
                "over_threshold_rate_percent": float(over.sum() / valid_chunks * 100.0)
                if valid_chunks
                else 0.0,
                "artifact_gated_valid_chunks": int((valid & gated["artifact_gate"].to_numpy(bool)).sum()),
                "artifact_gated_valid_rate_percent": float(
                    (valid & gated["artifact_gate"].to_numpy(bool)).sum() / valid_chunks * 100.0
                )
                if valid_chunks
                else 0.0,
                "alarm_episodes": int(len(ep_df)),
                "false_alerts_per_hour": float(len(ep_df) / valid_hours) if valid_hours else 0.0,
                "false_alerts_per_station_day": float(len(ep_df) / station_day_equiv)
                if station_day_equiv
                else 0.0,
                "stations": int(gated["station_key"].nunique()),
                "stations_with_alarm": int(ep_df["station_key"].nunique()) if not ep_df.empty else 0,
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(all_episodes)


def coincidence_clusters(episodes: pd.DataFrame, station_n: int, window_sec: float) -> int:
    if episodes.empty or "abs_time_epoch" not in episodes.columns:
        return 0
    ep = episodes.dropna(subset=["abs_time_epoch"]).sort_values("abs_time_epoch").reset_index(drop=True)
    if ep.empty:
        return 0
    times = ep["abs_time_epoch"].to_numpy(float)
    stations = ep["station_key"].astype(str).to_numpy()
    clusters = 0
    i = 0
    while i < len(ep):
        t0 = times[i]
        j = int(np.searchsorted(times, t0 + window_sec, side="right"))
        if len(set(stations[i:j])) >= station_n:
            clusters += 1
            i = j
        else:
            i += 1
    return int(clusters)


def build_network_summary(
    episodes: pd.DataFrame,
    station_ns: list[int],
    windows: list[float],
    valid_hours: float,
) -> pd.DataFrame:
    rows: list[dict] = []
    if episodes.empty:
        return pd.DataFrame(
            columns=[
                "gate",
                "threshold",
                "confirm_chunks",
                "station_n",
                "window_sec",
                "clusters",
                "clusters_per_station_day_equiv",
            ]
        )
    station_day_equiv = valid_hours / 24.0
    for (gate, threshold, confirm), sub in episodes.groupby(["gate", "threshold", "confirm_chunks"], sort=False):
        for station_n in station_ns:
            for window in windows:
                clusters = coincidence_clusters(sub, station_n=station_n, window_sec=window)
                rows.append(
                    {
                        "gate": gate,
                        "threshold": float(threshold),
                        "confirm_chunks": int(confirm),
                        "station_n": int(station_n),
                        "window_sec": float(window),
                        "clusters": int(clusters),
                        "clusters_per_station_day_equiv": float(clusters / station_day_equiv)
                        if station_day_equiv
                        else 0.0,
                    }
                )
    return pd.DataFrame(rows)


def write_report(
    path: Path,
    station_manifest: pd.DataFrame,
    events: pd.DataFrame,
    rates: pd.DataFrame,
    network: pd.DataFrame,
    args: argparse.Namespace,
    policy: ReplayPolicy,
) -> None:
    focus = rates.loc[(rates["threshold"].eq(0.55)) & (rates["confirm_chunks"].eq(2))].copy()
    lines = [
        "# FDSN Continuous Strong-Motion Station-Day False-Alarm Replay",
        "",
        f"Date: {time.strftime('%Y-%m-%d')}",
        "",
        "## Protocol",
        "",
        f"- Waveform provider: `{args.provider}`",
        f"- Event provider: `{args.event_provider}`",
        f"- Network/stations: `{args.network}` / `{args.stations}`",
        f"- Channel selector: `{args.channel}`; complete triplet required: HNZ/HNN/HNE",
        f"- Start: `{args.start}`",
        f"- Duration: {args.duration_hours:.2f} h per station",
        f"- Stations downloaded: {len(station_manifest)}",
        f"- Valid station hours: {float(rates['valid_hours'].iloc[0]) if len(rates) else 0.0:.2f}",
        f"- Reset policy: {'none' if policy.reset_chunks <= 0 else str(policy.reset_chunks) + ' packets'}",
        f"- Boundary exclusion after reset: {policy.boundary_exclude_chunks} packets",
        f"- Event-screening minimum magnitude: M {args.event_min_magnitude:.1f}",
        "",
        "This is a true chronological continuous waveform replay for the selected",
        "strong-motion accelerometer channels. It is still a pilot, not a complete",
        "operational network-day certification, because it covers a small station",
        "set and a selected quiet interval.",
        "",
        "## Event Catalog Screen",
        "",
        f"- Catalog events in the station bounding box: {len(events)}",
    ]
    if len(events):
        lines.extend(["", "| Time | M | Lat | Lon | Depth km |", "|---|---:|---:|---:|---:|"])
        for row in events.sort_values("time").to_dict(orient="records"):
            lines.append(
                f"| {row['time']} | {row['magnitude']:.2f} | {row['latitude']:.3f} | "
                f"{row['longitude']:.3f} | {row['depth_km']:.1f} |"
            )
    lines.extend(["", "## Working Operating Point", ""])
    if not focus.empty:
        lines.extend(
            [
                "| Gate | Valid h | Station-time days | Over-thr. | Episodes | False triggers/h | False triggers per station day | Stations with trigger |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in focus.sort_values("gate").to_dict(orient="records"):
            lines.append(
                f"| {row['gate']} | {row['valid_hours']:.2f} | "
                f"{row['station_day_equivalent']:.2f} | "
                f"{int(row['over_threshold_chunks'])} | {int(row['alarm_episodes'])} | "
                f"{row['false_alerts_per_hour']:.3f} | {row['false_alerts_per_station_day']:.2f} | "
                f"{int(row['stations_with_alarm'])}/{int(row['stations'])} |"
            )
    else:
        lines.append("No row found for threshold 0.55 and two-packet confirmation.")

    lines.extend(["", "## Multi-Station Time Coincidence", ""])
    net_focus = network.loc[
        (network["threshold"].eq(0.55))
        & (network["confirm_chunks"].eq(2))
        & (network["station_n"].isin([2, 3]))
        & (network["window_sec"].isin([3.0, 5.0]))
    ]
    if not net_focus.empty:
        lines.extend(
            [
                "| Gate | N stations | Window | Coincidences | Coincidences per station day |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for row in net_focus.sort_values(["gate", "station_n", "window_sec"]).to_dict(orient="records"):
            lines.append(
                f"| {row['gate']} | {int(row['station_n'])} | {row['window_sec']:.1f} s | "
                f"{int(row['clusters'])} | {row['clusters_per_station_day_equiv']:.2f} |"
            )
    else:
        lines.append("No multi-station coincidence rows were available.")

    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "- This evaluates the station-side candidate generator on real continuous",
            "  strong-motion accelerometer streams.",
            "- A nonzero single-station episode rate is not a final alert rate; the",
            "  alarm layer must add station QC, multi-station association, and source",
            "  consistency.",
            "- A zero or low cluster count in this small pilot does not certify a",
            "  production network. It only supports the engineering direction for",
            "  downstream association.",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", type=Path, default=ROOT / "models/checkpoints/multidomain_best.pt")
    ap.add_argument("--provider", default="SCEDC")
    ap.add_argument("--event-provider", default="USGS")
    ap.add_argument("--network", default="CI")
    ap.add_argument("--stations", default="PASC,SVD,USC,WTT2")
    ap.add_argument("--channel", default="HN?")
    ap.add_argument("--start", default="2024-02-07T00:00:00")
    ap.add_argument("--duration-hours", type=float, default=6.0)
    ap.add_argument("--download-chunk-hours", type=float, default=1.0)
    ap.add_argument("--event-min-magnitude", type=float, default=3.0)
    ap.add_argument("--event-bbox-padding-deg", type=float, default=2.0)
    ap.add_argument("--reset-chunks", type=int, default=320)
    ap.add_argument("--boundary-exclude-chunks", type=int, default=2)
    ap.add_argument("--thresholds", default="0.55")
    ap.add_argument("--confirm-list", default="1,2,3")
    ap.add_argument("--gates", default="none,peak12_width2,peak12_width8")
    ap.add_argument("--network-station-n", default="2,3,4")
    ap.add_argument("--network-windows-sec", default="3,5")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--force-download", action="store_true")
    ap.add_argument("--device", default="cpu")
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=ROOT / "data/fdsn_continuous_strong_motion",
    )
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs/evaluation/fdsn_strong_motion_stationday_false_alarm",
    )
    args = ap.parse_args()

    if args.device == "mps" and not torch.backends.mps.is_available():
        args.device = "cpu"
    device = torch.device(args.device)
    start = utc(args.start)
    end = start + float(args.duration_hours) * 3600.0
    stations = parse_csv_strings(args.stations)
    thresholds = parse_csv_floats(args.thresholds)
    confirms = parse_csv_ints(args.confirm_list)
    gate_names = parse_csv_strings(args.gates)
    gates = [gate for gate in GATES if gate.name in gate_names]
    missing_gates = sorted(set(gate_names).difference({gate.name for gate in gates}))
    if missing_gates:
        raise ValueError(f"Unknown gates: {missing_gates}. Available: {[gate.name for gate in GATES]}")
    policy = ReplayPolicy(reset_chunks=int(args.reset_chunks), boundary_exclude_chunks=int(args.boundary_exclude_chunks))

    started = time.time()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cache_run_dir = args.cache_dir / f"{args.network}_{safe_name(str(start))}_{safe_name(str(end))}"
    cache_run_dir.mkdir(parents=True, exist_ok=True)

    client = fdsn_client(args.provider, timeout=args.timeout)
    targets = get_station_targets(client, args.network, stations, args.channel, start, end)
    events = query_event_catalog(
        args.event_provider,
        start,
        end,
        targets,
        min_magnitude=float(args.event_min_magnitude),
        padding_deg=float(args.event_bbox_padding_deg),
        timeout=float(args.timeout),
    )
    events_path = args.output_dir / "event_catalog_screen.csv"
    events.to_csv(events_path, index=False)

    station_waves: list[tuple[StationTarget, np.ndarray, dict]] = []
    manifest_rows: list[dict] = []
    for target in targets:
        mseed = download_station_stream(
            client,
            target,
            start,
            end,
            channel=args.channel,
            chunk_hours=float(args.download_chunk_hours),
            cache_dir=cache_run_dir,
            force_download=bool(args.force_download),
        )
        wave, meta = stream_to_zne_array(mseed, target, start, end)
        station_waves.append((target, wave, meta))
        manifest_rows.append(meta)
        print(
            f"Prepared {target.network}.{target.station}.{target.location or '--'} "
            f"{meta['duration_hours']:.2f} h, gaps={meta['raw_gap_count']}",
            flush=True,
        )

    station_manifest = pd.DataFrame(manifest_rows)
    station_manifest_path = args.output_dir / "station_stream_manifest.csv"
    station_manifest.to_csv(station_manifest_path, index=False)

    model = load_model(args.checkpoint, device)
    probs = replay_continuous_waveforms(model, station_waves, device, start, policy)
    if probs.empty:
        raise RuntimeError("Replay produced no packet probabilities.")

    all_rates: list[pd.DataFrame] = []
    all_episodes: list[pd.DataFrame] = []
    for threshold in thresholds:
        for gate in gates:
            rates, episodes = summarize_gate(probs, gate=gate, threshold=threshold, confirms=confirms)
            all_rates.append(rates)
            if not episodes.empty:
                all_episodes.append(episodes)
    rates_df = pd.concat(all_rates, ignore_index=True)
    episodes_df = pd.concat(all_episodes, ignore_index=True) if all_episodes else pd.DataFrame()
    valid_hours = float((~probs["boundary_excluded"].to_numpy(bool)).sum() * CHUNK_SEC / 3600.0)
    network_df = build_network_summary(
        episodes_df,
        station_ns=parse_csv_ints(args.network_station_n),
        windows=parse_csv_floats(args.network_windows_sec),
        valid_hours=valid_hours,
    )

    probs_path = args.output_dir / "continuous_packet_probabilities.csv"
    rates_path = args.output_dir / "stationday_false_alarm_rates.csv"
    episodes_path = args.output_dir / "stationday_false_alarm_episodes.csv"
    network_path = args.output_dir / "network_coincidence_summary.csv"
    summary_path = args.output_dir / "fdsn_strong_motion_stationday_false_alarm_summary.json"
    report_path = args.output_dir / "fdsn_strong_motion_stationday_false_alarm_report.md"

    probs.to_csv(probs_path, index=False)
    rates_df.to_csv(rates_path, index=False)
    episodes_df.to_csv(episodes_path, index=False)
    network_df.to_csv(network_path, index=False)
    payload = {
        "protocol": "FDSN continuous strong-motion station-day false-alarm replay",
        "checkpoint": str(args.checkpoint),
        "provider": args.provider,
        "event_provider": args.event_provider,
        "network": args.network,
        "stations": stations,
        "channel": args.channel,
        "start": str(start),
        "end": str(end),
        "duration_hours_per_station": float(args.duration_hours),
        "policy": asdict(policy),
        "device": str(device),
        "thresholds": thresholds,
        "confirm_chunks": confirms,
        "gates": [gate.name for gate in gates],
        "station_count": int(station_manifest["station"].nunique()) if "station" in station_manifest.columns else len(targets),
        "valid_hours": valid_hours,
        "station_day_equivalent": valid_hours / 24.0,
        "event_catalog_count": int(len(events)),
        "elapsed_sec": time.time() - started,
        "outputs": {
            "station_stream_manifest": str(station_manifest_path),
            "event_catalog_screen": str(events_path),
            "continuous_packet_probabilities": str(probs_path),
            "stationday_false_alarm_rates": str(rates_path),
            "stationday_false_alarm_episodes": str(episodes_path),
            "network_coincidence_summary": str(network_path),
            "report": str(report_path),
        },
    }
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(report_path, station_manifest, events, rates_df, network_df, args, policy)

    print("\nRates:")
    print(rates_df.to_string(index=False))
    print("\nNetwork coincidence:")
    print(network_df.to_string(index=False))
    print(f"\nWrote report: {report_path}")


if __name__ == "__main__":
    main()
