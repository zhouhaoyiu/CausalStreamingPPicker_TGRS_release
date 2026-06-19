"""
knet_dataset.py — K-NET 数据集加载器

加载 K-NET HDF5 数据，
用于:
  1. 纯 K-NET 训练（替代 InstanceGM）
  2. InstanceGM 预训练 + K-NET 微调（域适应）
  3. K-NET 跨域评估（检验泛化性）

用法:
    from knet_dataset import KNETDataset
    ds = KNETDataset("data/knet_accel")
    sample = ds[0]  # {"wave": (3, L), "p_arrival_sample": int, ...}

    # 与 GaussianStreamPacketDataset 兼容:
    from knet_dataset import KNETGaussianDataset
    gds = KNETGaussianDataset(ds, split="train", max_chunks=320, label_sigma=0.5)
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import h5py
from pathlib import Path
from torch.utils.data import Dataset

from config import P_ARRIVAL_COL_CANDIDATES, SAMPLES_PER_CHUNK, TARGET_SR


class KNETDataset:
    """
    K-NET HDF5 数据集（只读，lazy loading）

    接口兼容 seisbench.data.InstanceGM:
      - .metadata  → DataFrame
      - .get_waveforms(idx) → np.ndarray (3, L)
    """

    def __init__(self, data_dir: str | Path):
        data_dir = Path(data_dir)
        self.hdf5_path = data_dir / "waveforms.hdf5"
        self.csv_path  = data_dir / "metadata.csv"

        if not self.hdf5_path.exists():
            raise FileNotFoundError(f"HDF5 not found: {self.hdf5_path}")
        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV not found: {self.csv_path}")

        # 读 metadata
        self.metadata = pd.read_csv(self.csv_path)

        # P 波列名适配
        self.p_col = None
        for col in P_ARRIVAL_COL_CANDIDATES:
            if col in self.metadata.columns:
                self.p_col = col
                break
        if self.p_col is None and "trace_p_arrival_sample" in self.metadata.columns:
            self.p_col = "trace_p_arrival_sample"

        # HDF5 handle（延迟打开，避免 pickle 问题）
        self._hf = None

        print(f"KNETDataset: {len(self.metadata)} traces from {data_dir}")
        if self.p_col:
            print(f"  P column: {self.p_col}")
        split_counts = self.metadata["split"].value_counts()
        for s in ["train", "dev", "test"]:
            print(f"  {s}: {split_counts.get(s, 0)}")

    @property
    def hf(self):
        if self._hf is None:
            self._hf = h5py.File(self.hdf5_path, "r")
        return self._hf

    def __len__(self):
        return len(self.metadata)

    def get_waveforms(self, idx: int) -> np.ndarray:
        """返回 (3, L) float32 波形"""
        row = self.metadata.iloc[idx]
        trace_name = row["trace_name"]
        wave = self.hf["data"][trace_name][:]  # (3, L)

        # 重采样到 TARGET_SR（如果需要）
        native_sr = row.get("trace_sampling_rate_hz", 100.0)
        if native_sr != TARGET_SR:
            from scipy.signal import resample
            target_npts = int(wave.shape[1] * TARGET_SR / native_sr)
            wave = resample(wave, target_npts, axis=1).astype(np.float32)
            # p_arrival 也要缩放
            # 注意：这里只改波形，p_arrival_sample 在 GaussianDataset 里处理

        return wave

    def close(self):
        if self._hf is not None:
            self._hf.close()
            self._hf = None

    def __del__(self):
        self.close()


class KNETGaussianDataset(Dataset):
    """
    K-NET 数据的 Gaussian 标签版，输出与包级流式训练接口一致

    返回格式与 GaussianStreamPacketDataset 完全一致:
      {"chunks": (max_chunks, 3, L), "labels": (max_chunks,),
       "labels_aux": (max_chunks,), "mask": (max_chunks,)}
    """
    def __init__(
        self,
        knet_ds: KNETDataset,
        split: str = "train",
        max_chunks: int = 320,
        indices: list[int] | None = None,
        label_sigma: float = 0.5,
        augmentation: bool = False,
        require_p_in_window: bool = True,
    ):
        self.knet = knet_ds
        self.max_chunks = max_chunks
        self.label_sigma = label_sigma
        self.augmentation = augmentation
        self.p_col = knet_ds.p_col

        # 筛选
        meta = knet_ds.metadata
        mask = meta["split"] == split
        if self.p_col:
            mask &= meta[self.p_col].notna()
        candidates = np.where(mask)[0]

        if indices is not None:
            idx_set = set(indices)
            candidates = np.array([i for i in candidates if i in idx_set])

        # P-in-window 过滤
        if require_p_in_window and self.p_col:
            spc = SAMPLES_PER_CHUNK
            valid = []
            for i in candidates:
                row = meta.iloc[i]
                p_s = float(row[self.p_col])
                npts = row.get("trace_npts", max_chunks * spc)
                if npts is None or pd.isna(npts):
                    npts = max_chunks * spc
                # 考虑重采样
                native_sr = row.get("trace_sampling_rate_hz", 100.0)
                if native_sr != TARGET_SR:
                    p_s = p_s * TARGET_SR / native_sr
                    npts = int(npts * TARGET_SR / native_sr)
                if 0 <= p_s < npts:
                    valid.append(i)
            candidates = np.array(valid)

        self.indices = candidates
        print(f"KNETGaussianDataset [{split}]: {len(self.indices)} traces, sigma={label_sigma}")

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, idx):
        import math
        import torch
        from data_streaming import normalize_packet_causal

        i = self.indices[idx]
        row = self.knet.metadata.iloc[i]
        wave = self.knet.get_waveforms(i)

        if wave.shape[0] != 3:
            wave = wave[:3]

        # P 到时（可能需要重采样缩放）
        p_s = float(row[self.p_col])
        native_sr = row.get("trace_sampling_rate_hz", 100.0)
        if native_sr != TARGET_SR:
            p_s = p_s * TARGET_SR / native_sr

        if self.augmentation:
            shift = np.random.randint(-25, 26)
            p_s += shift
            p_s = max(SAMPLES_PER_CHUNK, p_s)

        npts = wave.shape[1]
        spc = SAMPLES_PER_CHUNK
        n_chunks = min((npts + spc - 1) // spc, self.max_chunks)
        p_chunk = p_s / spc

        chunks = np.zeros((n_chunks, 3, spc), dtype=np.float32)
        labels_p = np.zeros(n_chunks, dtype=np.float32)
        labels_aux = np.zeros(n_chunks, dtype=np.float32)

        for k in range(n_chunks):
            dist = k - p_chunk
            labels_p[k] = math.exp(-0.5 * (dist / self.label_sigma) ** 2)
            labels_aux[k] = 1.0 if k >= int(round(p_chunk)) else 0.0

        running_stats = None
        for k in range(n_chunks):
            a, b = k * spc, min((k + 1) * spc, npts)
            seg = wave[:, a:b]
            valid_samples = None
            if b - a < spc:
                valid_samples = b - a
                pad = np.zeros((3, spc - (b - a)), dtype=wave.dtype)
                seg = np.concatenate([seg, pad], axis=1)
            chunks[k], running_stats = normalize_packet_causal(
                seg.astype(np.float64), running_stats,
                valid_samples=valid_samples,
            )

        full_chunks = torch.zeros(self.max_chunks, 3, spc)
        full_labels = torch.zeros(self.max_chunks)
        full_aux    = torch.zeros(self.max_chunks)
        full_mask   = torch.zeros(self.max_chunks)
        full_chunks[:n_chunks] = torch.from_numpy(chunks)
        full_labels[:n_chunks] = torch.from_numpy(labels_p)
        full_aux[:n_chunks]    = torch.from_numpy(labels_aux)
        full_mask[:n_chunks]   = 1.0

        return {
            "chunks": full_chunks,
            "labels": full_labels,
            "labels_aux": full_aux,
            "mask": full_mask,
        }
