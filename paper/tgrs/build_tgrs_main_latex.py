from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs/submission/tgrs_main_latex"
ZIP_PATH = OUT_DIR / "tgrs_causal_streaming_picker_latex.zip"

PACKAGE_FILES = [
    ("paper/tgrs/tgrs_causal_streaming_picker.tex", "tgrs_causal_streaming_picker.tex"),
    ("paper/tgrs/tgrs_causal_streaming_picker.bbl", "tgrs_causal_streaming_picker.bbl"),
    ("paper/tgrs/references.bib", "references.bib"),
    ("paper/tgrs/external_evidence_closure_honest_20260617.tex", "external_evidence_closure_honest_20260617.tex"),
    ("paper/tgrs/figures/fig_task_positioning_en.pdf", "figures/fig_task_positioning_en.pdf"),
    ("paper/tgrs/figures/fig_architecture_en.pdf", "figures/fig_architecture_en.pdf"),
    ("paper/tgrs/figures/fig1_firstp_latency_en_column.pdf", "figures/fig1_firstp_latency_en_column.pdf"),
    ("paper/tgrs/figures/fig_causal_replay_case_en.pdf", "figures/fig_causal_replay_case_en.pdf"),
    ("paper/tgrs/figures/fig2_knet_bins_en_column.pdf", "figures/fig2_knet_bins_en_column.pdf"),
    ("paper/tgrs/figures/fig_knet_imperfect_association_en.pdf", "figures/fig_knet_imperfect_association_en.pdf"),
    ("paper/tgrs/figures/fig_operating_tradeoff_en.pdf", "figures/fig_operating_tradeoff_en.pdf"),
    ("paper/tgrs/figures/table_station_detailed_metrics_en.tex", "figures/table_station_detailed_metrics_en.tex"),
    ("paper/tgrs/figures/table_knet_stratified_detailed_en.tex", "figures/table_knet_stratified_detailed_en.tex"),
    ("paper/tgrs/figures/table_spike_false_alarm_en.tex", "figures/table_spike_false_alarm_en.tex"),
    ("paper/tgrs/figures/table_continuous_false_alarm_en.tex", "figures/table_continuous_false_alarm_en.tex"),
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_member(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    zf.writestr(info, data, compresslevel=9)


def main() -> None:
    files: list[tuple[str, str, bytes]] = []
    for source_rel, archive_name in PACKAGE_FILES:
        source = ROOT / source_rel
        if not source.is_file():
            raise FileNotFoundError(source)
        files.append((source_rel, archive_name, source.read_bytes()))

    manifest = ["archive_path\tsource_path\tsha256"]
    manifest.extend(f"{name}\t{source}\t{sha256(data)}" for source, name, data in files)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = ZIP_PATH.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w") as zf:
        for _, archive_name, data in files:
            write_member(zf, archive_name, data)
        write_member(zf, "SOURCE_PACKAGE_MANIFEST.tsv", ("\n".join(manifest) + "\n").encode("utf-8"))
    temporary.replace(ZIP_PATH)

    with zipfile.ZipFile(ZIP_PATH) as zf:
        bad = zf.testzip()
    if bad:
        raise RuntimeError(f"corrupt ZIP member: {bad}")
    print(f"Wrote {ZIP_PATH}")


if __name__ == "__main__":
    main()
