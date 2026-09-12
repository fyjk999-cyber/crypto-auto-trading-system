"""Multi-exchange price and liquidity intelligence. Recommendations only."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class ExchangeQuote:
    exchange: str
    symbol: str
    mid_price: Decimal
    spread_bps: Decimal
    depth: Decimal
    status: str = "HEALTHY"


@dataclass
class ExecutionRecommendation:
    symbol: str
    recommended_exchange: str
    best_mid_price: Decimal
    best_spread_bps: Decimal
    reason: str


class PriceAggregator:
    def aggregate(self, quotes: list[ExchangeQuote]) -> ExecutionRecommendation:
        healthy = [q for q in quotes if q.status == "HEALTHY"]
        if not healthy:
            return ExecutionRecommendation(
                "", "NONE", Decimal("0"), Decimal("0"), "NO_HEALTHY_PROVIDER"
            )
        best = min(healthy, key=lambda q: q.spread_bps)
        return ExecutionRecommendation(
            symbol=best.symbol,
            recommended_exchange=best.exchange,
            best_mid_price=best.mid_price,
            best_spread_bps=best.spread_bps,
            reason=f"BEST_SPREAD_{best.exchange}",
        )
