"""StrategyPlugin contract. Strategy logic must never enter the core."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from crypto_trader.domain.models import Account, Position, SignalIntent
from crypto_trader.market_data.orderbook import OrderBook


@dataclass
class StrategyContext:
    symbol: str
    book: OrderBook
    account: Account
    positions: dict[str, Position]
    clock_time: datetime
    run_id: str | None = None


class StrategyPlugin(ABC):
    name: str = "base"
    version: str = "0.1.0"

    @abstractmethod
    async def on_market_data(self, ctx: StrategyContext) -> list[SignalIntent]:
        """Return zero or more intents. Must not call risk, execution, exchange, or ledger."""
        raise NotImplementedError
