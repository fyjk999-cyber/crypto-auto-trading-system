"""Unified ExchangeAdapter contract.

Every exchange-specific JSON/error/transport detail stays behind an adapter.
Core only ever sees domain objects and normalized errors.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Awaitable, Callable
from uuid import uuid4

from crypto_trader.domain.models import Balance, ExchangeEvent, Fill, Instrument, Order, Position
from crypto_trader.domain.enums import ExchangeEventType


class ExchangeAdapter(ABC):
    name: str = "UNKNOWN"

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def get_exchange_info(self, symbol: str | None = None) -> list[Instrument]: ...

    @abstractmethod
    async def get_balances(self) -> list[Balance]: ...

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abstractmethod
    async def get_orderbook(self, symbol: str, limit: int = 100) -> object: ...

    @abstractmethod
    async def get_ticker(self, symbol: str) -> dict: ...

    @abstractmethod
    async def submit_order(self, order: Order) -> object: ...

    @abstractmethod
    async def cancel_order(self, symbol: str, exchange_order_id: str) -> object: ...

    @abstractmethod
    async def get_order(self, symbol: str, exchange_order_id: str) -> object: ...

    @abstractmethod
    async def subscribe_market_data(self, symbol: str, handler: Callable[[ExchangeEvent], Awaitable[None]]) -> str: ...

    @abstractmethod
    async def subscribe_order_updates(self, handler: Callable[[ExchangeEvent], Awaitable[None]]) -> str: ...

    @abstractmethod
    async def subscribe_account_updates(self, handler: Callable[[ExchangeEvent], Awaitable[None]]) -> str: ...

    @abstractmethod
    def normalize_symbol(self, raw: object) -> str: ...

    @abstractmethod
    def normalize_order(self, raw: dict) -> Order | dict: ...

    @abstractmethod
    def normalize_fill(self, raw: dict) -> Fill: ...


def make_exchange_event(event_type: ExchangeEventType, symbol: str | None = None, payload: dict | None = None) -> ExchangeEvent:
    return ExchangeEvent(
        event_id=f"exevt_{uuid4().hex}",
        event_type=event_type,
        symbol=symbol,
        timestamp=datetime.now(timezone.utc),
        payload=payload or {},
    )
