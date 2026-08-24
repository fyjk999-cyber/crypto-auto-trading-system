"""OKX adapter: execution provider.

Signs requests with API key/secret/passphrase when configured. OKX DEMO
requests set the x-simulated-trading header. LIVE is disabled by default.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from crypto_trader.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from crypto_trader.domain.errors import (
    AuthenticationError,
    ExchangeUnavailable,
    InvalidOrder,
    OrderNotFound,
    OrderRejected,
    RateLimited,
    TemporaryNetworkError,
)
from crypto_trader.domain.models import Balance, ExchangeEvent, Fill, Order, Position
from crypto_trader.domain.money import D, format_decimal
from crypto_trader.exchange.base import ExchangeAdapter


class OKXAdapter(ExchangeAdapter):
    name = "OKX"

    def __init__(
        self,
        *,
        base_url: str = "https://www.okx.com",
        api_key: str | None = None,
        api_secret: str | None = None,
        api_passphrase: str | None = None,
        demo: bool = True,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.demo = demo
        self._client = client or httpx.AsyncClient(base_url=self.base_url, timeout=10.0)
        self._owns_client = client is None
        self.connected = False
        self._handlers: dict[str, Callable[[ExchangeEvent], Awaitable[None]]] = {}
        self._sub_counter = 0

    async def connect(self) -> None:
        if self._owns_client and self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False
        if self._owns_client:
            await self._client.aclose()

    def _headers(self, method: str, path: str, body: str = "") -> dict:
        headers = {"Content-Type": "application/json"}
        if self.demo:
            headers["x-simulated-trading"] = "1"
        if self.api_key:
            timestamp = str(int(time.time() * 1000))
            message = f"{timestamp}{method}{path}{body}"
            signature = base64.b64encode(
                hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256).digest()
            ).decode()
            headers.update(
                {
                    "OK-ACCESS-KEY": self.api_key,
                    "OK-ACCESS-SIGN": signature,
                    "OK-ACCESS-TIMESTAMP": timestamp,
                    "OK-ACCESS-PASSPHRASE": self.api_passphrase or "",
                }
            )
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: dict | None = None,
        signed: bool = False,
    ):
        if signed and not (self.api_key and self.api_secret and self.api_passphrase):
            raise AuthenticationError("OKX credentials are not configured")
        if not self.connected:
            await self.connect()
        body_str = json.dumps(body) if body is not None else ""
        for attempt in range(3):
            try:
                response = await self._client.request(
                    method,
                    path,
                    params=params,
                    content=body_str or None,
                    headers=self._headers(method, path, body_str),
                )
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise ExchangeUnavailable(f"OKX transport error: {exc}") from exc
                await __import__("asyncio").sleep(0.2 * (attempt + 1))
                continue
            if response.status_code == 200:
                return response.json()
            if response.status_code == 429:
                raise RateLimited("OKX rate limited")
            if response.status_code in (401, 403):
                raise AuthenticationError("OKX authentication failed")
            if response.status_code >= 500:
                raise ExchangeUnavailable(f"OKX 5xx {response.status_code}")
            try:
                payload = response.json()
                code = str(payload.get("code", ""))
                msg = str(payload.get("msg", ""))
            except Exception:
                code, msg = "", response.text
            if code in ("51000", "51001", "51002"):
                raise InvalidOrder(f"OKX invalid order {code}: {msg}")
            if code == "51603":
                raise OrderNotFound(f"OKX order not found: {msg}")
            if code in ("1", "30014", "50004", "50005"):
                raise TemporaryNetworkError(f"OKX transient {code}: {msg}")
            raise OrderRejected(f"OKX rejected {code}: {msg}")
        raise ExchangeUnavailable("OKX request failed after retries")

    async def get_exchange_info(self, symbol: str | None = None):
        return []

    async def get_balances(self):
        data = await self._request("GET", "/api/v5/account/balance", signed=True)
        balances = []
        for detail in data.get("data", []):
            for raw in detail.get("details", []):
                balances.append(
                    Balance(
                        currency=raw.get("ccy", "USDT"),
                        total=D(raw.get("cashBal", "0")),
                        available=D(raw.get("availBal", "0")),
                        frozen=D(raw.get("frozenBal", "0")),
                    )
                )
        return balances

    async def get_positions(self):
        data = await self._request("GET", "/api/v5/account/positions", signed=True)
        return [self._normalize_position(raw) for raw in data.get("data", [])]

    def _normalize_position(self, raw: dict) -> Position:
        return Position(
            symbol=raw.get("instId", ""),
            base_asset=raw.get("ccy", ""),
            quote_asset="USDT",
            quantity=D(raw.get("pos", "0")),
            avg_entry_price=D(raw.get("avgPx", "0")),
            cost_basis=Decimal("0"),
            realized_pnl=D(raw.get("realizedPnl", "0")),
            updated_at=datetime.now(UTC),
        )

    async def get_orderbook(self, symbol: str, limit: int = 100):
        data = await self._request(
            "GET", "/api/v5/market/books", params={"instId": symbol, "sz": limit}
        )
        return data

    async def get_ticker(self, symbol: str):
        data = await self._request("GET", "/api/v5/market/ticker", params={"instId": symbol})
        if not data.get("data"):
            raise OrderNotFound(symbol)
        raw = data["data"][0]
        return {
            "symbol": raw["instId"],
            "bid": format_decimal(D(raw.get("bidPx", "0"))),
            "ask": format_decimal(D(raw.get("askPx", "0"))),
            "mark": format_decimal(D(raw.get("markPx", "0"))),
        }

    async def submit_order(self, order: Order):
        from crypto_trader.exchange.symbol_mapper import SymbolMapper

        inst_id = SymbolMapper().to_okx(order.symbol)
        body = {
            "instId": inst_id,
            "tdMode": "cross",
            "side": "buy" if order.side == OrderSide.BUY else "sell",
            "ordType": "limit" if order.order_type == OrderType.LIMIT else "market",
            "sz": format_decimal(order.quantity),
        }
        if order.order_type == OrderType.LIMIT and order.price is not None:
            body["px"] = format_decimal(order.price)
        data = await self._request("POST", "/api/v5/trade/order", body=body, signed=True)
        if not data.get("data"):
            raise OrderRejected("OKX submit_order returned no data")
        return self.normalize_order(data["data"][0], order)

    async def cancel_order(self, symbol: str, exchange_order_id: str):
        from crypto_trader.exchange.symbol_mapper import SymbolMapper

        inst_id = SymbolMapper().to_okx(symbol)
        data = await self._request(
            "POST",
            "/api/v5/trade/cancel-order",
            body={"instId": inst_id, "ordId": exchange_order_id},
            signed=True,
        )
        if not data.get("data"):
            raise OrderNotFound(exchange_order_id)
        return data

    async def get_order(self, symbol: str, exchange_order_id: str):
        from crypto_trader.exchange.symbol_mapper import SymbolMapper

        inst_id = SymbolMapper().to_okx(symbol)
        data = await self._request(
            "GET",
            "/api/v5/trade/order",
            params={"instId": inst_id, "ordId": exchange_order_id},
            signed=True,
        )
        if not data.get("data"):
            raise OrderNotFound(exchange_order_id)
        return self.normalize_order(data["data"][0])

    def normalize_symbol(self, raw: object) -> str:
        from crypto_trader.exchange.symbol_mapper import SymbolMapper

        return SymbolMapper().to_canonical(str(raw))

    def normalize_order(self, raw: dict, fallback: Order | None = None) -> Order:
        from crypto_trader.exchange.symbol_mapper import SymbolMapper

        status_map = {
            "live": OrderStatus.OPEN,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "filled": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
        }
        fallback = fallback or Order(
            internal_order_id="unknown",
            client_order_id=str(raw.get("clOrdId", "unknown")),
            symbol=SymbolMapper().to_canonical(str(raw.get("instId", ""))),
            side=OrderSide(str(raw.get("side", "buy")).upper()),
            order_type=OrderType(str(raw.get("ordType", "limit")).upper()),
            time_in_force=TimeInForce.GTC,
            quantity=D(raw.get("sz", "0")),
            filled_quantity=D(raw.get("accFillSz", "0")),
            status=status_map.get(str(raw.get("state", "live")), OrderStatus.UNKNOWN),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        return Order(
            internal_order_id=fallback.internal_order_id,
            client_order_id=str(raw.get("clOrdId", fallback.client_order_id)),
            exchange_order_id=str(raw.get("ordId", fallback.exchange_order_id)),
            symbol=fallback.symbol,
            side=OrderSide(str(raw.get("side", fallback.side.value)).upper()),
            order_type=OrderType(str(raw.get("ordType", fallback.order_type.value)).upper()),
            time_in_force=TimeInForce.GTC,
            price=D(raw.get("px", "0")) if raw.get("px") else fallback.price,
            quantity=D(raw.get("sz", fallback.quantity)),
            filled_quantity=D(raw.get("accFillSz", fallback.filled_quantity)),
            status=status_map.get(str(raw.get("state", "live")), fallback.status),
            trading_mode=fallback.trading_mode,
            strategy_id=fallback.strategy_id,
            run_id=fallback.run_id,
            created_at=fallback.created_at,
            updated_at=datetime.now(UTC),
        )

    def normalize_fill(self, raw: dict) -> Fill:
        from crypto_trader.exchange.symbol_mapper import SymbolMapper

        return Fill(
            fill_id=str(raw.get("tradeId", raw.get("billId", "unknown"))),
            trade_id=str(raw.get("tradeId", raw.get("billId", None))),
            order_id=str(raw.get("ordId", "")),
            client_order_id=raw.get("clOrdId"),
            exchange_order_id=str(raw.get("ordId", "")),
            symbol=SymbolMapper().to_canonical(str(raw.get("instId", ""))),
            side=OrderSide(str(raw.get("side", "buy")).upper()),
            price=D(raw.get("fillPx", raw.get("fillPx", "0"))),
            quantity=D(raw.get("fillSz", "0")),
            fee=D(raw.get("fee", "0")),
            fee_currency=raw.get("feeCcy"),
            timestamp=datetime.fromtimestamp(int(raw.get("ts", time.time())) / 1000.0, tz=UTC),
            payload={"raw_type": "okx_fill"},
        )

    async def subscribe_market_data(self, symbol: str, handler):
        return ""

    async def subscribe_order_updates(self, handler):
        self._sub_counter += 1
        sub_id = f"okx_order_{self._sub_counter}"
        self._handlers[sub_id] = handler
        return sub_id

    async def subscribe_account_updates(self, handler):
        self._sub_counter += 1
        sub_id = f"okx_account_{self._sub_counter}"
        self._handlers[sub_id] = handler
        return sub_id
