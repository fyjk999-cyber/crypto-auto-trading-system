"""Liquidity assessment and execution planning. Advisory only."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class LiquidityAssessment:
    symbol: str
    liquidity_score: Decimal
    max_recommended_notional: Decimal
    estimated_slippage_bps: Decimal
    estimated_impact_bps: Decimal
    execution_difficulty: str
    data_quality: str
    reason_codes: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class ExecutionPlan:
    style: str
    slice_count: int
    slice_size: Decimal
    time_horizon: str
    price_tolerance: Decimal
    urgency: str
    cancel_conditions: list[str] = field(default_factory=list)
    reassessment_conditions: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)


class LiquidityAssessor:
    def assess(
        self,
        *,
        symbol: str,
        spread_bps: Decimal,
        depth: Decimal,
        volume_24h: Decimal,
        size: Decimal,
        freshness_seconds: float,
    ) -> LiquidityAssessment:
        reasons: list[str] = []
        size = D(size)
        depth = D(depth)
        if freshness_seconds > 5:
            reasons.append("STALE_BOOK")
            return LiquidityAssessment(
                symbol, D("0"), D("0"), D("999"), D("999"), "UNSAFE", "STALE", reasons
            )
        if depth <= 0:
            return LiquidityAssessment(
                symbol, D("0"), D("0"), D("999"), D("999"), "UNSAFE", "NO_DEPTH", reasons
            )
        size_depth = size / depth
        score = D("100") - D(spread_bps) * D("2") - size_depth * D("50")
        score = max(D("0"), min(D("100"), score))
        slip = D(spread_bps) / D("2") + size_depth * D("5")
        impact = size_depth * D("8")
        if score < D("50"):
            reasons.append("LOW_LIQUIDITY")
        difficulty = "EASY" if score >= 70 else "MODERATE" if score >= 40 else "HARD"
        max_notional = depth * D("0.05")
        return LiquidityAssessment(
            symbol, score, max_notional, slip, impact, difficulty, "FRESH", reasons
        )


class ExecutionPlanner:
    def plan(
        self,
        *,
        assessment: LiquidityAssessment,
        order_size: Decimal,
        spread_bps: Decimal,
        urgent: bool,
        thesis_invalidated: bool,
    ) -> ExecutionPlan:
        if assessment.data_quality == "STALE":
            return ExecutionPlan(
                "WAIT",
                0,
                D("0"),
                "0",
                D("0"),
                "LOW",
                ["STALE_BOOK"],
                ["REFRESH_BOOK"],
                ["STALE_DATA"],
            )
        if thesis_invalidated:
            return ExecutionPlan(
                "CANCEL_REASSESS",
                0,
                D("0"),
                "0",
                D("0"),
                "HIGH",
                ["THESIS_INVALID"],
                ["REASSESS_THESIS"],
                ["INVALIDATION"],
            )
        if urgent:
            return ExecutionPlan(
                "MARKET",
                1,
                D(order_size),
                "IMMEDIATE",
                D(spread_bps),
                "HIGH",
                ["SLIPPAGE_CAP"],
                [],
                ["URGENT"],
            )
        if D(order_size) > assessment.max_recommended_notional:
            slices = max(2, int(D(order_size) / max(assessment.max_recommended_notional, D("1"))))
            return ExecutionPlan(
                "TWAP",
                slices,
                D(order_size) / Decimal(slices),
                "1h",
                D(spread_bps),
                "LOW",
                ["SLIPPAGE_CAP"],
                ["RESLICE_ON_BOOK_CHANGE"],
                ["LARGE_SIZE"],
            )
        if D(spread_bps) > D("5"):
            return ExecutionPlan(
                "PASSIVE_LIMIT",
                1,
                D(order_size),
                "30m",
                D(spread_bps) / D("2"),
                "LOW",
                ["WIDE_SPREAD"],
                [],
                ["WIDE_SPREAD"],
            )
        return ExecutionPlan(
            "LIMIT", 1, D(order_size), "15m", D(spread_bps) / D("2"), "LOW", [], [], ["NORMAL"]
        )
