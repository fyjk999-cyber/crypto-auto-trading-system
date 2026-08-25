"""Trading personality evolution. Cannot modify risk hard limits."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class TradingStyle:
    style_name: str
    risk_appetite: str
    holding_period: str
    strategy_preference: str
    leverage_preference: Decimal
    trade_frequency: str
    confidence_threshold: Decimal


class TradingStyleEngine:
    def evolve(
        self, *, regime: str, recent_win_rate: Decimal, volatility_pct: Decimal
    ) -> TradingStyle:
        if regime in ("TREND_BEAR", "PANIC"):
            return TradingStyle(
                "Conservative Trend Trader",
                "LOW",
                "SHORT",
                "mean_reversion",
                Decimal("1"),
                "LOW",
                Decimal("0.75"),
            )
        if regime == "TREND_BULL":
            return TradingStyle(
                "Aggressive Momentum Trader",
                "MEDIUM",
                "LONG",
                "trend_following",
                Decimal("3"),
                "MEDIUM",
                Decimal("0.60"),
            )
        return TradingStyle(
            "Balanced Trader", "MEDIUM", "MEDIUM", "mix", Decimal("2"), "MEDIUM", Decimal("0.65")
        )
