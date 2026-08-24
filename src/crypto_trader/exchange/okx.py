"""OKX adapter boundary.

Phase 1 intentionally provides only the adapter boundary and normalization
entry points. Binance-specific logic must never leak into core; when OKX is
implemented, all OKX-specific transport/auth/error mapping lives here.
"""

from __future__ import annotations

from crypto_trader.exchange.base import ExchangeAdapter


class OKXAdapter(ExchangeAdapter):
    name = "OKX"

    def __init__(self, **kwargs) -> None:
        self._config = kwargs
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def _not_implemented(self, method: str):
        raise NotImplementedError(f"OKX adapter {method} is a phase-1 boundary")

    async def get_exchange_info(self, symbol: str | None = None):
        return await self._not_implemented("get_exchange_info")

    async def get_balances(self):
        return await self._not_implemented("get_balances")

    async def get_positions(self):
        return await self._not_implemented("get_positions")

    async def get_orderbook(self, symbol: str, limit: int = 100):
        return await self._not_implemented("get_orderbook")

    async def get_ticker(self, symbol: str):
        return await self._not_implemented("get_ticker")

    async def submit_order(self, order):
        return await self._not_implemented("submit_order")

    async def cancel_order(self, symbol: str, exchange_order_id: str):
        return await self._not_implemented("cancel_order")

    async def get_order(self, symbol: str, exchange_order_id: str):
        return await self._not_implemented("get_order")

    async def subscribe_market_data(self, symbol: str, handler):
        return await self._not_implemented("subscribe_market_data")

    async def subscribe_order_updates(self, handler):
        return await self._not_implemented("subscribe_order_updates")

    async def subscribe_account_updates(self, handler):
        return await self._not_implemented("subscribe_account_updates")

    def normalize_symbol(self, raw: object) -> str:
        return str(raw)

    def normalize_order(self, raw: dict):
        raise NotImplementedError("OKX normalize_order is a phase-1 boundary")

    def normalize_fill(self, raw: dict):
        raise NotImplementedError("OKX normalize_fill is a phase-1 boundary")
