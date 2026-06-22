"""Combine FDSN continuous strong-motion campaign summaries."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]


def combine_rates(paths: list[Path]) -> pd.DataFrame:
    frames = [pd.read_csv(p / "campaign_stationday_false_alarm_rates.csv") for p in paths]
    data = pd.concat(frames, ignore_index=True)
    group_cols = ["gate", "threshold", "confirm_chunks"]
    out = (
        data.groupby(group_cols, as_index=False)
        .agg(
            valid_chunks=("valid_chunks", "sum"),
            valid_hours=("valid_hours", "sum"),
            station_day_equivalent=("station_day_equivalent", "sum"),
            over_threshold_chunks=("over_threshold_chunks", "sum"),
            artifact_gated_valid_chunks=("artifact_gated_valid_chunks", "sum"),
            alarm_episodes=("alarm_episodes", "sum"),
            interval_count=("interval_count", "sum"),
        )
    )
    out["over_threshold_rate_percent"] = out["over_threshold_chunks"] / out["valid_chunks"] * 100.0
    out["artifact_gated_valid_rate_percent"] = (
        out["artifact_gated_valid_chunks"] / out["valid_chunks"] * 100.0
    )
    out["false_alerts_per_hour"] = out["alarm_episodes"] / out["valid_hours"]
    out["false_alerts_per_station_day"] = out["alarm_episodes"] / out["station_day_equivalent"]
    return out


def combine_network(paths: list[Path], total_station_days: float) -> pd.DataFrame:
    frames = [pd.read_csv(p / "campaign_network_coincidence_summary.csv") for p in paths]
    data = pd.concat(frames, ignore_index=True)
    group_cols = ["gate", "threshold", "confirm_chunks", "station_n", "window_sec"]
    out = (
        data.groupby(group_cols, as_index=False)
        .agg(clusters=("clusters", "sum"), interval_count=("interval_count", "sum"))
    )
    out["clusters_per_station_day_equiv"] = out["clusters"] / total_station_days
    return out


def combine_events(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for p in paths:
        event_path = p / "campaign_event_catalog_screen.csv"
        if event_path.exists() and event_path.stat().st_size > 1:
            frames.append(pd.read_csv(event_path))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def write_report(out_dir: Path, rates: pd.DataFrame, network: pd.DataFrame, events: pd.DataFrame) -> None:
    focus = rates[(rates["threshold"].eq(0.55)) & (rates["confirm_chunks"].eq(2))]
    net_focus = network[
        (network["threshold"].eq(0.55))
        & (network["confirm_chunks"].eq(2))
        & (network["station_n"].isin([2, 3, 4]))
        & (network["window_sec"].isin([3.0, 5.0]))
    ]
    lines = [
        "# Combined FDSN Continuous Strong-Motion Campaign",
        "",
        "This combines existing campaign-level CSV summaries. It does not rerun model inference.",
        "",
        f"- Catalog events found during screened intervals: {len(events)}",
        "",
        "## Working Operating Point",
        "",
        "| Gate | Valid h | Station-day equiv. | Episodes | FA/h | FA/station-day |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in focus.sort_values("gate").to_dict(orient="records"):
        lines.append(
            f"| {row['gate']} | {row['valid_hours']:.2f} | {row['station_day_equivalent']:.2f} | "
            f"{int(row['alarm_episodes'])} | {row['false_alerts_per_hour']:.3f} | "
            f"{row['false_alerts_per_station_day']:.2f} |"
        )
    lines += [
        "",
        "## Multi-Station Time Coincidence",
        "",
        "| Gate | Confirm | N stations | Window | Clusters | Clusters/station-day equiv. |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in net_focus.sort_values(["gate", "confirm_chunks", "station_n", "window_sec"]).to_dict(
        orient="records"
    ):
        lines.append(
            f"| {row['gate']} | {int(row['confirm_chunks'])} | {int(row['station_n'])} | "
            f"{row['window_sec']:.1f} s | {int(row['clusters'])} | "
            f"{row['clusters_per_station_day_equiv']:.2f} |"
        )
    (out_dir / "combined_campaign_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def self_check() -> None:
    tmp = pd.DataFrame(
        [
            {"gate": "none", "threshold": 0.55, "confirm_chunks": 2, "valid_chunks": 10, "valid_hours": 1.0, "station_day_equivalent": 0.5, "over_threshold_chunks": 1, "artifact_gated_valid_chunks": 0, "alarm_episodes": 2, "interval_count": 1},
            {"gate": "none", "threshold": 0.55, "confirm_chunks": 2, "valid_chunks": 10, "valid_hours": 1.0, "station_day_equivalent": 0.5, "over_threshold_chunks": 1, "artifact_gated_valid_chunks": 0, "alarm_episodes": 2, "interval_count": 1},
        ]
    )
    out = (
        tmp.groupby(["gate", "threshold", "confirm_chunks"], as_index=False)
        .agg(valid_hours=("valid_hours", "sum"), station_day_equivalent=("station_day_equivalent", "sum"), alarm_episodes=("alarm_episodes", "sum"))
    )
    assert float(out["valid_hours"].iloc[0]) == 2.0
    assert float(out["alarm_episodes"].iloc[0] / out["station_day_equivalent"].iloc[0]) == 4.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--campaign-dirs",
        default="outputs/evaluation/fdsn_strong_motion_stationday_campaign_stable10,outputs/evaluation/fdsn_strong_motion_stationday_campaign_extra1h",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs/evaluation/fdsn_strong_motion_stationday_campaign_combined",
    )
    args = parser.parse_args()
    self_check()
    paths = [ROOT / p.strip() for p in args.campaign_dirs.split(",") if p.strip()]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rates = combine_rates(paths)
    total_station_days = float(rates["station_day_equivalent"].max()) if len(rates) else 0.0
    network = combine_network(paths, total_station_days)
    events = combine_events(paths)
    rates.to_csv(args.output_dir / "combined_stationday_false_alarm_rates.csv", index=False)
    network.to_csv(args.output_dir / "combined_network_coincidence_summary.csv", index=False)
    events.to_csv(args.output_dir / "combined_event_catalog_screen.csv", index=False)
    payload = {
        "campaign_dirs": [str(p) for p in paths],
        "valid_hours": total_station_days * 24.0,
        "station_day_equivalent": total_station_days,
        "event_catalog_count": int(len(events)),
    }
    (args.output_dir / "combined_campaign_summary.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    write_report(args.output_dir, rates, network, events)
    print(args.output_dir / "combined_campaign_report.md")


if __name__ == "__main__":
    main()
