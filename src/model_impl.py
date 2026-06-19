"""CausalStreamingPPicker model definition.

The model combines a causal packet encoder, inter-packet delta features,
normalized packet position, and a unidirectional GRU state. The public class
name is ``CausalStreamingPPicker``.
"""
from __future__ import annotations
import math
import torch
import torch.nn as nn


# ==================== 物理先验特征 ====================

class PhysicsFeatureExtractor(nn.Module):
    """Causal per-sample channels tied to P-wave polarization and energy growth."""

    def __init__(self, mode: str = "zne"):
        super().__init__()
        if mode not in {"zne", "physics"}:
            raise ValueError(f"Unknown feature_mode: {mode}")
        self.mode = mode
        self.out_channels = 4 if mode == "zne" else 7

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z_energy  = x[:, 0, :].pow(2)
        n_energy  = x[:, 1, :].pow(2)
        e_energy  = x[:, 2, :].pow(2)
        h_energy  = n_energy + e_energy
        total_energy = z_energy + h_energy

        z_over_h = torch.log1p(z_energy / (h_energy + 1e-6)).unsqueeze(1)
        if self.mode == "zne":
            return torch.cat([x, z_over_h], dim=1)

        z_fraction = (z_energy / (total_energy + 1e-6)).unsqueeze(1)
        log_h_energy = torch.log1p(h_energy).unsqueeze(1)
        log_total_energy = torch.log1p(total_energy).unsqueeze(1)
        return torch.cat(
            [x, z_over_h, z_fraction, log_h_energy, log_total_energy],
            dim=1,
        )


# ==================== 注意力池化 ====================

