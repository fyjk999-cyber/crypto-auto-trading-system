"""Order flow imbalance and market impact."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class OrderFlowResult:
    imbalance: Decimal
    aggressive_buy: Decimal
    aggressive_sell: Decimal
    large_order_activity: Decimal


class OrderFlowAnalyzer:
    def analyze(
        self, *, bid_volume, ask_volume, buy_trades, sell_trades, large_trades: Decimal
    ) -> OrderFlowResult:
        bid = D(bid_volume)
        ask = D(ask_volume)
        total = bid + ask
        imbalance = (bid - ask) / total * D("100") if total > 0 else D("0")
        return OrderFlowResult(
            imbalance=imbalance,
            aggressive_buy=D(buy_trades),
            aggressive_sell=D(sell_trades),
            large_order_activity=D(large_trades),
        )


class MarketImpactModel:
    def recommended_order_size(self, *, orderbook_depth, max_impact_bps: str = "5") -> Decimal:
        depth = D(orderbook_depth)
        if depth <= 0:
            return D("0")
        return depth * D(max_impact_bps) / D("10000")
