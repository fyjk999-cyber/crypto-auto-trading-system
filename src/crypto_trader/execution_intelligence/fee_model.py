"""Transaction cost model with full breakdown."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class FeeBreakdown:
    open_fee: Decimal
    close_fee: Decimal
    funding_cost: Decimal
    slippage_cost: Decimal
    market_impact_cost: Decimal
    total_cost: Decimal
    cost_ratio: Decimal


class FeeModel:
    def calculate(
        self,
        *,
        order_size: Decimal,
        price: Decimal,
        leverage: Decimal,
        maker_fee_rate: Decimal,
        taker_fee_rate: Decimal,
        funding_rate: Decimal,
        holding_hours: Decimal,
        slippage_bps: Decimal,
        market_impact_bps: Decimal,
        expected_gross_pnl: Decimal,
    ) -> FeeBreakdown:
        notional = D(order_size) * D(price)
        open_fee = notional * D(taker_fee_rate)
        close_fee = notional * D(maker_fee_rate)
        funding_cost = notional * D(funding_rate) * D(leverage) * D(holding_hours) / D("8")
        slippage_cost = notional * D(slippage_bps) / D("10000")
        market_impact_cost = notional * D(market_impact_bps) / D("10000")
        total = open_fee + close_fee + funding_cost + slippage_cost + market_impact_cost
        ratio = total / abs(D(expected_gross_pnl)) if D(expected_gross_pnl) != 0 else D("999")
        return FeeBreakdown(
            open_fee=open_fee,
            close_fee=close_fee,
            funding_cost=funding_cost,
            slippage_cost=slippage_cost,
            market_impact_cost=market_impact_cost,
            total_cost=total,
            cost_ratio=ratio,
        )

    def profitability_decision(self, cost_ratio: Decimal) -> str:
        if cost_ratio < D("0.20"):
            return "NORMAL"
        if cost_ratio <= D("0.40"):
            return "REDUCE_POSITION"
        return "REJECT"
