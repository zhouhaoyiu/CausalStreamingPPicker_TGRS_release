"""
多域联合训练模型 — 双域 Test 集评估

同时评估 InstanceGM 和 K-NET 的测试子集，输出:
  - 各域可用率、检测率、perfect/good/early/late/miss 分布
  - InstanceGM 按仪器类型细分（测震 vs 强震动）

用法:
    python eval_multidomain_test.py \
        --checkpoint models/checkpoints/multidomain_best.pt \
        --knet-dir data/knet_accel \
        --min-mag 4.0 \
        --device mps

    # CPU reproduction run
    python eval_multidomain_test.py \
        --checkpoint models/checkpoints/multidomain_best.pt \
        --knet-dir data/knet_accel \
        --min-mag 4.0 \
        --device cpu
"""
from __future__ import annotations
import argparse
import gc
import os
import sys
import time
import numpy as np
import torch
import torch.nn as nn
from pathlib import Path
from collections import Counter
from project_paths import DATA_DIR

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SAMPLES_PER_CHUNK, TARGET_SR, P_ARRIVAL_COL_CANDIDATES
from model import CausalStreamingPPicker as CausalStreamingPPickerModel
from data_streaming import normalize_packet_causal


DOMAIN_KNET_STRONG = 0
DOMAIN_IG_STRONG = 1
DOMAIN_IG_SEISMIC = 2
DOMAIN_UNKNOWN = 3


def domain_ids_for_instance_types(inst_types, device):
    ids = []
    for inst in inst_types:
        if inst == "strong_motion":
            ids.append(DOMAIN_IG_STRONG)
        elif inst == "seismic":
            ids.append(DOMAIN_IG_SEISMIC)
        else:
            ids.append(DOMAIN_UNKNOWN)
    return torch.tensor(ids, device=device, dtype=torch.long)


# ──────────────────────── K-NET Dataset ────────────────────────

