"""Stream a waveform file to the real-time picker service.

Example:
    python scripts/demo/realtime_service.py --device cpu --port 8765

    python scripts/demo/realtime_stream_client.py \
      --source data/samples/AOM0122512082315_3comp.mseed \
      --format mseed \
      --url http://127.0.0.1:8765/predict \
      --station-id AOM01 \
      --speed 20
"""
from __future__ import annotations

import argparse
import io
import json
import time
from pathlib import Path

import numpy as np
import requests
from scipy.signal import resample

TARGET_SR = 100.0
PACKET_SAMPLES = 50
PACKET_SEC = PACKET_SAMPLES / TARGET_SR


def load_wave(path: Path, fmt: str, component_order: str, sampling_rate_hz: float) -> tuple[np.ndarray, float]:
    fmt = fmt.lower()
    if fmt == "mseed":
        from obspy import read

        st = read(str(path))
        st.merge(method=1, fill_value="interpolate")
        traces = {}
        for tr in st:
            comp = mseed_component(str(tr.stats.channel))
            if comp:
                traces[comp] = tr
        missing = [c for c in "ZNE" if c not in traces]
        if missing:
            raise ValueError(f"miniSEED must contain Z/N/E or UD/NS/EW components; missing {missing}")
        n = min(len(traces[c].data) for c in "ZNE")
        arr = np.stack([np.asarray(traces[c].data[:n], dtype=np.float32) for c in "ZNE"], axis=0)
        return arr, float(traces["Z"].stats.sampling_rate)

    if fmt == "npy":
        arr = np.load(path, allow_pickle=False)
    elif fmt == "npz":
        loaded = np.load(path, allow_pickle=False)
        key = "data" if "data" in loaded.files else loaded.files[0]
        arr = loaded[key]
    elif fmt == "csv":
        arr = np.loadtxt(path, delimiter=",", comments="#", dtype=np.float32)
    else:
        raise ValueError("format must be mseed, csv, npy, or npz")

    return reorder_components(as_2d(arr), component_order), sampling_rate_hz


def mseed_component(channel: str) -> str | None:
    channel = channel.upper()
    aliases = {"UD": "Z", "NS": "N", "EW": "E"}
    if channel in aliases:
        return aliases[channel]
    if channel and channel[-1] in "ZNE":
        return channel[-1]
    return None


def as_2d(arr: np.ndarray) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError("waveform array must be shaped (3,n) or (n,3)")
    if arr.shape[0] == 3:
        return arr
    if arr.shape[1] == 3:
        return arr.T
    raise ValueError(f"cannot infer 3 components from shape {arr.shape}")


def reorder_components(arr: np.ndarray, component_order: str) -> np.ndarray:
    order = component_order.upper()
    if order == "ZNE":
        return arr
    if len(order) != 3 or set(order) != {"Z", "N", "E"}:
        raise ValueError("component_order must be a permutation of ZNE")
    return np.stack([arr[order.index(c)] for c in "ZNE"], axis=0)


def to_target_rate(arr: np.ndarray, sr: float) -> np.ndarray:
    if abs(sr - TARGET_SR) < 1e-6:
        return arr.astype(np.float32, copy=False)
    n = int(round(arr.shape[1] * TARGET_SR / sr))
    return resample(arr, n, axis=1).astype(np.float32)


def post_packet(url: str, station_id: str, packet: np.ndarray, scale_factor: float, timeout: float) -> dict:
    payload = {
        "station_id": station_id,
        "sampling_rate_hz": TARGET_SR,
        "component_order": "ZNE",
        "scale_factor": scale_factor,
        "data": packet.tolist(),
    }
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--format", choices=["mseed", "csv", "npy", "npz"], required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8765/predict")
    ap.add_argument("--station-id", default=None)
    ap.add_argument("--sampling-rate-hz", type=float, default=100.0)
    ap.add_argument("--component-order", default="ZNE")
    ap.add_argument("--scale-factor", type=float, default=1.0)
    ap.add_argument("--speed", type=float, default=1.0, help="1=real time, 10=ten times faster, 0=no sleep")
    ap.add_argument("--max-packets", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args()

    station_id = args.station_id or args.source.stem
    wave, sr = load_wave(args.source, args.format, args.component_order, args.sampling_rate_hz)
    wave = to_target_rate(wave, sr)
    n_packets = wave.shape[1] // PACKET_SAMPLES
    if args.max_packets > 0:
        n_packets = min(n_packets, args.max_packets)

    for i in range(n_packets):
        start = i * PACKET_SAMPLES
        packet = wave[:, start : start + PACKET_SAMPLES]
        out = post_packet(args.url, station_id, packet, args.scale_factor, args.timeout)
        for row in out.get("results", []):
            print(json.dumps(row, ensure_ascii=False), flush=True)
        if args.speed > 0 and i + 1 < n_packets:
            time.sleep(PACKET_SEC / args.speed)


if __name__ == "__main__":
    main()