class TemporalAttentionPool(nn.Module):
    def __init__(self, channels: int, dropout: float = 0.1):
        super().__init__()
        mid = max(channels // 4, 8)
        self.attn = nn.Sequential(
            nn.Linear(channels, mid),
            nn.Tanh(),
            nn.Linear(mid, 1),
        )
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        w = self.attn(x.permute(0, 2, 1))
        w = torch.softmax(w, dim=1)
        w = self.dropout(w)
        return (x * w.permute(0, 2, 1)).sum(dim=2)


# ==================== 残差因果卷积块 ====================

class ResidualCausalBlock(nn.Module):
    def __init__(self, channels: int, kernel_size: int = 3, dropout: float = 0.1):
        super().__init__()
        pad = kernel_size - 1
        self.block = nn.Sequential(
            nn.BatchNorm1d(channels), nn.ReLU(inplace=True), nn.Dropout(dropout),
            nn.ConstantPad1d((pad, 0), 0.0), nn.Conv1d(channels, channels, kernel_size),
            nn.BatchNorm1d(channels), nn.ReLU(inplace=True), nn.Dropout(dropout),
            nn.ConstantPad1d((pad, 0), 0.0), nn.Conv1d(channels, channels, kernel_size),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.block(x)


# ==================== 编码器 ====================

class CausalChunkEncoder(nn.Module):
    def __init__(
        self,
        in_ch: int = 3,
        hid: int = 64,
        dropout: float = 0.15,
        feature_mode: str = "zne",
    ):
        super().__init__()
        self.features = PhysicsFeatureExtractor(mode=feature_mode)
        cnn_in_ch = self.features.out_channels
        ch1 = max(16, hid // 4)
        ch2 = max(32, hid // 2)
        self.hid = hid
        self.conv = nn.Sequential(
            nn.ConstantPad1d((6, 0), 0.0), nn.Conv1d(cnn_in_ch, ch1, 7),
            nn.BatchNorm1d(ch1), nn.ReLU(inplace=True), nn.Dropout(dropout),
            nn.ConstantPad1d((4, 0), 0.0), nn.Conv1d(ch1, ch2, 5),
            nn.BatchNorm1d(ch2), nn.ReLU(inplace=True), nn.Dropout(dropout),
            nn.ConstantPad1d((4, 0), 0.0), nn.Conv1d(ch2, hid, 5, stride=2),
            nn.BatchNorm1d(hid), nn.ReLU(inplace=True), nn.Dropout(dropout),
            nn.ConstantPad1d((2, 0), 0.0), nn.Conv1d(hid, hid, 3),
            nn.BatchNorm1d(hid), nn.ReLU(inplace=True), nn.Dropout(dropout),
        )
        self.res1 = ResidualCausalBlock(hid, kernel_size=3, dropout=dropout)
        self.res2 = ResidualCausalBlock(hid, kernel_size=3, dropout=dropout)
        self.attn_pool = TemporalAttentionPool(hid, dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.features(x)
        x = self.conv(x)
        x = self.res1(x)
        x = self.res2(x)
        return self.attn_pool(x)


# ==================== 主模型 ====================

class CausalStreamingPPicker(nn.Module):
    """
    Delta-feature causal streaming picker.

    GRU 输入 = [feat(t), delta(t), pos(t)]
             = encoder_hid + encoder_hid + 1
             = encoder_hid*2 + 1

    训练接口（不变）:
      forward(chunks, h0) → (logits_p, logits_aux, h_n)

    流式接口（新增 prev_feat 参数和返回值）:
      forward_streaming_packet(pkt, h, packet_idx, prev_feat) → (logit, h_new, feat)
      - prev_feat: 上一个 chunk 的 encoder 输出，首包传 None
      - 返回的 feat 作为下一包的 prev_feat
    """

    def __init__(
        self,
        encoder_hid: int = 64,
        gru_hid: int = 128,
        gru_layers: int = 2,
        dropout: float = 0.15,
        max_chunks: int = 320,
        feature_mode: str = "zne",
        num_domains: int = 0,
        domain_calibration: bool = False,
        domain_conditioning: str = "none",
    ):
        super().__init__()
        if domain_conditioning not in {"none", "bias", "film"}:
            raise ValueError(f"Unknown domain_conditioning: {domain_conditioning}")
        if domain_calibration and domain_conditioning == "none":
            domain_conditioning = "bias"
        self.encoder = CausalChunkEncoder(
            in_ch=3,
            hid=encoder_hid,
            dropout=dropout,
            feature_mode=feature_mode,
        )
        self.encoder_hid = encoder_hid
        self.max_chunks = max_chunks
        self.feature_mode = feature_mode
        self.num_domains = int(num_domains)
        self.domain_conditioning = domain_conditioning if self.num_domains > 0 else "none"
        self.domain_calibration = self.domain_conditioning == "bias"
        self.uses_domain_ids = self.domain_conditioning != "none"

        # GRU input: feat + delta + pos = encoder_hid*2 + 1
        gru_input_size = encoder_hid * 2 + 1

        self.gru = nn.GRU(
            gru_input_size, gru_hid, num_layers=gru_layers,
            batch_first=True,
            dropout=dropout if gru_layers > 1 else 0.0,
            bidirectional=False,
        )

        self.head_p = nn.Linear(gru_hid, 1)
        nn.init.xavier_uniform_(self.head_p.weight)
        nn.init.constant_(self.head_p.bias, -3.0)

        if self.domain_conditioning == "bias":
            self.domain_bias = nn.Embedding(self.num_domains, 1)
            nn.init.zeros_(self.domain_bias.weight)
        else:
            self.domain_bias = None

        if self.domain_conditioning == "film":
            self.domain_film = nn.Embedding(self.num_domains, encoder_hid * 2)
            nn.init.zeros_(self.domain_film.weight)
        else:
            self.domain_film = None

        self.head_aux = nn.Linear(gru_hid, 1)
        nn.init.xavier_uniform_(self.head_aux.weight)
        nn.init.constant_(self.head_aux.bias, -1.0)

    def forward(
        self,
        chunks: torch.Tensor,
        h0: torch.Tensor | None = None,
        domain_ids: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        b, t, c, l = chunks.shape
        x = chunks.reshape(b * t, c, l)
        feat = self.encoder(x).reshape(b, t, -1)   # (B, T, encoder_hid)
        if self.domain_film is not None and domain_ids is not None:
            domain_ids = domain_ids.to(feat.device).long().clamp(0, self.num_domains - 1)
            gamma_beta = self.domain_film(domain_ids).unsqueeze(1)
            gamma, beta = gamma_beta.chunk(2, dim=-1)
            feat = feat * (1.0 + gamma) + beta

        # Delta: feat[t] - feat[t-1]，首包 delta=0
        delta = torch.zeros_like(feat)
        delta[:, 1:] = feat[:, 1:] - feat[:, :-1]  # (B, T, encoder_hid)

        # Delta normalization keeps the delta branch on the same scale as feat.
        # feat 和 delta 的关系：若 feat ~ N(0, σ²)，则 delta ~ N(0, 2σ²)
        # 除以 sqrt(2) 使 delta 的方差与 feat 一致，稳定 GRU 输入分布
        delta = delta / math.sqrt(2)

        # 归一化位置编码
        pos = torch.arange(t, device=feat.device, dtype=torch.float32) / self.max_chunks
        pos = pos.unsqueeze(0).unsqueeze(-1).expand(b, t, 1)

        # GRU 输入
        gru_in = torch.cat([feat, delta, pos], dim=-1)   # (B, T, 2*encoder_hid+1)

        out, h_n = self.gru(gru_in, h0)
        logits_p   = self.head_p(out).squeeze(-1)
        if self.domain_bias is not None and domain_ids is not None:
            domain_ids = domain_ids.to(feat.device).long().clamp(0, self.num_domains - 1)
            logits_p = logits_p + self.domain_bias(domain_ids).squeeze(-1).unsqueeze(1)
        logits_aux = self.head_aux(out).squeeze(-1)
        return logits_p, logits_aux, h_n

    @torch.inference_mode()
    def forward_streaming_packet(
        self,
        packet: torch.Tensor,
        h_prev: torch.Tensor | None = None,
        packet_idx: int = 0,
        prev_feat: torch.Tensor | None = None,
        domain_id: int | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        单包流式推理

        packet:     (3, L) 或 (1, 3, L)
        h_prev:     GRU 隐状态，首包传 None
        packet_idx: 当前包序号（0-based）
        prev_feat:  上一包的 encoder 输出，首包传 None
        返回:       (logit, h_new, feat)
                    feat 作为下一包的 prev_feat
        """
        if packet.dim() == 2:
            packet = packet.unsqueeze(0)   # (1, 3, L)

        feat = self.encoder(packet)        # (1, encoder_hid)
        if self.domain_film is not None and domain_id is not None:
            domain_id_tensor = torch.tensor(
                [domain_id],
                device=feat.device,
                dtype=torch.long,
            ).clamp(0, self.num_domains - 1)
            gamma_beta = self.domain_film(domain_id_tensor)
            gamma, beta = gamma_beta.chunk(2, dim=-1)
            feat = feat * (1.0 + gamma) + beta

        # Delta
        if prev_feat is None:
            delta = torch.zeros_like(feat)
        else:
            # Keep cached state on the current inference device.
            delta = feat - prev_feat.to(feat.device)   # (1, encoder_hid)

        # Match the delta normalization used in the batched forward path.
        delta = delta / math.sqrt(2)

        # 位置编码
        pos = torch.tensor(
            [[[packet_idx / self.max_chunks]]],
            device=feat.device, dtype=torch.float32,
        )                                  # (1, 1, 1)

        gru_in = torch.cat(
            [feat.unsqueeze(1), delta.unsqueeze(1), pos], dim=-1
        )                                  # (1, 1, 2*encoder_hid+1)

        out, h_new = self.gru(gru_in, h_prev)
        logit = self.head_p(out[:, -1, :]).squeeze(-1).squeeze(0)
        if self.domain_bias is not None and domain_id is not None:
            did = torch.tensor(
                [domain_id],
                device=feat.device,
                dtype=torch.long,
            ).clamp(0, self.num_domains - 1)
            logit = logit + self.domain_bias(did).squeeze(0).squeeze(-1)
        return logit, h_new, feat
