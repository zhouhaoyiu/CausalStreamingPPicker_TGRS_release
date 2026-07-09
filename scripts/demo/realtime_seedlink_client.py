"""Forward SeedLink real-time station streams to the picker service.

Start the picker service first:
    python scripts/demo/realtime_service.py --device cpu --port 8765

Then connect to a SeedLink server:
    python scripts/demo/realtime_seedlink_client.py \
      --server seedlink.example.org:18000 \
      --stream NET.STA.HN? \
      --url http://127.0.0.1:8765/predict
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import requests
from obspy import Trace
from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient
from scipy.signal import resample

TARGET_SR = 100.0
PACKET_SAMPLES = 50


@dataclass
class StationBuffer:
    components: dict[str, np.ndarray] = field(
        default_factory=lambda: {c: np.zeros(0, dtype=np.float32) for c in "ZNE"}
    )
    last_endtime: dict[str, object] = field(default_factory=dict)

    def reset(self) -> None:
        for comp in "ZNE":
            self.components[comp] = np.zeros(0, dtype=np.float32)
        self.last_endtime.clear()


class PickerSeedLinkClient(EasySeedLinkClient):
    def __init__(self, server_url: str, picker_url: str, scale_factor: float, timeout: float, max_packets: int):
        super().__init__(server_url, autoconnect=True)
        self.picker_url = picker_url
        self.scale_factor = scale_factor
        self.timeout = timeout
        self.max_packets = max_packets
        self.buffers: dict[str, StationBuffer] = defaultdict(StationBuffer)
        self.sent_packets = 0

    def on_data(self, trace: Trace) -> None:
        comp = component_from_channel(str(trace.stats.channel))
        if comp is None:
            return
        station_id = f"{trace.stats.network}.{trace.stats.station}"
        buf = self.buffers[station_id]
        if has_gap(buf, comp, trace):
            buf.reset()
            post_reset(self.picker_url, station_id, self.timeout)

        data = np.asarray(trace.data, dtype=np.float32)
        sr = float(trace.stats.sampling_rate)
        if abs(sr - TARGET_SR) > 1e-6:
            n = int(round(data.size * TARGET_SR / sr))
            data = resample(data, n).astype(np.float32)

        buf.components[comp] = np.concatenate([buf.components[comp], data])
        buf.last_endtime[comp] = trace.stats.endtime
        self.flush(station_id, buf)

    def flush(self, station_id: str, buf: StationBuffer) -> None:
        while min(buf.components[c].size for c in "ZNE") >= PACKET_SAMPLES:
            packet = np.stack([buf.components[c][:PACKET_SAMPLES] for c in "ZNE"], axis=0)
            for comp in "ZNE":
                buf.components[comp] = buf.components[comp][PACKET_SAMPLES:]
            out = post_packet(self.picker_url, station_id, packet, self.scale_factor, self.timeout)
            for row in out.get("results", []):
                print(json.dumps({"station_id": station_id, **row}, ensure_ascii=False), flush=True)
            self.sent_packets += 1
            if self.max_packets and self.sent_packets >= self.max_packets:
                self.close()
                raise SystemExit(0)


def component_from_channel(channel: str) -> str | None:
    channel = channel.upper()
    aliases = {"UD": "Z", "NS": "N", "EW": "E"}
    if channel in aliases:
        return aliases[channel]
    if channel and channel[-1] in "ZNE":
        return channel[-1]
    return None


def has_gap(buf: StationBuffer, comp: str, trace: Trace) -> bool:
    prev = buf.last_endtime.get(comp)
    if prev is None:
        return False
    dt = 1.0 / float(trace.stats.sampling_rate)
    gap = abs(float(trace.stats.starttime - prev) - dt)
    return gap > max(0.05, 2 * dt)


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


def post_reset(url: str, station_id: str, timeout: float) -> None:
    reset_url = url.rsplit("/", 1)[0] + "/reset"
    requests.post(reset_url, params={"station_id": station_id}, timeout=timeout).raise_for_status()


def parse_stream(value: str) -> tuple[str, str, str]:
    parts = value.split(".", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("stream must be NET.STA.SELECTOR, e.g. CI.PASC.HN?")
    return parts[0], parts[1], parts[2]


def self_test() -> None:
    assert component_from_channel("HNZ") == "Z"
    assert component_from_channel("HNN") == "N"
    assert component_from_channel("HNE") == "E"
    assert component_from_channel("UD") == "Z"
    assert parse_stream("CI.PASC.HN?") == ("CI", "PASC", "HN?")
    print("self-test passed")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", help="SeedLink server, e.g. host:18000")
    ap.add_argument("--stream", action="append", type=parse_stream, default=[], help="NET.STA.SELECTOR, repeatable")
    ap.add_argument("--url", default="http://127.0.0.1:8765/predict")
    ap.add_argument("--scale-factor", type=float, default=1.0)
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--max-packets", type=int, default=0)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return
    if not args.server or not args.stream:
        ap.error("--server and at least one --stream are required")

    client = PickerSeedLinkClient(args.server, args.url, args.scale_factor, args.timeout, args.max_packets)
    for net, sta, selector in args.stream:
        client.select_stream(net, sta, selector)
        print(f"selected {net}.{sta}.{selector}")
    print(f"connected to SeedLink {args.server}; forwarding to {args.url}")
    try:
        client.run()
    finally:
        time.sleep(0.1)
        client.close()


if __name__ == "__main__":
    main()
