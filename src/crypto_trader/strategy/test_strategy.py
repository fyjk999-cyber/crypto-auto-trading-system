"""TestStrategy: emits exactly one deterministic BUY intent.

Used only to verify Strategy -> SignalIntent -> Risk -> Execution -> Fill ->
Ledger. It contains no alpha/indicator logic and never enters core modules.
"""
from __future__ import annotations

from datetime import timedelta

from crypto_trader.domain.enums import OrderSide, OrderType, TimeInForce
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import SignalIntent
from crypto_trader.domain.money import D
from crypto_trader.strategy.base import StrategyContext, StrategyPlugin


class TestStrategy(StrategyPlugin):
    name = "test"
    version = "0.1.0"
    __test__ = False
    symbol = "BTCUSDT"

    def __init__(self, quantity: str = "0.1", limit_price: str | None = None,
                 signal_id: str | None = None) -> None:
        self.quantity = D(quantity)
        self.limit_price = D(limit_price) if limit_price else None
        self.signal_id = signal_id or new_id("signal")
        self.sent = False

    async def on_market_data(self, ctx: StrategyContext) -> list[SignalIntent]:
        if self.sent:
            return []
        self.sent = True
        price = self.limit_price
        if price is None:
            mid = ctx.book.mid_price()
            if mid is None:
                return []
            price = mid * D("1.01")
        return [
            SignalIntent(
                signal_id=self.signal_id,
                strategy_id=self.name,
                symbol=self.symbol,
                side=OrderSide.BUY,
                quantity=self.quantity,
                limit_price=price,
                order_type=OrderType.LIMIT,
                time_in_force=TimeInForce.GTC,
                expires_at=ctx.clock_time + timedelta(minutes=5),
                reason="deterministic E2E chain test",
                run_id=ctx.run_id,
            )
        ]