class KNETGaussianDataset(torch.utils.data.Dataset):
    """K-NET 数据集"""

    def __init__(self, data_dir: Path, split: str = "test",
                 max_chunks: int = 320, sigma: float = 1.5,
                 min_mag: float = 0, max_dist: float = 9999):
        import pandas as pd

        self.hdf5_path = data_dir / "waveforms.hdf5"
        self.csv_path = data_dir / "metadata.csv"
        self.max_chunks = max_chunks
        self.sigma = sigma
        self.spc = SAMPLES_PER_CHUNK

        self.metadata = pd.read_csv(self.csv_path)
        self._hf = None

        self.p_col = None
        for col in P_ARRIVAL_COL_CANDIDATES:
            if col in self.metadata.columns:
                self.p_col = col
                break
        if self.p_col is None and "trace_p_arrival_sample" in self.metadata.columns:
            self.p_col = "trace_p_arrival_sample"

        mask = self.metadata["split"] == split
        mask &= self.metadata[self.p_col].notna()
        if min_mag > 0 and "source_magnitude" in self.metadata.columns:
            mask &= self.metadata["source_magnitude"].notna()
            mask &= self.metadata["source_magnitude"] >= min_mag
        if max_dist < 9999 and "source_distance_km" in self.metadata.columns:
            mask &= self.metadata["source_distance_km"].notna()
            mask &= self.metadata["source_distance_km"] <= max_dist

        self.indices = np.where(mask)[0]
        print(f"KNETGaussianDataset: {len(self.indices)} traces (split={split})")

    @property
    def hf(self):
        if self._hf is None:
            import h5py
            self._hf = h5py.File(self.hdf5_path, "r")
        return self._hf

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, i):
        idx = self.indices[i]
        row = self.metadata.iloc[idx]
        trace_name = row["trace_name"]

        try:
            wave = self.hf["data"][trace_name][:].astype(np.float32)
        except Exception:
            wave = np.zeros((3, 10000), dtype=np.float32)

        if wave.shape[0] != 3:
            wave = wave[:3]

        native_sr = float(row.get("trace_sampling_rate_hz", 100.0))
        if native_sr != TARGET_SR:
            from scipy.signal import resample
            target_npts = int(wave.shape[1] * TARGET_SR / native_sr)
            wave = resample(wave, target_npts, axis=1).astype(np.float32)

        npts = wave.shape[1]
        n_chunks = min((npts + self.spc - 1) // self.spc, self.max_chunks)

        chunks = np.zeros((self.max_chunks, 3, self.spc), dtype=np.float32)
        running_stats = None
        for k in range(n_chunks):
            a, b = k * self.spc, min((k + 1) * self.spc, npts)
            seg = wave[:, a:b]
            valid_samples = None
            if b - a < self.spc:
                valid_samples = b - a
                pad = np.zeros((3, self.spc - (b - a)), dtype=wave.dtype)
                seg = np.concatenate([seg, pad], axis=1)
            normed, running_stats = normalize_packet_causal(
                seg.astype(np.float64), running_stats, valid_samples=valid_samples
            )
            chunks[k] = normed.astype(np.float32)

        p_s = float(row[self.p_col])
        if native_sr != TARGET_SR:
            p_s = p_s * TARGET_SR / native_sr
        p_chunk = int(round(p_s / self.spc))

        ks = np.arange(n_chunks, dtype=np.float32)
        label = np.exp(-0.5 * ((ks - p_chunk) / self.sigma) ** 2).astype(np.float32)

        full_label = np.zeros(self.max_chunks, dtype=np.float32)
        full_label[:n_chunks] = label

        return (
            torch.from_numpy(chunks),
            torch.from_numpy(full_label),
            n_chunks,
            p_chunk,
        )


# ──────────────────────── InstanceGM Dataset ────────────────────────

class InstanceGMGaussianDataset(torch.utils.data.Dataset):
    """InstanceGM 数据集，带仪器类型标签"""

    def __init__(self, split: str = "test", max_chunks: int = 320,
                 sigma: float = 1.5, min_mag: float = 0, max_dist: float = 9999):
        from seisbench.data import InstanceGM
        import pandas as pd

        self.ds = InstanceGM(cache="trace", metadata_cache=True, component_order="ZNE")
        self.max_chunks = max_chunks
        self.sigma = sigma
        self.spc = SAMPLES_PER_CHUNK

        self.p_col = None
        for col in P_ARRIVAL_COL_CANDIDATES:
            if col in self.ds.metadata.columns:
                self.p_col = col
                break

        dv = self.ds.metadata["split"] == split
        dv &= self.ds.metadata[self.p_col].notna()

        if min_mag > 0 and "source_magnitude" in self.ds.metadata.columns:
            dv &= self.ds.metadata["source_magnitude"].notna()
            dv &= self.ds.metadata["source_magnitude"] >= min_mag
        if max_dist < 9999:
            dist_col = None
            for c in ["path_ep_distance_km", "path_hyp_distance_km"]:
                if c in self.ds.metadata.columns:
                    dist_col = c
                    break
            if dist_col:
                dv &= self.ds.metadata[dist_col].notna()
                dv &= self.ds.metadata[dist_col] <= max_dist

        self.indices = np.where(dv)[0]
        print(f"InstanceGMGaussianDataset: {len(self.indices)} traces (split={split}, M>={min_mag})")

    def __len__(self):
        return len(self.indices)

    def _get_instrument_type(self, row):
        """判断仪器类型: seismic / strong_motion / unknown"""
        import pandas as pd
        ch_col = None
        for c in ["station_channels", "trace_channel"]:
            if c in row.index and pd.notna(row[c]):
                ch_col = c
                break
        if ch_col is None:
            return "unknown"

        ch = str(row[ch_col]).upper()
        if any(ch.startswith(p) for p in ["HH", "EH", "HL", "BH", "SH"]):
            return "seismic"
        elif any(ch.startswith(p) for p in ["HN", "EN", "BN"]):
            return "strong_motion"
        else:
            return "unknown"

    def __getitem__(self, i):
        gi = self.indices[i]
        row = self.ds.metadata.iloc[gi]

        try:
            wave = self.ds.get_waveforms(int(gi)).astype(np.float32)
        except Exception:
            wave = np.zeros((3, 10000), dtype=np.float32)

        if wave.shape[0] != 3:
            wave = wave[:3]

        npts = wave.shape[1]
        p_sample = float(row[self.p_col])
        if p_sample < 0 or p_sample >= npts:
            chunks = np.zeros((self.max_chunks, 3, self.spc), dtype=np.float32)
            full_label = np.zeros(self.max_chunks, dtype=np.float32)
            return (
                torch.from_numpy(chunks),
                torch.from_numpy(full_label),
                0, 0, "unknown",
            )

        n_chunks = min((npts + self.spc - 1) // self.spc, self.max_chunks)

        chunks = np.zeros((self.max_chunks, 3, self.spc), dtype=np.float32)
        running_stats = None
        for k in range(n_chunks):
            a, b = k * self.spc, min((k + 1) * self.spc, npts)
            seg = wave[:, a:b]
            valid_samples = None
            if b - a < self.spc:
                valid_samples = b - a
                pad = np.zeros((3, self.spc - (b - a)), dtype=wave.dtype)
                seg = np.concatenate([seg, pad], axis=1)
            normed, running_stats = normalize_packet_causal(
                seg.astype(np.float64), running_stats, valid_samples=valid_samples
            )
            chunks[k] = normed.astype(np.float32)

        p_chunk = int(round(p_sample / self.spc))

        ks = np.arange(n_chunks, dtype=np.float32)
        label = np.exp(-0.5 * ((ks - p_chunk) / self.sigma) ** 2).astype(np.float32)

        full_label = np.zeros(self.max_chunks, dtype=np.float32)
        full_label[:n_chunks] = label

        inst_type = self._get_instrument_type(row)

        return (
            torch.from_numpy(chunks),
            torch.from_numpy(full_label),
            n_chunks,
            p_chunk,
            inst_type,
        )


# ──────────────────────── 模型加载 ────────────────────────

def load_model(ckpt_path, device):
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    cfg = ckpt.get("config", {})
    model = CausalStreamingPPickerModel(
        encoder_hid=int(cfg.get("encoder_hid", 64)),
        gru_hid=int(cfg.get("gru_hid", 128)),
        gru_layers=int(cfg.get("gru_layers", 2)),
        dropout=float(cfg.get("dropout", 0.15)),
        max_chunks=int(cfg.get("max_chunks", 320)),
        feature_mode=str(cfg.get("feature_mode", "zne")),
        num_domains=int(cfg.get("num_domains", 0)),
        domain_calibration=bool(cfg.get("domain_calibration", False)),
        domain_conditioning=str(cfg.get("domain_conditioning", "bias" if cfg.get("domain_calibration", False) else "none")),
    ).to(device)

    state_dict = ckpt["model"]
    model_sd = model.state_dict()
    loaded, skipped = 0, 0
    for k, v in state_dict.items():
        if k in model_sd and v.shape == model_sd[k].shape:
            model_sd[k] = v
            loaded += 1
        else:
            skipped += 1
    model.load_state_dict(model_sd)
    print(f"加载模型: {ckpt_path}")
    print(f"  参数匹配: {loaded}, 跳过: {skipped}")
    print(f"  训练 epoch: {ckpt.get('epoch', '?')}")
    ig_m = ckpt.get("ig_metrics", {})
    knet_m = ckpt.get("knet_metrics", {})
    if ig_m:
        print(f"  IG dev 可用率: {ig_m.get('usable_rate', '?')}%")
    if knet_m:
        print(f"  K-NET dev 可用率: {knet_m.get('usable_rate', '?')}%")
    combined = ckpt.get("combined_hmean", None)
    if combined is not None:
        print(f"  调和均值: {combined:.1f}%")

    return model


# ──────────────────────── 评估 ────────────────────────

@torch.inference_mode()
def evaluate_knet(model, loader, device, max_chunks=320, threshold=0.55, margin=3):
    """评估 K-NET 数据集"""
    from tqdm import tqdm
    model.eval()
    cats = Counter()
    all_gaps = []

    for chunks, labels, n_chunks, p_chunks in tqdm(loader, desc="K-NET test", ncols=100):
        chunks = chunks.to(device)
        B = chunks.shape[0]

        domain_ids = None
        if getattr(model, "uses_domain_ids", False):
            domain_ids = torch.full(
                (B,), DOMAIN_KNET_STRONG, device=device, dtype=torch.long
            )
        logits_p, _, _ = model(chunks, domain_ids=domain_ids)
        probs = torch.sigmoid(logits_p)

        for b in range(B):
            nc = n_chunks[b].item()
            if nc <= 0:
                continue
            p_prob = probs[b, :nc].cpu().numpy()
            p_chunk = p_chunks[b].item()

            ff = None
            for j, p in enumerate(p_prob):
                if p >= threshold:
                    ff = j
                    break

            if ff is None:
                cats["miss"] += 1
            else:
                gap = ff - p_chunk
                all_gaps.append(gap)
                if abs(gap) <= 1:
                    cats["perfect"] += 1
                elif abs(gap) <= margin:
                    cats["good"] += 1
                elif gap < -margin:
                    cats["early"] += 1
                else:
                    cats["late"] += 1

        if device.type == "mps":
            gc.collect()
            torch.mps.empty_cache()

    n = sum(cats.values())
    usable = cats.get("perfect", 0) + cats.get("good", 0)
    detected = n - cats.get("miss", 0)

    result = {
        "usable_rate": usable / n * 100 if n > 0 else 0,
        "detect_rate": detected / n * 100 if n > 0 else 0,
        "perfect_rate": cats.get("perfect", 0) / n * 100 if n > 0 else 0,
        "n": n,
        "cats": dict(cats),
    }
    if all_gaps:
        gaps = np.array(all_gaps)
        result["mean_gap"] = float(gaps.mean())
        result["median_gap"] = float(np.median(gaps))
        result["std_gap"] = float(gaps.std())

    return result


@torch.inference_mode()
def evaluate_ig(model, loader, device, max_chunks=320, threshold=0.55, margin=3):
    """评估 InstanceGM 数据集，按仪器类型细分"""
    from tqdm import tqdm
    model.eval()

    cats_all = Counter()
    cats_seismic = Counter()
    cats_strong = Counter()
    cats_unknown = Counter()
    gaps_all = []
    gaps_seismic = []
    gaps_strong = []

    for chunks, labels, n_chunks, p_chunks, inst_types in tqdm(
        loader, desc="InstanceGM test", ncols=100
    ):
        chunks = chunks.to(device)
        B = chunks.shape[0]

        domain_ids = None
        if getattr(model, "uses_domain_ids", False):
            domain_ids = domain_ids_for_instance_types(inst_types, device)
        logits_p, _, _ = model(chunks, domain_ids=domain_ids)
        probs = torch.sigmoid(logits_p)

        for b in range(B):
            nc = n_chunks[b].item()
            if nc <= 0:
                continue
            p_prob = probs[b, :nc].cpu().numpy()
            p_chunk = p_chunks[b].item()
            inst = inst_types[b]

            ff = None
            for j, p in enumerate(p_prob):
                if p >= threshold:
                    ff = j
                    break

            cat = None
            if ff is None:
                cat = "miss"
            else:
                gap = ff - p_chunk
                gaps_all.append(gap)
                if abs(gap) <= 1:
                    cat = "perfect"
                elif abs(gap) <= margin:
                    cat = "good"
                elif gap < -margin:
                    cat = "early"
                else:
                    cat = "late"

            cats_all[cat] += 1
            if inst == "seismic":
                cats_seismic[cat] += 1
                if ff is not None:
                    gaps_seismic.append(gap)
            elif inst == "strong_motion":
                cats_strong[cat] += 1
                if ff is not None:
                    gaps_strong.append(gap)
            else:
                cats_unknown[cat] += 1

        if device.type == "mps":
            gc.collect()
            torch.mps.empty_cache()

    def summarize(cats, gaps, label):
        n = sum(cats.values())
        usable = cats.get("perfect", 0) + cats.get("good", 0)
        detected = n - cats.get("miss", 0)
        result = {
            "label": label,
            "n": n,
            "usable_rate": usable / n * 100 if n > 0 else 0,
            "detect_rate": detected / n * 100 if n > 0 else 0,
            "perfect_rate": cats.get("perfect", 0) / n * 100 if n > 0 else 0,
            "cats": dict(cats),
        }
        if gaps:
            g = np.array(gaps)
            result["mean_gap"] = float(g.mean())
            result["median_gap"] = float(np.median(g))
            result["std_gap"] = float(g.std())
        return result

    return {
        "overall": summarize(cats_all, gaps_all, "Overall"),
        "seismic": summarize(cats_seismic, gaps_seismic, "测震(HH/EH/HL)"),
        "strong_motion": summarize(cats_strong, gaps_strong, "强震动(HN/EN)"),
        "unknown": summarize(cats_unknown, [], "未知"),
    }


# ──────────────────────── 打印结果 ────────────────────────

def print_knet_result(r, title="K-NET Test"):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    print(f"  样本数: {r['n']}")
    print(f"  可用率: {r['usable_rate']:.1f}%")
    print(f"  检测率: {r['detect_rate']:.1f}%")
    print(f"  Perfect: {r['perfect_rate']:.1f}%")
    cats = r['cats']
    print(f"  分布: perfect={cats.get('perfect',0)} good={cats.get('good',0)} "
          f"early={cats.get('early',0)} late={cats.get('late',0)} miss={cats.get('miss',0)}")
    if 'mean_gap' in r:
        print(f"  误差: mean={r['mean_gap']:+.2f} chunks, "
              f"median={r['median_gap']:+.1f} chunks, std={r['std_gap']:.2f}")


def print_ig_result(r, title="InstanceGM Test"):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

    for key in ["overall", "seismic", "strong_motion", "unknown"]:
        sub = r[key]
        if sub['n'] == 0:
            continue
        print(f"\n  [{sub['label']}] n={sub['n']}")
        print(f"    可用率: {sub['usable_rate']:.1f}%")
        print(f"    检测率: {sub['detect_rate']:.1f}%")
        print(f"    Perfect: {sub['perfect_rate']:.1f}%")
        cats = sub['cats']
        print(f"    分布: perfect={cats.get('perfect',0)} good={cats.get('good',0)} "
              f"early={cats.get('early',0)} late={cats.get('late',0)} miss={cats.get('miss',0)}")
        if 'mean_gap' in sub:
            print(f"    误差: mean={sub['mean_gap']:+.2f} chunks, "
                  f"median={sub['median_gap']:+.1f} chunks, std={sub['std_gap']:.2f}")


# ──────────────────────── 主函数 ────────────────────────

def main():
    import pandas as pd

    ap = argparse.ArgumentParser(description="多域模型双域 Test 评估")
    ap.add_argument("--checkpoint", type=str, required=True,
                    help="模型 checkpoint 路径")
    ap.add_argument("--knet-dir", type=str,
                    default=str(DATA_DIR / "knet_accel"),
                    help="K-NET 数据目录")
    ap.add_argument("--min-mag", type=float, default=0,
                    help="最小震级过滤 (默认不过滤, 设4.0只看M4+)")
    ap.add_argument("--max-dist", type=float, default=9999,
                    help="最大距离过滤 (km)")
    ap.add_argument("--threshold", type=float, default=0.55,
                    help="P 波检测阈值")
    ap.add_argument("--margin", type=int, default=3,
                    help="good 判定容差 (chunks)")
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--device", type=str, default="mps")
    ap.add_argument("--sigma", type=float, default=1.5)
    ap.add_argument("--skip-knet", action="store_true",
                    help="跳过 K-NET 评估")
    ap.add_argument("--skip-ig", action="store_true",
                    help="跳过 InstanceGM 评估")
    args = ap.parse_args()

    if args.device == "mps" and not torch.backends.mps.is_available():
        args.device = "cpu"
    device = torch.device(args.device)

    # 加载模型
    model = load_model(args.checkpoint, device)

    # ──── K-NET Test ────
    if not args.skip_knet:
        print("\n加载 K-NET test 数据...")
        knet_test = KNETGaussianDataset(
            Path(args.knet_dir), split="test", sigma=args.sigma,
            min_mag=args.min_mag, max_dist=args.max_dist,
        )
        knet_loader = torch.utils.data.DataLoader(
            knet_test, batch_size=args.batch_size, shuffle=False,
            num_workers=0, pin_memory=False,
        )

        t0 = time.time()
        knet_result = evaluate_knet(
            model, knet_loader, device,
            max_chunks=320, threshold=args.threshold, margin=args.margin,
        )
        elapsed = time.time() - t0
        print_knet_result(knet_result)
        print(f"\n  耗时: {elapsed:.0f}s")

    # ──── InstanceGM Test ────
    if not args.skip_ig:
        print("\n加载 InstanceGM test 数据...")
        ig_test = InstanceGMGaussianDataset(
            split="test", sigma=args.sigma,
            min_mag=args.min_mag, max_dist=args.max_dist,
        )
        ig_loader = torch.utils.data.DataLoader(
            ig_test, batch_size=args.batch_size, shuffle=False,
            num_workers=0, pin_memory=False,
        )

        t0 = time.time()
        ig_result = evaluate_ig(
            model, ig_loader, device,
            max_chunks=320, threshold=args.threshold, margin=args.margin,
        )
        elapsed = time.time() - t0
        print_ig_result(ig_result)
        print(f"\n  耗时: {elapsed:.0f}s")

    # ──── 汇总对比 ────
    print(f"\n{'='*60}")
    print(f"  汇总对比")
    print(f"{'='*60}")
    print(f"  模型: {args.checkpoint}")
    print(f"  过滤: M>={args.min_mag}, dist<={args.max_dist}km")

    if not args.skip_knet:
        print(f"  K-NET test 可用率: {knet_result['usable_rate']:.1f}%  "
              f"检测率: {knet_result['detect_rate']:.1f}%")
    if not args.skip_ig:
        ig_overall = ig_result['overall']
        ig_seis = ig_result['seismic']
        ig_strong = ig_result['strong_motion']
        print(f"  IG test  总体可用率: {ig_overall['usable_rate']:.1f}%  "
              f"检测率: {ig_overall['detect_rate']:.1f}%")
        print(f"  IG test  测震可用率: {ig_seis['usable_rate']:.1f}%  "
              f"检测率: {ig_seis['detect_rate']:.1f}%")
        print(f"  IG test  强震动可用率: {ig_strong['usable_rate']:.1f}%  "
              f"检测率: {ig_strong['detect_rate']:.1f}%")

    if not args.skip_knet and not args.skip_ig:
        ig_u = ig_overall['usable_rate']
        knet_u = knet_result['usable_rate']
        if ig_u > 0 and knet_u > 0:
            hmean = 2 * ig_u * knet_u / (ig_u + knet_u)
            print(f"  调和均值: {hmean:.1f}%")


if __name__ == "__main__":
    main()
