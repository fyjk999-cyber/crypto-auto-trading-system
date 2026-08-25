"""Quant + DeepSeek fusion."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FusedDecision:
    symbol: str
    decision: str
    confidence: float
    fusion_type: str  # AGREEMENT | CONFLICT | QUANT_ONLY


def fuse_quant_deepseek(
    *,
    symbol: str,
    quant_direction: str,
    quant_confidence: float,
    deepseek_direction: str | None,
    deepseek_confidence: float | None,
) -> FusedDecision:
    if deepseek_direction is None:
        return FusedDecision(symbol, quant_direction, quant_confidence, "QUANT_ONLY")
    if deepseek_direction == quant_direction:
        conf = min(0.95, quant_confidence * 0.6 + (deepseek_confidence or 0.0) * 0.4)
        return FusedDecision(symbol, quant_direction, round(conf, 3), "AGREEMENT")
    return FusedDecision(symbol, "NO_TRADE", 0.0, "CONFLICT")
