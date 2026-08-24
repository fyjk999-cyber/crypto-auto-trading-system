"""DummyStrategy: never emits an intent. Exists to prove plugin boundaries."""
from __future__ import annotations

from crypto_trader.domain.models import SignalIntent
from crypto_trader.strategy.base import StrategyContext, StrategyPlugin


class DummyStrategy(StrategyPlugin):
    name = "dummy"
    version = "0.1.0"
    symbol = "BTCUSDT"

    async def on_market_data(self, ctx: StrategyContext) -> list[SignalIntent]:
        return []
