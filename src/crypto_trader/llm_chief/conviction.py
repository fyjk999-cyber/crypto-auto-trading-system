"""Conviction engine: calibrates LLM confidence into conviction score."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class ConvictionResult:
    conviction_score: float
    approved_leverage: Decimal
    reason_codes: list[str]


class ConvictionEngine:
    def evaluate(
        self,
        *,
        llm_confidence: float,
        calibrated_accuracy: float,
        quant_agreement: float,
        strategy_sharpe: Decimal,
        pattern_win_rate: Decimal,
        sample_confidence: str,
        liquidity_score: Decimal,
        cost_ratio: Decimal,
        requested_leverage: Decimal,
        max_leverage: Decimal,
    ) -> ConvictionResult:
        score = (
            float(llm_confidence) * 0.25
            + float(calibrated_accuracy) * 0.20
            + float(quant_agreement) * 0.15
            + float(max(D("0"), min(D("1"), strategy_sharpe)) / D("2")) * 0.15
            + float(pattern_win_rate) * 0.15
            + float(liquidity_score / D("100")) * 0.05
            - float(cost_ratio) * 0.10
        )
        sample_factor = {
            "EXPERIMENTAL": 0.5,
            "LOW": 0.7,
            "MEDIUM": 0.9,
            "HIGH": 1.0,
            "MATURE": 1.0,
        }.get(sample_confidence, 0.6)
        score *= sample_factor
        score = max(0.0, min(1.0, score))
        approved = D(str(requested_leverage)) * D(str(score))
        approved = max(D("1"), min(D(str(max_leverage)), approved))
        reasons = []
        if score < 0.3:
            reasons.append("LOW_CONVICTION")
        if cost_ratio > D("0.25"):
            reasons.append("HIGH_COST")
        return ConvictionResult(round(score, 3), approved, reasons)
