"""Binance adapter (testnet-capable).

All Binance-specific JSON, error codes, symbols, and transport stay here.
Core receives only domain objects and normalized errors.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from websockets.asyncio.client import connect as ws_connect

from crypto_trader.domain.enums import (
    ExchangeEventType,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from crypto_trader.domain.errors import (
    AuthenticationError,
    ExchangeUnavailable,
    InsufficientBalance,
    InvalidOrder,
    OrderNotFound,
    OrderRejected,
    RateLimited,
    TemporaryNetworkError,
    UnknownExecutionState,
)
from crypto_trader.domain.models import Balance, ExchangeEvent, Fill, Instrument, Order, Position
from crypto_trader.domain.money import D, format_decimal
from crypto_trader.exchange.base import ExchangeAdapter, make_exchange_event
from crypto_trader.market_data.orderbook import OrderBook


def _dec(raw: object) -> Decimal:
    if isinstance(raw, str):
        return D(raw)
    return D(str(raw))


class BinanceAdapter(ExchangeAdapter):
    name = "BINANCE"

    def __init__(
        self,
        *,
        base_url: str = "https://testnet.binance.vision",
        ws_base_url: str = "wss://testnet.binance.vision",
        api_key: str | None = None,
        api_secret: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.ws_base_url = ws_base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self._client = client or httpx.AsyncClient(base_url=self.base_url, timeout=10.0)
        self._owns_client = client is None
        self.connected = False
        self.last_balance_update: datetime | None = None
        self._subscriptions: dict[str, Callable[[ExchangeEvent], Awaitable[None]]] = {}

    async def connect(self) -> None:
        if self._owns_client and self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": self.api_key} if self.api_key else {}

    def _signed_params(self, params: dict) -> dict:
        params = dict(params)
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = 10000
        query = "&".join(f"{k}={params[k]}" for k in sorted(params))
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = signature
        return params

    async def _request(
        self, method: str, path: str, params: dict | None = None, signed: bool = False
    ):
        if not self.connected:
            await self.connect()
        if signed:
            if not self.api_key or not self.api_secret:
                raise AuthenticationError("Binance API credentials are not configured")
            params = self._signed_params(params or {})
        for attempt in range(3):
            try:
                response = await self._client.request(
                    method, path, params=params, headers=self._headers()
                )
            except httpx.TimeoutException as exc:
                if attempt == 2:
                    raise TemporaryNetworkError("Binance request timed out") from exc
                await asyncio.sleep(0.1 * (attempt + 1))
                continue
            except httpx.TransportError as exc:
                if attempt == 2:
                    raise ExchangeUnavailable(f"Binance transport error: {exc}") from exc
                await asyncio.sleep(0.2 * (attempt + 1))
                continue
            self._raise_for_binance_error(response)
            return response.json()
        raise ExchangeUnavailable("Binance request failed after retries")

    def _raise_for_binance_error(self, response: httpx.Response) -> None:
        if response.status_code == 200:
            return
        if response.status_code == 429 or response.status_code == 418:
            raise RateLimited(f"Binance rate limited: {response.text}")
        try:
            payload = response.json()
            code = int(payload.get("code", 0))
            msg = str(payload.get("msg", ""))
        except Exception:
            code = 0
            msg = response.text
        if response.status_code >= 500:
            raise ExchangeUnavailable(f"Binance 5xx ({response.status_code}): {msg}")
        if code in (-2015, -2014):
            raise AuthenticationError(f"Binance auth error {code}: {msg}")
        if code in (-2010, -1013, -2011):
            raise InvalidOrder(f"Binance invalid order {code}: {msg}")
        if code == -2013:
            raise OrderNotFound(f"Binance order not found: {msg}")
        if code == -2019:
            raise InsufficientBalance(f"Binance insufficient balance: {msg}")
        if code in (-2018,):
            raise InsufficientBalance(f"Binance insufficient balance: {msg}")
        if code in (-1100,):
            raise InvalidOrder(f"Binance illegal characters: {msg}")
        if code in (-1001, -1002, -1003, -1007, -1008):
            raise TemporaryNetworkError(f"Binance transient error {code}: {msg}")
        if code in (-1000,):
            raise ExchangeUnavailable(f"Binance error {code}: {msg}")
        if response.status_code in (400, 401, 403, 404):
            raise OrderRejected(f"Binance rejected request ({response.status_code}, {code}): {msg}")
        raise UnknownExecutionState(
            f"Binance unexpected response {response.status_code} code={code}: {msg}"
        )

    async def get_exchange_info(self, symbol: str | None = None) -> list[Instrument]:
        data = await self._request("GET", "/api/v3/exchangeInfo")
        instruments: list[Instrument] = []
        for raw in data.get("symbols", []):
            instrument = self._normalize_symbol_info(raw)
            if symbol is None or instrument.symbol == symbol:
                instruments.append(instrument)
        return instruments

    def _normalize_symbol_info(self, raw: dict) -> Instrument:
        symbol = raw["symbol"]
        filters = {f["filterType"]: f for f in raw.get("filters", [])}
        price_filter = filters.get("PRICE_FILTER", {})
        lot_filter = filters.get("LOT_SIZE", {})
        notional_filter = filters.get("NOTIONAL", {}) or filters.get("MIN_NOTIONAL", {})
        return Instrument(
            symbol=symbol,
            base_asset=raw.get("baseAsset", symbol),
            quote_asset=raw.get("quoteAsset", symbol),
            status=str(raw.get("status", "TRADING")),
            tick_size=_dec(price_filter.get("tickSize", "0.00000001")),
            step_size=_dec(lot_filter.get("stepSize", "0.00000001")),
            min_qty=_dec(lot_filter.get("minQty", "0.00000001")),
            min_notional=_dec(notional_filter.get("minNotional", "0.00000001")),
            price_precision=int(price_filter.get("pricePrecision", 8)),
            quantity_precision=int(lot_filter.get("quantityPrecision", 8)),
            exchange=self.name,
        )

    async def get_balances(self) -> list[Balance]:
        data = await self._request("GET", "/api/v3/account", signed=True)
        self.last_balance_update = datetime.now(UTC)
        return [self._normalize_balance(raw) for raw in data.get("balances", [])]

    def _normalize_balance(self, raw: dict) -> Balance:
        total = _dec(raw.get("free", "0")) + _dec(raw.get("locked", "0"))
        return Balance(
            currency=str(raw["asset"]),
            total=total,
            available=_dec(raw.get("free", "0")),
            frozen=_dec(raw.get("locked", "0")),
        )

    async def get_positions(self) -> list[Position]:
        # Spot Binance has no positions; positions are derived from ledger locally.
        return []

    async def get_orderbook(self, symbol: str, limit: int = 100) -> OrderBook:
        data = await self._request(
            "GET", "/api/v3/depth", params={"symbol": symbol, "limit": limit}
        )
        book = OrderBook(symbol=symbol, exchange=self.name)
        book.apply_snapshot(
            int(data.get("lastUpdateId", 0)),
            [(_dec(b[0]), _dec(b[1])) for b in data.get("bids", [])],
            [(_dec(a[0]), _dec(a[1])) for a in data.get("asks", [])],
        )
        return book

    async def get_ticker(self, symbol: str) -> dict:
        data = await self._request("GET", "/api/v3/ticker/bookTicker", params={"symbol": symbol})
        return {
            "symbol": data["symbol"],
            "bid": format_decimal(_dec(data["bidPrice"])),
            "ask": format_decimal(_dec(data["askPrice"])),
            "bid_quantity": format_decimal(_dec(data["bidQty"])),
            "ask_quantity": format_decimal(_dec(data["askQty"])),
        }

    async def submit_order(self, order: Order) -> Order:
        params: dict = {
            "symbol": order.symbol,
            "side": order.side.value,
            "type": order.order_type.value,
            "newClientOrderId": order.client_order_id,
        }
        if order.order_type == OrderType.LIMIT:
            if order.price is None:
                raise InvalidOrder("LIMIT order requires price")
            params["price"] = format_decimal(order.price)
            params["timeInForce"] = order.time_in_force.value
        if order.quantity > 0:
            params["quantity"] = format_decimal(order.quantity)
        raw = await self._request("POST", "/api/v3/order", params=params, signed=True)
        return self.normalize_order(raw, order)

    async def cancel_order(self, symbol: str, exchange_order_id: str) -> Order:
        raw = await self._request(
            "DELETE",
            "/api/v3/order",
            params={"symbol": symbol, "origClientOrderId": exchange_order_id},
            signed=True,
        )
        return self.normalize_order(raw)

    async def get_order(self, symbol: str, exchange_order_id: str) -> Order:
        raw = await self._request(
            "GET",
            "/api/v3/order",
            params={"symbol": symbol, "origClientOrderId": exchange_order_id},
            signed=True,
        )
        return self.normalize_order(raw)

    def normalize_symbol(self, raw: object) -> str:
        if isinstance(raw, str):
            return raw.upper()
        if isinstance(raw, dict):
            return str(raw["symbol"]).upper()
        raise InvalidOrder(f"cannot normalize Binance symbol from {type(raw).__name__}")

    def normalize_order(self, raw: dict, fallback: Order | None = None) -> Order:
        status_map = {
            "NEW": OrderStatus.ACKNOWLEDGED,
            "ACK": OrderStatus.ACKNOWLEDGED,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
            "FILLED": OrderStatus.FILLED,
            "CANCELED": OrderStatus.CANCELLED,
            "PENDING_CANCEL": OrderStatus.CANCEL_PENDING,
            "REJECTED": OrderStatus.REJECTED,
            "EXPIRED": OrderStatus.EXPIRED,
            "EXPIRED_IN_MATCH": OrderStatus.EXPIRED,
        }
        fallback = fallback or Order(
            internal_order_id="unknown",
            client_order_id=str(raw.get("clientOrderId") or "unknown"),
            symbol=str(raw.get("symbol", "")),
            side=OrderSide(str(raw.get("side", "BUY"))),
            order_type=OrderType(str(raw.get("type", "LIMIT"))),
            time_in_force=TimeInForce(str(raw.get("timeInForce", "GTC"))),
            price=_dec(raw.get("price", "0")) if raw.get("price") else None,
            quantity=_dec(raw.get("origQty", "0")),
            filled_quantity=_dec(raw.get("executedQty", "0")),
            status=status_map.get(str(raw.get("status", "NEW")), OrderStatus.UNKNOWN),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        return Order(
            internal_order_id=fallback.internal_order_id,
            client_order_id=str(raw.get("clientOrderId") or fallback.client_order_id),
            exchange_order_id=str(raw.get("orderId")),
            symbol=str(raw.get("symbol", fallback.symbol)),
            side=OrderSide(str(raw.get("side", fallback.side.value))),
            order_type=OrderType(str(raw.get("type", fallback.order_type.value))),
            time_in_force=TimeInForce(str(raw.get("timeInForce", fallback.time_in_force.value))),
            price=_dec(raw.get("price", "0")) if raw.get("price") else fallback.price,
            quantity=_dec(raw.get("origQty", fallback.quantity)),
            filled_quantity=_dec(raw.get("executedQty", fallback.filled_quantity)),
            avg_fill_price=_dec(raw.get("cummulativeQuoteQty", "0"))
            / _dec(raw.get("executedQty", "0"))
            if _dec(raw.get("executedQty", "0")) > 0
            else fallback.avg_fill_price,
            status=status_map.get(str(raw.get("status", "NEW")), fallback.status),
            trading_mode=fallback.trading_mode,
            strategy_id=fallback.strategy_id,
            run_id=fallback.run_id,
            created_at=fallback.created_at,
            updated_at=datetime.now(UTC),
            expires_at=fallback.expires_at,
            rejection_reason=str(raw.get("rejectReason", "")) or fallback.rejection_reason,
            last_event_id=fallback.last_event_id,
        )

    def normalize_fill(self, raw: dict) -> Fill:
        price = _dec(raw.get("price", raw.get("p", "0")))
        quantity = _dec(raw.get("qty", raw.get("q", raw.get("lastExecutedQty", "0"))))
        fee = _dec(raw.get("commission", raw.get("n", "0")))
        return Fill(
            fill_id=str(raw.get("tradeId", raw.get("t", "unknown"))),
            trade_id=str(raw.get("tradeId", raw.get("t", None))),
            order_id=str(raw.get("orderId", raw.get("i", "unknown"))),
            client_order_id=raw.get("clientOrderId", raw.get("c")),
            exchange_order_id=str(raw.get("orderId", raw.get("i", None))),
            symbol=str(raw.get("symbol", raw.get("s", ""))),
            side=OrderSide.BUY
            if str(raw.get("side", raw.get("S", "BUY"))) == "BUY"
            else OrderSide.SELL,
            price=price,
            quantity=quantity,
            fee=fee,
            fee_currency=raw.get("commissionAsset", None),
            timestamp=datetime.fromtimestamp(
                float(raw.get("time", raw.get("T", time.time()))) / 1000.0, tz=UTC
            ),
            payload={"raw_type": "binance_fill"},
        )

    async def subscribe_market_data(
        self, symbol: str, handler: Callable[[ExchangeEvent], Awaitable[None]]
    ) -> str:
        sub_id = f"binance_md_{symbol}_{id(handler)}"
        self._subscriptions[sub_id] = handler
        return sub_id

    async def subscribe_order_updates(
        self, handler: Callable[[ExchangeEvent], Awaitable[None]]
    ) -> str:
        sub_id = f"binance_order_{id(handler)}"
        self._subscriptions[sub_id] = handler
        return sub_id

    async def subscribe_account_updates(
        self, handler: Callable[[ExchangeEvent], Awaitable[None]]
    ) -> str:
        sub_id = f"binance_account_{id(handler)}"
        self._subscriptions[sub_id] = handler
        return sub_id

    async def dispatch_raw_event(self, raw: dict) -> None:
        """Parse one Binance stream event into a normalized ExchangeEvent and dispatch."""
        event_type = str(raw.get("e", ""))
        symbol = raw.get("s")
        if event_type == "executionReport":
            status = str(raw.get("X", ""))
            event = make_exchange_event(ExchangeEventType.ORDER_ACK, symbol, {"raw": raw})
            if status == "PARTIALLY_FILLED":
                event = make_exchange_event(
                    ExchangeEventType.ORDER_PARTIALLY_FILLED, symbol, {"raw": raw}
                )
            elif status == "FILLED":
                event = make_exchange_event(ExchangeEventType.ORDER_FILLED, symbol, {"raw": raw})
            elif status in ("CANCELED",):
                event = make_exchange_event(ExchangeEventType.ORDER_CANCELLED, symbol, {"raw": raw})
            elif status in ("REJECTED", "EXPIRED", "EXPIRED_IN_MATCH"):
                event = make_exchange_event(ExchangeEventType.ORDER_REJECTED, symbol, {"raw": raw})
        elif event_type == "depthUpdate":
            event = make_exchange_event(ExchangeEventType.MARKET_DELTA, symbol, {"raw": raw})
        elif event_type == "outboundAccountPosition":
            event = make_exchange_event(ExchangeEventType.BALANCE_UPDATE, None, {"raw": raw})
        else:
            event = make_exchange_event(ExchangeEventType.MARKET_SNAPSHOT, symbol, {"raw": raw})
        for handler in self._subscriptions.values():
            await handler(event)


class BinanceMarketStream:
    """WebSocket client for Binance market streams. Reconnect + resync policy.

    The normalized stream increments a local continuous sequence per symbol so
    the core MarketDataService detects any gap between processed messages.
    """

    def __init__(self, adapter: BinanceAdapter, reconnect_policy) -> None:
        self.adapter = adapter
        self.reconnect_policy = reconnect_policy
        self._task: asyncio.Task | None = None
        self._sequence: dict[str, int] = {}

    async def run(self, symbol: str, handler: Callable[[dict], Awaitable[None]]) -> None:
        stream = f"{symbol.lower()}@depth@100ms"
        uri = f"{self.adapter.ws_base_url}/ws/{stream}"
        while self.reconnect_policy.should_reconnect():
            try:
                async with ws_connect(uri) as websocket:
                    self.reconnect_policy.on_connected()
                    async for message in websocket:
                        raw = json.loads(message)
                        symbol_key = raw.get("s") or symbol
                        self._sequence[symbol_key] = self._sequence.get(symbol_key, 0) + 1
                        raw["_local_seq"] = self._sequence[symbol_key]
                        await handler(raw)
            except Exception as exc:
                self.reconnect_policy.on_disconnected()
                if self.reconnect_policy.exhausted():
                    raise ExchangeUnavailable(f"Binance market stream exhausted: {exc}") from exc
                await self.reconnect_policy.wait_backoff()

    def start(self, symbol: str, handler: Callable[[dict], Awaitable[None]]) -> asyncio.Task:
        self._task = asyncio.create_task(self.run(symbol, handler))
        return self._task

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
