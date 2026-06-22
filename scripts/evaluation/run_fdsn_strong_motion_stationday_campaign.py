"""Run and aggregate a small FDSN continuous strong-motion station-day campaign."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/evaluation/eval_fdsn_strong_motion_stationday_false_alarm.py"
DEFAULT_PYTHON = Path(sys.executable)


def parse_csv_strings(text: str) -> list[str]:
    return [x.strip() for x in text.split(",") if x.strip()]


def safe_name(text: str) -> str:
    return text.replace(":", "").replace("-", "").replace("/", "_").replace(",", "_")


def run_one(args: argparse.Namespace, start: str, out_dir: Path) -> None:
    cmd = [
        str(args.python),
        str(SCRIPT),
        "--provider",
        args.provider,
        "--event-provider",
        args.event_provider,
        "--network",
        args.network,
        "--stations",
        args.stations,
        "--channel",
        args.channel,
        "--start",
        start,
        "--duration-hours",
        str(args.duration_hours),
        "--download-chunk-hours",
        str(args.download_chunk_hours),
        "--event-min-magnitude",
        str(args.event_min_magnitude),
        "--event-bbox-padding-deg",
        str(args.event_bbox_padding_deg),
        "--reset-chunks",
        str(args.reset_chunks),
        "--boundary-exclude-chunks",
        str(args.boundary_exclude_chunks),
        "--thresholds",
        args.thresholds,
        "--confirm-list",
        args.confirm_list,
        "--gates",
        args.gates,
        "--network-station-n",
        args.network_station_n,
        "--network-windows-sec",
        args.network_windows_sec,
        "--device",
        args.device,
        "--output-dir",
        str(out_dir),
    ]
    if args.force_download:
        cmd.append("--force-download")
    print("Running:", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (out_dir / "campaign_subprocess.log").write_text(proc.stdout, encoding="utf-8")
    print(proc.stdout, flush=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Interval {start} failed with exit code {proc.returncode}")


def aggregate(interval_dirs: list[Path], out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rates = []
    network = []
    events = []
    for d in interval_dirs:
        tag = d.name
        r = pd.read_csv(d / "stationday_false_alarm_rates.csv")
        r.insert(0, "interval", tag)
        rates.append(r)
        n = pd.read_csv(d / "network_coincidence_summary.csv")
        if not n.empty:
            n.insert(0, "interval", tag)
            network.append(n)
        e = pd.read_csv(d / "event_catalog_screen.csv")
        if not e.empty:
            e.insert(0, "interval", tag)
            events.append(e)

    rate_df = pd.concat(rates, ignore_index=True)
    group_cols = ["gate", "threshold", "confirm_chunks"]
    agg_rates = (
        rate_df.groupby(group_cols, as_index=False)
        .agg(
            valid_chunks=("valid_chunks", "sum"),
            valid_hours=("valid_hours", "sum"),
            station_day_equivalent=("station_day_equivalent", "sum"),
            over_threshold_chunks=("over_threshold_chunks", "sum"),
            artifact_gated_valid_chunks=("artifact_gated_valid_chunks", "sum"),
            alarm_episodes=("alarm_episodes", "sum"),
            interval_count=("interval", "nunique"),
        )
    )
    agg_rates["over_threshold_rate_percent"] = (
        agg_rates["over_threshold_chunks"] / agg_rates["valid_chunks"] * 100.0
    )
    agg_rates["artifact_gated_valid_rate_percent"] = (
        agg_rates["artifact_gated_valid_chunks"] / agg_rates["valid_chunks"] * 100.0
    )
    agg_rates["false_alerts_per_hour"] = agg_rates["alarm_episodes"] / agg_rates["valid_hours"]
    agg_rates["false_alerts_per_station_day"] = (
        agg_rates["alarm_episodes"] / agg_rates["station_day_equivalent"]
    )

    if network:
        network_df = pd.concat(network, ignore_index=True)
        net_group_cols = ["gate", "threshold", "confirm_chunks", "station_n", "window_sec"]
        agg_net = (
            network_df.groupby(net_group_cols, as_index=False)
            .agg(clusters=("clusters", "sum"), interval_count=("interval", "nunique"))
        )
        total_station_days = float(agg_rates["station_day_equivalent"].max())
        agg_net["clusters_per_station_day_equiv"] = agg_net["clusters"] / total_station_days
    else:
        network_df = pd.DataFrame()
        agg_net = pd.DataFrame()

    event_df = pd.concat(events, ignore_index=True) if events else pd.DataFrame()
    agg_rates.to_csv(out_dir / "campaign_stationday_false_alarm_rates.csv", index=False)
    agg_net.to_csv(out_dir / "campaign_network_coincidence_summary.csv", index=False)
    rate_df.to_csv(out_dir / "campaign_interval_rates.csv", index=False)
    network_df.to_csv(out_dir / "campaign_interval_network.csv", index=False)
    event_df.to_csv(out_dir / "campaign_event_catalog_screen.csv", index=False)
    return agg_rates, agg_net, event_df


def write_report(out_dir: Path, starts: list[str], agg_rates: pd.DataFrame, agg_net: pd.DataFrame, events: pd.DataFrame, args: argparse.Namespace) -> None:
    focus = agg_rates.loc[(agg_rates["threshold"].eq(0.55)) & (agg_rates["confirm_chunks"].eq(2))]
    net_focus = agg_net.loc[
        (agg_net["threshold"].eq(0.55))
        & (agg_net["confirm_chunks"].eq(2))
        & (agg_net["station_n"].isin([2, 3]))
        & (agg_net["window_sec"].isin([3.0, 5.0]))
    ] if not agg_net.empty else pd.DataFrame()
    lines = [
        "# FDSN Continuous Strong-Motion Station-Day Campaign",
        "",
        "## Protocol",
        "",
        f"- Waveform provider: `{args.provider}`",
        f"- Event provider: `{args.event_provider}`",
        f"- Network/stations: `{args.network}` / `{args.stations}`",
        f"- Starts: {', '.join(f'`{s}`' for s in starts)}",
        f"- Duration per station per start: {args.duration_hours:.2f} h",
        f"- Event screen: M >= {args.event_min_magnitude:.1f}",
        f"- Reset chunks: {args.reset_chunks}",
        "",
        "This campaign uses public FDSN chronological strong-motion acceleration",
        "streams. It is stronger than clip-based station-time replay, but still a",
        "bounded public-data check rather than full operational certification.",
        "",
        f"Catalog events found during screened intervals: {len(events)}",
        "",
        "## Working Operating Point",
        "",
    ]
    if not focus.empty:
        lines.extend(
            [
                "| Gate | Valid h | Station-time days | Episodes | False triggers/h | False triggers per station day |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in focus.sort_values("gate").to_dict(orient="records"):
            lines.append(
                f"| {row['gate']} | {row['valid_hours']:.2f} | "
                f"{row['station_day_equivalent']:.2f} | {int(row['alarm_episodes'])} | "
                f"{row['false_alerts_per_hour']:.3f} | {row['false_alerts_per_station_day']:.2f} |"
            )
    lines.extend(["", "## Multi-Station Time Coincidence", ""])
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
    report = out_dir / "campaign_report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", type=Path, default=DEFAULT_PYTHON if DEFAULT_PYTHON.exists() else Path(sys.executable))
    ap.add_argument("--provider", default="SCEDC")
    ap.add_argument("--event-provider", default="USGS")
    ap.add_argument("--network", default="CI")
    ap.add_argument("--stations", default="PASC,SVD,USC,WTT2,BHP,CAC,GVR,HLL")
    ap.add_argument(
        "--starts",
        default="2024-01-03T00:00:00,2024-02-07T00:00:00,2024-03-12T00:00:00,2024-05-21T00:00:00",
    )
    ap.add_argument("--channel", default="HN?")
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
    ap.add_argument("--device", default="mps")
    ap.add_argument("--force-download", action="store_true")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs/evaluation/fdsn_strong_motion_stationday_campaign",
    )
    args = ap.parse_args()

    starts = parse_csv_strings(args.starts)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    interval_dirs: list[Path] = []
    for start in starts:
        interval_dir = args.output_dir / safe_name(start)
        interval_dirs.append(interval_dir)
        if args.skip_existing and (interval_dir / "stationday_false_alarm_rates.csv").exists():
            print(f"Skipping existing interval {start}: {interval_dir}", flush=True)
            continue
        interval_dir.mkdir(parents=True, exist_ok=True)
        run_one(args, start, interval_dir)

    agg_rates, agg_net, events = aggregate(interval_dirs, args.output_dir)
    write_report(args.output_dir, starts, agg_rates, agg_net, events, args)
    payload = {
        "starts": starts,
        "stations": parse_csv_strings(args.stations),
        "duration_hours": args.duration_hours,
        "outputs": {
            "report": str(args.output_dir / "campaign_report.md"),
            "rates": str(args.output_dir / "campaign_stationday_false_alarm_rates.csv"),
            "network": str(args.output_dir / "campaign_network_coincidence_summary.csv"),
        },
    }
    (args.output_dir / "campaign_summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("\nCampaign rates:")
    print(agg_rates.to_string(index=False))
    print("\nCampaign network:")
    print(agg_net.to_string(index=False) if not agg_net.empty else "(empty)")
    print(f"\nWrote report: {args.output_dir / 'campaign_report.md'}")


if __name__ == "__main__":
    main()
