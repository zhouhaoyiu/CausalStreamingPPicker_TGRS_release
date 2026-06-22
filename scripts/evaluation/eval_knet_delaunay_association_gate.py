"""Evaluate a Delaunay-neighbor consistency gate on K-NET event triggers.

This is a post-processing check on existing single-station trigger tables. It
does not rerun the picker. The goal is to test whether event-window station
clusters also satisfy a lightweight network-geometry condition inspired by
Delaunay-neighbor interference rejection used in early EEW system studies.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import Delaunay


ROOT = Path(__file__).resolve().parents[2]
CHUNK_SEC = 0.5


@dataclass
class EventDelaunayResult:
    threshold: float
    confirm_chunks: int
    min_stations: int
    window_sec: float
    event_name: str
    source_magnitude: float | None
    source_depth_km: float | None
    n_stations: int
    n_coord_stations: int
    n_station_detections: int
    associated: bool
    assoc_time_sec: float | None
    assoc_delay_from_first_p_sec: float | None
    station_codes_in_window: str
    delaunay_supported: bool
    delaunay_assoc_time_sec: float | None
    delaunay_delay_from_first_p_sec: float | None
    extra_delay_after_plain_assoc_sec: float | None
    delaunay_station_codes_in_window: str


def parse_float_list(text: str) -> list[float]:
    return [float(x.strip()) for x in text.split(",") if x.strip()]


def parse_int_list(text: str) -> list[int]:
    return [int(x.strip()) for x in text.split(",") if x.strip()]


def scalar_or_none(value) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.astype(str).str.lower().isin(["true", "1", "yes", "y"])


def ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def build_delaunay_adjacency(meta: pd.DataFrame) -> dict[str, set[str]]:
    required = ["station_code", "station_latitude_deg", "station_longitude_deg"]
    missing = [c for c in required if c not in meta.columns]
    if missing:
        raise ValueError(f"metadata is missing required station columns: {missing}")

    stations = (
        meta[required]
        .dropna()
        .assign(station_code=lambda d: d["station_code"].astype(str))
        .groupby("station_code", as_index=False)
        .agg(
            station_latitude_deg=("station_latitude_deg", "mean"),
            station_longitude_deg=("station_longitude_deg", "mean"),
        )
        .sort_values("station_code")
        .reset_index(drop=True)
    )
    if len(stations) < 3:
        raise ValueError("at least three stations with coordinates are required")

    lat0 = math.radians(float(stations["station_latitude_deg"].mean()))
    xy = np.column_stack(
        [
            stations["station_longitude_deg"].to_numpy(dtype=float) * math.cos(lat0),
            stations["station_latitude_deg"].to_numpy(dtype=float),
        ]
    )
    triangulation = Delaunay(xy)
    codes = stations["station_code"].astype(str).tolist()
    adjacency: dict[str, set[str]] = {code: set() for code in codes}
    for simplex in triangulation.simplices:
        simplex_codes = [codes[int(i)] for i in simplex]
        for i, code_i in enumerate(simplex_codes):
            for code_j in simplex_codes[i + 1 :]:
                adjacency[code_i].add(code_j)
                adjacency[code_j].add(code_i)
    return adjacency


def largest_delaunay_component(stations: list[str], adjacency: dict[str, set[str]]) -> list[str]:
    station_set = set(stations)
    remaining = set(stations)
    best: list[str] = []
    while remaining:
        start = remaining.pop()
        stack = [start]
        component = {start}
        while stack:
            current = stack.pop()
            for neighbor in adjacency.get(current, set()):
                if neighbor in station_set and neighbor not in component:
                    component.add(neighbor)
                    remaining.discard(neighbor)
                    stack.append(neighbor)
        ordered_component = [s for s in stations if s in component]
        if len(ordered_component) > len(best):
            best = ordered_component
    return best


def first_cluster(
    triggers: pd.DataFrame,
    min_stations: int,
    window_sec: float,
    adjacency: dict[str, set[str]] | None = None,
) -> tuple[bool, float | None, str]:
    """Return earliest rolling-window cluster.

    If adjacency is provided, the cluster must contain a Delaunay-connected
    component with at least min_stations stations.
    """
    if triggers.empty:
        return False, None, ""

    work = triggers.sort_values(["trigger_time_sec", "station_code"]).reset_index(drop=True)
    times = work["trigger_time_sec"].to_numpy(dtype=float)
    stations = work["station_code"].astype(str).tolist()

    left = 0
    for right, t_right in enumerate(times):
        while left <= right and t_right - times[left] > window_sec + 1e-9:
            left += 1
        window_stations = ordered_unique(stations[left : right + 1])
        if adjacency is None:
            if len(window_stations) >= min_stations:
                return True, float(t_right), ",".join(window_stations)
            continue

        coord_stations = [s for s in window_stations if s in adjacency]
        component = largest_delaunay_component(coord_stations, adjacency)
        if len(component) >= min_stations:
            return True, float(t_right), ",".join(component)

    return False, None, ""


def prepare_joined(details: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    meta_cols = [
        "trace_name",
        "event_name",
        "station_code",
        "trace_p_arrival_sample",
        "trace_sampling_rate_hz",
        "source_magnitude",
        "source_depth_km",
        "station_latitude_deg",
        "station_longitude_deg",
    ]
    keep_cols = [c for c in meta_cols if c in meta.columns]
    joined = details.merge(meta[keep_cols], on="trace_name", how="left", validate="many_to_one")
    if joined["event_name"].isna().any():
        missing = int(joined["event_name"].isna().sum())
        raise ValueError(f"{missing} trigger rows could not be joined to K-NET metadata")
    joined["station_code"] = joined["station_code"].astype(str)
    joined["detected_bool"] = as_bool(joined["detected"])
    joined["p_time_sec"] = joined["p_chunk"].astype(float) * CHUNK_SEC
    joined["trigger_time_sec"] = joined["available_chunk"].astype(float) * CHUNK_SEC
    return joined


def build_event_results(
    details: pd.DataFrame,
    meta: pd.DataFrame,
    thresholds: list[float],
    confirms: list[int],
    min_stations_list: list[int],
    windows: list[float],
    adjacency: dict[str, set[str]],
) -> pd.DataFrame:
    joined = prepare_joined(details, meta)
    rows: list[EventDelaunayResult] = []
    for threshold in thresholds:
        for confirm in confirms:
            cfg = joined[
                np.isclose(joined["threshold"].astype(float), threshold)
                & (joined["confirm_chunks"].astype(int) == int(confirm))
            ].copy()
            if cfg.empty:
                continue

            for event_name, event in cfg.groupby("event_name", sort=True):
                n_stations = int(event["station_code"].nunique())
                n_coord_stations = int(event[event["station_code"].isin(adjacency)]["station_code"].nunique())
                first_p = float(event["p_time_sec"].min()) if len(event) else None
                source_mag = scalar_or_none(event["source_magnitude"].iloc[0])
                source_depth = scalar_or_none(event["source_depth_km"].iloc[0])
                detected = event[event["detected_bool"]].copy()
                n_detected = int(detected["station_code"].nunique())

                for min_stations in min_stations_list:
                    for window in windows:
                        associated, assoc_time, station_codes = first_cluster(
                            detected,
                            min_stations=min_stations,
                            window_sec=window,
                        )
                        supported, support_time, support_codes = first_cluster(
                            detected,
                            min_stations=min_stations,
                            window_sec=window,
                            adjacency=adjacency,
                        )
                        rows.append(
                            EventDelaunayResult(
                                threshold=float(threshold),
                                confirm_chunks=int(confirm),
                                min_stations=int(min_stations),
                                window_sec=float(window),
                                event_name=str(event_name),
                                source_magnitude=source_mag,
                                source_depth_km=source_depth,
                                n_stations=n_stations,
                                n_coord_stations=n_coord_stations,
                                n_station_detections=n_detected,
                                associated=bool(associated),
                                assoc_time_sec=assoc_time,
                                assoc_delay_from_first_p_sec=None
                                if assoc_time is None or first_p is None
                                else float(assoc_time - first_p),
                                station_codes_in_window=station_codes,
                                delaunay_supported=bool(supported),
                                delaunay_assoc_time_sec=support_time,
                                delaunay_delay_from_first_p_sec=None
                                if support_time is None or first_p is None
                                else float(support_time - first_p),
                                extra_delay_after_plain_assoc_sec=None
                                if assoc_time is None or support_time is None
                                else float(support_time - assoc_time),
                                delaunay_station_codes_in_window=support_codes,
                            )
                        )
    return pd.DataFrame([asdict(r) for r in rows])


def summarize(event_results: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    group_cols = ["threshold", "confirm_chunks", "min_stations", "window_sec"]
    for key, group in event_results.groupby(group_cols, sort=True):
        threshold, confirm, min_stations, window = key
        n_events = int(len(group))
        eligible = group[group["n_stations"] >= int(min_stations)]
        geometry_eligible = group[group["n_coord_stations"] >= int(min_stations)]
        associated = group[group["associated"].astype(bool)]
        supported = group[group["delaunay_supported"].astype(bool)]
        supported_delays = supported["delaunay_delay_from_first_p_sec"].dropna().astype(float)
        associated_delays = associated["assoc_delay_from_first_p_sec"].dropna().astype(float)
        extras = supported["extra_delay_after_plain_assoc_sec"].dropna().astype(float)
        rows.append(
            {
                "threshold": float(threshold),
                "confirm_chunks": int(confirm),
                "min_stations": int(min_stations),
                "window_sec": float(window),
                "n_events": n_events,
                "eligible_events": int(len(eligible)),
                "geometry_eligible_events": int(len(geometry_eligible)),
                "associated_events": int(len(associated)),
                "delaunay_supported_events": int(len(supported)),
                "association_rate_percent": float(len(associated) / n_events * 100.0)
                if n_events
                else math.nan,
                "delaunay_support_rate_percent": float(len(supported) / n_events * 100.0)
                if n_events
                else math.nan,
                "delaunay_support_among_associated_percent": float(
                    len(supported) / len(associated) * 100.0
                )
                if len(associated)
                else math.nan,
                "median_assoc_delay_from_first_p_sec": float(associated_delays.median())
                if len(associated_delays)
                else math.nan,
                "median_delaunay_delay_from_first_p_sec": float(supported_delays.median())
                if len(supported_delays)
                else math.nan,
                "p95_delaunay_delay_from_first_p_sec": float(supported_delays.quantile(0.95))
                if len(supported_delays)
                else math.nan,
                "median_extra_delay_after_plain_assoc_sec": float(extras.median())
                if len(extras)
                else math.nan,
            }
        )
    return pd.DataFrame(rows)


def dataframe_to_markdown(df: pd.DataFrame) -> str:
    cols = list(df.columns)

    def fmt(value) -> str:
        if pd.isna(value):
            return ""
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.3f}"
        return str(value)

    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(fmt(row[c]) for c in cols) + " |")
    return "\n".join(lines)


def self_check() -> None:
    adjacency = {
        "A": {"B"},
        "B": {"A", "C"},
        "C": {"B"},
        "D": set(),
    }
    assert largest_delaunay_component(["A", "B", "C"], adjacency) == ["A", "B", "C"]
    assert len(largest_delaunay_component(["A", "D"], adjacency)) == 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--details",
        type=Path,
        default=ROOT / "outputs/evaluation/confirmation_effect/knet_test_mge4_dle200_details.csv",
    )
    ap.add_argument("--metadata", type=Path, default=ROOT / "data/knet_accel/metadata.csv")
    ap.add_argument("--thresholds", default="0.55")
    ap.add_argument("--confirm-list", default="2")
    ap.add_argument("--min-stations", default="2,3")
    ap.add_argument("--windows-sec", default="3,5")
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs/evaluation/delaunay_association",
    )
    ap.add_argument("--tag", default="knet_mge4_dle200")
    ap.add_argument(
        "--dataset-label",
        default="K-NET test split, M >= 4, source distance <= 200 km",
    )
    args = ap.parse_args()

    self_check()
    thresholds = parse_float_list(args.thresholds)
    confirms = parse_int_list(args.confirm_list)
    min_stations_list = parse_int_list(args.min_stations)
    windows = parse_float_list(args.windows_sec)

    details = pd.read_csv(args.details)
    meta = pd.read_csv(args.metadata)
    adjacency = build_delaunay_adjacency(meta)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    event_results = build_event_results(
        details=details,
        meta=meta,
        thresholds=thresholds,
        confirms=confirms,
        min_stations_list=min_stations_list,
        windows=windows,
        adjacency=adjacency,
    )
    summary = summarize(event_results)

    event_path = args.output_dir / f"{args.tag}_delaunay_association_events.csv"
    summary_path = args.output_dir / f"{args.tag}_delaunay_association_summary.csv"
    report_path = args.output_dir / f"{args.tag}_delaunay_association_report.md"
    json_path = args.output_dir / f"{args.tag}_delaunay_association_summary.json"

    event_results.to_csv(event_path, index=False)
    summary.to_csv(summary_path, index=False)

    payload = {
        "protocol": "K-NET event-window Delaunay-neighbor association gate",
        "inputs": {
            "details_csv": str(args.details),
            "metadata_csv": str(args.metadata),
        },
        "chunk_sec": CHUNK_SEC,
        "thresholds": thresholds,
        "confirm_chunks": confirms,
        "min_stations": min_stations_list,
        "windows_sec": windows,
        "n_delaunay_stations": int(len(adjacency)),
        "n_events": int(event_results["event_name"].nunique()) if len(event_results) else 0,
        "outputs": {
            "event_csv": str(event_path),
            "summary_csv": str(summary_path),
            "report_md": str(report_path),
            "json": str(json_path),
        },
        "summary": summary.to_dict(orient="records"),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    report_cols = [
        "threshold",
        "confirm_chunks",
        "min_stations",
        "window_sec",
        "n_events",
        "associated_events",
        "delaunay_supported_events",
        "delaunay_support_among_associated_percent",
        "median_delaunay_delay_from_first_p_sec",
        "p95_delaunay_delay_from_first_p_sec",
        "median_extra_delay_after_plain_assoc_sec",
    ]
    report_rows = summary[report_cols].copy()
    report = [
        "# K-NET Delaunay Association Gate",
        "",
        "This post-processing check uses existing single-station K-NET trigger details and K-NET station coordinates. It does not rerun model inference.",
        "",
        "## Protocol",
        "",
        f"- Dataset: {args.dataset_label}.",
        "- Station trigger time: confirmation-completion packet time on the event-window replay axis.",
        "- Plain association: at least `min_stations` distinct stations trigger within a rolling `window_sec` time window.",
        "- Delaunay support: within the same rolling window, a Delaunay-connected station component reaches `min_stations` stations.",
        "- Scope: event-window geometry consistency check. This is not blind hypocenter estimation or chronological station-day alert validation.",
        "",
        "## Summary",
        "",
        dataframe_to_markdown(report_rows),
        "",
        "## Output Files",
        "",
        f"- `{event_path.name}`",
        f"- `{summary_path.name}`",
        f"- `{json_path.name}`",
    ]
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")

    print("Delaunay association gate:")
    print(report_rows.to_string(index=False))
    print(f"\nWrote:\n  {event_path}\n  {summary_path}\n  {json_path}\n  {report_path}")


if __name__ == "__main__":
    main()
