"""Small HTTP service for real-time packet picking.

The service keeps per-station streaming state and accepts common payloads:
JSON arrays, CSV rows, NumPy .npy/.npz bytes, and miniSEED.

Example:
    python scripts/demo/realtime_service.py --device cpu --port 8765

    curl -X POST 'http://127.0.0.1:8765/predict' \
      -H 'content-type: application/json' \
      -d '{"station_id":"demo","sampling_rate_hz":100,"component_order":"ZNE","data":[[0,0],[0,0],[0,0]]}'
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import ssl
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import torch
from scipy.signal import resample

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import SAMPLES_PER_CHUNK, TARGET_SR
from data_streaming import normalize_packet_causal
from model_v3 import CausalStreamingPPickerV3


def load_model(checkpoint: Path, device: torch.device) -> CausalStreamingPPickerV3:
    ckpt = torch.load(checkpoint, map_location=device, weights_only=False)
    cfg = ckpt.get("config", {})
    model = CausalStreamingPPickerV3(
        encoder_hid=int(cfg.get("encoder_hid", 64)),
        gru_hid=int(cfg.get("gru_hid", 128)),
        gru_layers=int(cfg.get("gru_layers", 2)),
        dropout=float(cfg.get("dropout", 0.25)),
        max_chunks=int(cfg.get("max_chunks", 320)),
        feature_mode=str(cfg.get("feature_mode", "zne")),
    ).to(device)
    model.load_state_dict(ckpt["model"], strict=True)
    model.eval()
    return model


@dataclass
class StationState:
    running_stats: dict | None = None
    h: torch.Tensor | None = None
    prev_feat: torch.Tensor | None = None
    packet_idx: int = 0
    session_packet_idx: int = 0
    trigger_streak: int = 0
    buffer: np.ndarray = field(default_factory=lambda: np.zeros((3, 0), dtype=np.float32))


class RealtimePicker:
    def __init__(
        self,
        checkpoint: Path,
        device: str,
        threshold: float,
        reset_chunks: int,
        confirm_chunks: int,
        boundary_exclude_chunks: int,
    ):
        if reset_chunks < 0 or confirm_chunks < 1 or boundary_exclude_chunks < 0:
            raise ValueError("reset_chunks and boundary_exclude_chunks must be nonnegative; confirm_chunks must be positive")
        if reset_chunks and boundary_exclude_chunks >= reset_chunks:
            raise ValueError("boundary_exclude_chunks must be smaller than reset_chunks")
        if device == "mps" and not torch.backends.mps.is_available():
            device = "cpu"
        self.device = torch.device(device)
        self.model = load_model(checkpoint, self.device)
        self.threshold = threshold
        self.reset_chunks = reset_chunks
        self.confirm_chunks = confirm_chunks
        self.boundary_exclude_chunks = boundary_exclude_chunks
        self.states: dict[str, StationState] = {}
        self.lock = threading.Lock()

    def reset(self, station_id: str | None = None) -> None:
        with self.lock:
            if station_id:
                self.states.pop(station_id, None)
            else:
                self.states.clear()

    def predict_samples(self, station_id: str, samples: np.ndarray) -> dict:
        samples = as_zne(samples)
        with self.lock:
            state = self.states.setdefault(station_id, StationState())
            state.buffer = np.concatenate([state.buffer, samples.astype(np.float32, copy=False)], axis=1)
            results = []
            while state.buffer.shape[1] >= SAMPLES_PER_CHUNK:
                raw = state.buffer[:, :SAMPLES_PER_CHUNK]
                state.buffer = state.buffer[:, SAMPLES_PER_CHUNK:]
                if self.reset_chunks > 0 and state.session_packet_idx >= self.reset_chunks:
                    state.running_stats = None
                    state.h = None
                    state.prev_feat = None
                    state.session_packet_idx = 0
                    state.trigger_streak = 0
                prob = self._predict_packet(raw, state)
                candidate = prob >= self.threshold
                boundary_excluded = state.session_packet_idx < self.boundary_exclude_chunks
                if boundary_excluded:
                    state.trigger_streak = 0
                else:
                    state.trigger_streak = state.trigger_streak + 1 if candidate else 0
                confirmed = state.trigger_streak >= self.confirm_chunks
                results.append(
                    {
                        "packet_idx": state.packet_idx,
                        "session_packet_idx": state.session_packet_idx,
                        "time_sec": state.packet_idx * (SAMPLES_PER_CHUNK / TARGET_SR),
                        "p_probability": prob,
                        "candidate": candidate,
                        "confirmed": confirmed,
                        "trigger": state.trigger_streak == self.confirm_chunks,
                        "confirmation_streak": state.trigger_streak,
                        "boundary_excluded": boundary_excluded,
                    }
                )
                state.packet_idx += 1
                state.session_packet_idx += 1
            return {
                "station_id": station_id,
                "threshold": self.threshold,
                "confirm_chunks": self.confirm_chunks,
                "reset_chunks": self.reset_chunks,
                "boundary_exclude_chunks": self.boundary_exclude_chunks,
                "packets_processed": len(results),
                "buffered_samples": int(state.buffer.shape[1]),
                "results": results,
            }

    @torch.inference_mode()
    def _predict_packet(self, raw: np.ndarray, state: StationState) -> float:
        normed, state.running_stats = normalize_packet_causal(
            raw.astype(np.float64, copy=False),
            state.running_stats,
        )
        packet = torch.from_numpy(normed.astype(np.float32, copy=False)).unsqueeze(0).to(self.device)
        logit, state.h, state.prev_feat = self.model.forward_streaming_packet(
            packet,
            h_prev=state.h,
            packet_idx=state.session_packet_idx,
            prev_feat=state.prev_feat,
        )
        return float(torch.sigmoid(logit.reshape(-1)[0]).item())


def as_zne(arr: np.ndarray) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError("data must be a 2-D array shaped (3, n_samples) or (n_samples, 3)")
    if arr.shape[0] == 3:
        return arr
    if arr.shape[1] == 3:
        return arr.T
    raise ValueError(f"cannot infer 3 components from shape {arr.shape}")


def reorder_components(arr: np.ndarray, component_order: str) -> np.ndarray:
    arr = as_zne(arr)
    order = component_order.upper()
    if order == "ZNE":
        return arr
    if len(order) != 3 or set(order) != {"Z", "N", "E"}:
        raise ValueError("component_order must be a permutation of ZNE")
    return np.stack([arr[order.index(c)] for c in "ZNE"], axis=0)


def to_target_rate(arr: np.ndarray, sampling_rate_hz: float) -> np.ndarray:
    if sampling_rate_hz <= 0:
        raise ValueError("sampling_rate_hz must be positive")
    if abs(sampling_rate_hz - TARGET_SR) < 1e-6:
        return arr.astype(np.float32, copy=False)
    target_n = int(round(arr.shape[1] * TARGET_SR / sampling_rate_hz))
    if target_n <= 0:
        return np.zeros((3, 0), dtype=np.float32)
    return resample(arr, target_n, axis=1).astype(np.float32)


def parse_json(body: bytes, query: dict[str, list[str]]) -> tuple[str, np.ndarray, float, str, float]:
    payload = json.loads(body.decode("utf-8"))
    station = str(payload.get("station_id") or first(query, "station_id", "default"))
    sr = float(payload.get("sampling_rate_hz", first(query, "sampling_rate_hz", TARGET_SR)))
    order = str(payload.get("component_order", first(query, "component_order", "ZNE")))
    scale = float(payload.get("scale_factor", first(query, "scale_factor", 1.0)))
    return station, np.asarray(payload["data"], dtype=np.float32), sr, order, scale


def parse_csv_body(body: bytes, query: dict[str, list[str]]) -> tuple[str, np.ndarray, float, str, float]:
    rows = list(csv.reader(io.StringIO(body.decode("utf-8"))))
    clean = []
    for row in rows:
        if not row:
            continue
        try:
            clean.append([float(x) for x in row if x.strip()])
        except ValueError:
            continue
    arr = np.asarray(clean, dtype=np.float32)
    return (
        str(first(query, "station_id", "default")),
        arr,
        float(first(query, "sampling_rate_hz", TARGET_SR)),
        str(first(query, "component_order", "ZNE")),
        float(first(query, "scale_factor", 1.0)),
    )


def parse_numpy_body(body: bytes, query: dict[str, list[str]]) -> tuple[str, np.ndarray, float, str, float]:
    loaded = np.load(io.BytesIO(body), allow_pickle=False)
    if isinstance(loaded, np.lib.npyio.NpzFile):
        key = "data" if "data" in loaded.files else loaded.files[0]
        arr = loaded[key]
    else:
        arr = loaded
    return (
        str(first(query, "station_id", "default")),
        np.asarray(arr, dtype=np.float32),
        float(first(query, "sampling_rate_hz", TARGET_SR)),
        str(first(query, "component_order", "ZNE")),
        float(first(query, "scale_factor", 1.0)),
    )


def parse_mseed_body(body: bytes, query: dict[str, list[str]]) -> tuple[str, np.ndarray, float, str, float]:
    from obspy import read

    stream = read(io.BytesIO(body))
    stream.merge(method=1, fill_value="interpolate")
    station = str(first(query, "station_id", stream[0].stats.station or "default"))
    traces = {}
    for tr in stream:
        comp = mseed_component(str(tr.stats.channel))
        if comp:
            traces[comp] = tr
    missing = [c for c in "ZNE" if c not in traces]
    if missing:
        raise ValueError(f"miniSEED must contain Z/N/E components; missing {missing}")
    sr = float(traces["Z"].stats.sampling_rate)
    n = min(len(traces[c].data) for c in "ZNE")
    arr = np.stack([np.asarray(traces[c].data[:n], dtype=np.float32) for c in "ZNE"], axis=0)
    return station, arr, sr, "ZNE", float(first(query, "scale_factor", 1.0))


def mseed_component(channel: str) -> str | None:
    channel = channel.upper()
    aliases = {"UD": "Z", "NS": "N", "EW": "E"}
    if channel in aliases:
        return aliases[channel]
    if channel and channel[-1] in "ZNE":
        return channel[-1]
    return None


def parse_request(body: bytes, content_type: str, query: dict[str, list[str]]) -> tuple[str, np.ndarray]:
    fmt = str(first(query, "format", "")).lower()
    ctype = content_type.split(";", 1)[0].lower()
    if fmt == "csv" or ctype in {"text/csv", "application/csv"}:
        station, arr, sr, order, scale = parse_csv_body(body, query)
    elif fmt == "mseed" or "mseed" in ctype:
        station, arr, sr, order, scale = parse_mseed_body(body, query)
    elif fmt in {"npy", "npz"} or ctype in {"application/x-npy", "application/x-npz", "application/octet-stream"}:
        station, arr, sr, order, scale = parse_numpy_body(body, query)
    else:
        station, arr, sr, order, scale = parse_json(body, query)
    arr = reorder_components(arr * scale, order)
    return station, to_target_rate(arr, sr)


def first(query: dict[str, list[str]], key: str, default):
    values = query.get(key)
    return values[0] if values else default


def make_handler(picker: RealtimePicker):
    class Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.send_cors_headers()
            self.end_headers()

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self.write_json(
                    {
                        "ok": True,
                        "device": str(picker.device),
                        "target_sr": TARGET_SR,
                        "threshold": picker.threshold,
                        "confirm_chunks": picker.confirm_chunks,
                        "reset_chunks": picker.reset_chunks,
                        "boundary_exclude_chunks": picker.boundary_exclude_chunks,
                    }
                )
            elif parsed.path == "/device-accel-demo":
                self.write_file(ROOT / "docs/device_accel_stream_demo.html", "text/html; charset=utf-8")
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            try:
                if parsed.path == "/reset":
                    picker.reset(str(first(query, "station_id", "")) or None)
                    self.write_json({"ok": True})
                    return
                if parsed.path != "/predict":
                    self.send_error(404)
                    return
                n = int(self.headers.get("content-length", "0"))
                body = self.rfile.read(n)
                station, samples = parse_request(body, self.headers.get("content-type", ""), query)
                self.write_json(picker.predict_samples(station, samples))
            except Exception as exc:
                self.write_json({"ok": False, "error": str(exc)}, status=400)

        def write_json(self, payload: dict, status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def write_file(self, path: Path, content_type: str) -> None:
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("content-type", content_type)
            self.send_cors_headers()
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_cors_headers(self) -> None:
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
            self.send_header("access-control-allow-headers", "content-type")

        def log_message(self, fmt: str, *args) -> None:
            if not getattr(self.server, "quiet", False):
                super().log_message(fmt, *args)

    return Handler


def self_test(checkpoint: Path) -> None:
    picker = RealtimePicker(
        checkpoint,
        "cpu",
        threshold=-1.0,
        reset_chunks=4,
        confirm_chunks=2,
        boundary_exclude_chunks=1,
    )
    arr = np.zeros((3, SAMPLES_PER_CHUNK), dtype=np.float32)
    out = picker.predict_samples("json", np.tile(arr, (1, 5)))
    rows = out["results"]
    assert [row["session_packet_idx"] for row in rows] == [0, 1, 2, 3, 0]
    assert [row["boundary_excluded"] for row in rows] == [True, False, False, False, True]
    assert [row["trigger"] for row in rows] == [False, False, True, False, False]

    csv_body = "\n".join(["0,0,0"] * SAMPLES_PER_CHUNK).encode("utf-8")
    station, samples = parse_request(
        csv_body,
        "text/csv",
        {"station_id": ["csv"], "sampling_rate_hz": ["100"], "component_order": ["ZNE"]},
    )
    assert station == "csv" and samples.shape == (3, SAMPLES_PER_CHUNK)

    buf = io.BytesIO()
    np.save(buf, arr)
    station, samples = parse_request(
        buf.getvalue(),
        "application/x-npy",
        {"station_id": ["npy"], "sampling_rate_hz": ["100"], "component_order": ["ZNE"]},
    )
    assert station == "npy" and samples.shape == (3, SAMPLES_PER_CHUNK)
    print("self-test passed")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", type=Path, default=ROOT / "models/checkpoints/multidomain_best.pt")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--threshold", type=float, default=0.55)
    ap.add_argument("--reset-chunks", type=int, default=320)
    ap.add_argument("--confirm-chunks", type=int, default=2)
    ap.add_argument("--boundary-exclude-chunks", type=int, default=2)
    ap.add_argument("--ssl-cert", type=Path, default=None)
    ap.add_argument("--ssl-key", type=Path, default=None)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        self_test(args.checkpoint)
        return

    picker = RealtimePicker(
        args.checkpoint,
        args.device,
        args.threshold,
        args.reset_chunks,
        args.confirm_chunks,
        args.boundary_exclude_chunks,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(picker))
    scheme = "http"
    if args.ssl_cert or args.ssl_key:
        if not args.ssl_cert or not args.ssl_key:
            raise SystemExit("--ssl-cert and --ssl-key must be provided together")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(args.ssl_cert, args.ssl_key)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    server.quiet = args.quiet
    print(
        f"serving on {scheme}://{args.host}:{args.port} threshold={args.threshold} "
        f"confirm={args.confirm_chunks} reset={args.reset_chunks} device={picker.device}"
    )
    print("endpoints: GET /health, POST /predict, POST /reset")
    server.serve_forever()


if __name__ == "__main__":
    main()
