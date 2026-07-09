"""Backward-compatible import path for older experiment scripts."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from model_impl import CausalStreamingPPicker

CausalStreamingPPickerV3 = CausalStreamingPPicker

__all__ = ["CausalStreamingPPicker", "CausalStreamingPPickerV3"]
