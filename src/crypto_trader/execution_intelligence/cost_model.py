"""Transaction cost model: net pnl after fees, funding, slippage."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class NetPnL:
    gross_pnl: Decimal
    trading_fee: Decimal
    funding_cost: Decimal
    slippage: Decimal
    net_pnl: Decimal


class CostModel:
    def net_pnl(self, gross_pnl, trading_fee, funding_cost, slippage) -> NetPnL:
        gross = D(gross_pnl)
        fee = D(trading_fee)
        funding = D(funding_cost)
        slip = D(slippage)
        return NetPnL(
            gross_pnl=gross,
            trading_fee=fee,
            funding_cost=funding,
            slippage=slip,
            net_pnl=gross - fee - funding - slip,
        )
