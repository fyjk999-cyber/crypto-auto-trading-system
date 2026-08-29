"""OKX adapter: execution provider.

Correct OKX REST authentication:
- ISO8601 UTC millisecond timestamp (deterministic-testable)
- GET query string is part of the signed requestPath, byte-for-byte
- POST body is serialized once and shared by signing and request
- OKX Demo uses x-simulated-trading:1; LIVE never adds it
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx

from crypto_trader.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from crypto_trader.domain.errors import (
    AuthenticationError,
    ExchangeUnavailable,
    OrderNotFound,
    OrderRejected,
)
from crypto_trader.domain.models import Balance, ExchangeEvent, Fill, Order, Position
from crypto_trader.domain.money import D, format_decimal
from crypto_trader.exchange.base import ExchangeAdapter


class OKXDiagnosticError(ExchangeUnavailable):
    """Safe, structured failure returned by an OKX REST response."""

    def __init__(
        self,
        reason_code: str,
        safe_message: str,
        exchange_code: str | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.reason_code = reason_code
        self.safe_message = safe_message[:256]
        self.exchange_code = exchange_code


def classify_okx_error(exchange_code: str, message: str) -> str:
    """Map documented/common OKX failures without exposing request secrets."""
    normalized = message.lower()
    if exchange_code in {"50011", "50061"} or "rate limit" in normalized:
        return "RATE_LIMITED"
    if (
        exchange_code in {"50115"}
        or "ip" in normalized
        and ("white" in normalized or "restrict" in normalized or "allow" in normalized)
    ):
        return "IP_RESTRICTED"
    if exchange_code in {"50101", "50102"} or any(
        term in normalized for term in ("simulated", "demo", "testnet", "environment mismatch")
    ):
        return "DEMO_ENV_MISMATCH"
    if "permission" in normalized or "not allowed" in normalized:
        return "PERMISSION_DENIED"
    if exchange_code in {"50103", "50113", "50114", "50121"} or any(
        term in normalized
        for term in ("api key", "passphrase", "signature", "authentication", "authorization")
    ):
        return "AUTH_FAILED"
    return "OKX_REJECTED"


def _okx_payload(response: httpx.Response, *, path: str) -> dict:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise OKXDiagnosticError(
            "MALFORMED_RESPONSE", f"OKX returned invalid JSON for {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise OKXDiagnosticError("MALFORMED_RESPONSE", f"OKX returned invalid data for {path}")
    exchange_code = str(payload.get("code", ""))
    if exchange_code != "0":
        message = str(payload.get("msg", "OKX rejected request"))
        raise OKXDiagnosticError(classify_okx_error(exchange_code, message), message, exchange_code)
    return payload


def okx_timestamp() -> str:
    """OKX REST requires ISO 8601 UTC with milliseconds."""
    return (
        datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{datetime.now(UTC).microsecond // 1000:03d}Z"
    )


def okx_prehash(timestamp: str, method: str, request_path: str, body: str) -> str:
    return f"{timestamp}{method}{request_path}{body}"


def okx_signature(secret: str, prehash: str) -> str:
    return base64.b64encode(
        hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()
    ).decode()


def canonical_query_string(params: dict) -> str:
    if not params:
        return ""
    return "&".join(f"{k}={params[k]}" for k in sorted(params))


class OKXAdapter(ExchangeAdapter):
    name = "OKX"

    def __init__(
        self,
        *,
        base_url: str = "https://openapi.okx.com",
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
        self.time_offset_ms = 0
        self.auth_status = "NOT_CONFIGURED"
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

    async def sync_server_time(self) -> dict:
        data = await self._public_request("GET", "/api/v5/public/time")
        rows = data.get("data")
        if (
            not isinstance(rows, list)
            or not rows
            or not isinstance(rows[0], dict)
            or "ts" not in rows[0]
        ):
            raise OKXDiagnosticError("MALFORMED_RESPONSE", "OKX public time response is incomplete")
        try:
            server_ms = int(rows[0]["ts"])
        except (TypeError, ValueError) as exc:
            raise OKXDiagnosticError("MALFORMED_RESPONSE", "OKX public time is invalid") from exc
        local_ms = int(datetime.now(UTC).timestamp() * 1000)
        self.time_offset_ms = server_ms - local_ms
        return {"server_ms": server_ms, "local_ms": local_ms, "offset_ms": self.time_offset_ms}

    async def _public_request(self, method: str, path: str, params: dict | None = None):
        if not self.connected:
            await self.connect()
        try:
            response = await self._client.request(method, path, params=params)
        except httpx.RequestError as exc:
            raise OKXDiagnosticError("NETWORK_ERROR", "Unable to connect to OKX") from exc
        if response.status_code >= 500:
            raise OKXDiagnosticError(
                "OKX_UNAVAILABLE", f"OKX public service HTTP {response.status_code}"
            )
        if response.status_code != 200:
            raise OKXDiagnosticError(
                "OKX_REJECTED", f"OKX public request HTTP {response.status_code}"
            )
        return _okx_payload(response, path=path)

    def _build_headers(self, method: str, request_path: str, body: str) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.demo:
            headers["x-simulated-trading"] = "1"
        if self.api_key and self.api_secret and self.api_passphrase:
            timestamp = okx_timestamp()
            prehash = okx_prehash(timestamp, method, request_path, body)
            headers.update(
                {
                    "OK-ACCESS-KEY": self.api_key,
                    "OK-ACCESS-SIGN": okx_signature(self.api_secret, prehash),
                    "OK-ACCESS-TIMESTAMP": timestamp,
                    "OK-ACCESS-PASSPHRASE": self.api_passphrase,
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
            self.auth_status = "NOT_CONFIGURED"
            raise AuthenticationError("OKX credentials are not configured")
        if not self.connected:
            await self.connect()
        body_str = json.dumps(body, separators=(",", ":")) if body is not None else ""
        query = canonical_query_string(params or {})
        request_path = f"{path}?{query}" if query else path
        headers = self._build_headers(method, request_path, body_str)
        for attempt in range(3):
            try:
                response = await self._client.request(
                    method, path, params=params, content=body_str or None, headers=headers
                )
            except UnicodeError as exc:
                raise OKXDiagnosticError(
                    "AUTH_FAILED", "OKX credential contains unsupported characters"
                ) from exc
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise OKXDiagnosticError("NETWORK_ERROR", "Unable to connect to OKX") from exc
                continue
            if response.status_code == 200:
                return _okx_payload(response, path=path)
            if response.status_code == 429:
                raise OKXDiagnosticError("RATE_LIMITED", "OKX rate limited")
            if response.status_code in (401, 403):
                self.auth_status = "AUTH_FAILED"
                raise OKXDiagnosticError("AUTH_FAILED", "OKX authentication failed")
            if response.status_code >= 500:
                raise OKXDiagnosticError(
                    "OKX_UNAVAILABLE", f"OKX service HTTP {response.status_code}"
                )
            return _okx_payload(response, path=path)
        raise ExchangeUnavailable("OKX request failed after retries")

    async def validate_credentials(self) -> dict:
        if not (self.api_key and self.api_secret and self.api_passphrase):
            self.auth_status = "NOT_CONFIGURED"
            return {"status": "NOT_CONFIGURED"}
        try:
            await self.get_balances()
            await self.get_positions()
            self.auth_status = "VERIFIED"
            return {"status": "VERIFIED"}
        except AuthenticationError:
            self.auth_status = "AUTH_FAILED"
            return {"status": "AUTH_FAILED"}

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
        from crypto_trader.exchange.symbol_mapper import SymbolMapper

        return Position(
            symbol=SymbolMapper().to_canonical(str(raw.get("instId", ""))),
            base_asset=raw.get("ccy", ""),
            quote_asset="USDT",
            quantity=D(raw.get("pos", "0")),
            avg_entry_price=D(raw.get("avgPx", "0")),
            realized_pnl=D(raw.get("upl", "0")),
            updated_at=datetime.now(UTC),
        )

    async def get_pending_orders(self):
        return await self._request("GET", "/api/v5/trade/orders-pending", signed=True)

    async def get_account_config(self):
        return await self._request("GET", "/api/v5/account/config", signed=True)

    async def get_orderbook(self, symbol: str, limit: int = 100):
        data = await self._public_request(
            "GET", "/api/v5/market/books", params={"instId": symbol, "sz": limit}
        )
        return data

    async def get_ticker(self, symbol: str):
        data = await self._public_request("GET", "/api/v5/market/ticker", params={"instId": symbol})
        if not data.get("data"):
            raise OrderNotFound(symbol)
        raw = data["data"][0]
        return {
            "symbol": raw["instId"],
            "last": raw.get("last", "0"),
            "bid": raw.get("bidPx", "0"),
            "ask": raw.get("askPx", "0"),
            "open_24h": raw.get("open24h", "0"),
            "volume_24h": raw.get("vol24h", "0"),
            "timestamp": raw.get("ts", "0"),
        }

    async def get_public_mark_price(self, inst_id: str) -> dict:
        data = await self._public_request(
            "GET", "/api/v5/public/mark-price", params={"instType": "SWAP", "instId": inst_id}
        )
        return data["data"][0]

    async def get_public_index_ticker(self, inst_id: str) -> dict:
        data = await self._public_request(
            "GET", "/api/v5/market/index-tickers", params={"instId": inst_id}
        )
        return data["data"][0]

    async def get_public_funding_rate(self, inst_id: str) -> dict:
        data = await self._public_request(
            "GET", "/api/v5/public/funding-rate", params={"instId": inst_id}
        )
        return data["data"][0]

    # ------------------------------------------------------------------
    # Phase B: batch public market datasets (rate-limit aware: ONE call per
    # product class instead of per-symbol polling).
    # ------------------------------------------------------------------

    async def get_instruments(self, inst_type: str, uly: str | None = None) -> list[dict]:
        """Full instrument metadata for one product class (discovery)."""
        params: dict = {"instType": inst_type}
        if uly:
            params["uly"] = uly
        data = await self._public_request(
            "GET", "/api/v5/public/instruments", params=params
        )
        return list(data.get("data") or [])

    async def get_all_tickers(self, inst_type: str = "SPOT") -> list[dict]:
        """Batch tickers for an entire product class in ONE request.

        Returns last/bid/ask/sizes/24h stats for every instrument - the
        Layer-1 factual scan foundation for the Market Observer.
        """
        data = await self._public_request(
            "GET", "/api/v5/market/tickers", params={"instType": inst_type}
        )
        return list(data.get("data") or [])

    async def get_open_interest_batch(self, inst_type: str = "SWAP") -> list[dict]:
        """Batch open interest (oi / oiCcy / oiUsd) for one product class."""
        data = await self._public_request(
            "GET", "/api/v5/public/open-interest", params={"instType": inst_type}
        )
        return list(data.get("data") or [])

    async def get_funding_rate_history(
        self, inst_id: str, limit: int = 100, before: str | None = None, after: str | None = None
    ) -> list[dict]:
        """Historical funding rates (paginated via before/after)."""
        params: dict = {"instId": inst_id, "limit": str(limit)}
        if before:
            params["before"] = before
        if after:
            params["after"] = after
        data = await self._public_request(
            "GET", "/api/v5/public/funding-rate-history", params=params
        )
        return list(data.get("data") or [])

    async def get_history_candles(
        self, inst_id: str, bar: str = "1D", limit: int = 100,
        after: str | None = None, before: str | None = None,
    ) -> list[list[str]]:
        """Historical candles (research/backfill; paginated, on-demand)."""
        params: dict = {"instId": inst_id, "bar": bar, "limit": str(limit)}
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        data = await self._public_request(
            "GET", "/api/v5/market/history-candles", params=params
        )
        return list(data.get("data") or [])

    async def get_recent_trades(self, inst_id: str, limit: int = 100) -> list[dict]:
        """Recent public trades snapshot."""
        data = await self._public_request(
            "GET", "/api/v5/market/trades", params={"instId": inst_id, "limit": str(limit)}
        )
        return list(data.get("data") or [])

    async def get_history_trades(
        self, inst_id: str, limit: int = 100, after: str | None = None
    ) -> list[dict]:
        """Historical public trades (paginated via after tradeId)."""
        params: dict = {"instId": inst_id, "limit": str(limit)}
        if after:
            params["after"] = after
        data = await self._public_request(
            "GET", "/api/v5/market/history-trades", params=params
        )
        return list(data.get("data") or [])

    async def get_public_open_interest(self, inst_id: str) -> dict:
        data = await self._public_request(
            "GET", "/api/v5/public/open-interest", params={"instType": "SWAP", "instId": inst_id}
        )
        return data["data"][0]

    async def get_candles(self, inst_id: str, bar: str, limit: int = 500) -> list[list[str]]:
        """Fetch public OKX candles; no credentials or demo headers are used."""
        data = await self._public_request(
            "GET",
            "/api/v5/market/candles",
            params={"instId": inst_id, "bar": bar, "limit": limit},
        )
        rows = data.get("data")
        if not isinstance(rows, list):
            raise OKXDiagnosticError("MALFORMED_RESPONSE", "OKX candle response is incomplete")
        if not all(isinstance(row, list) and len(row) >= 9 for row in rows):
            raise OKXDiagnosticError(
                "MALFORMED_RESPONSE", "OKX candle response contains invalid rows"
            )
        return rows

    def _cl_ord_id(self, client_order_id: str) -> str:
        digest = hashlib.sha256(client_order_id.encode()).hexdigest()[:28].upper()
        return f"C{digest}"

    async def submit_order(self, order: Order):
        from crypto_trader.exchange.symbol_mapper import SymbolMapper

        inst_id = SymbolMapper().to_okx(order.symbol)
        body = {
            "instId": inst_id,
            "tdMode": "cross",
            "clOrdId": self._cl_ord_id(order.client_order_id),
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
            symbol=SymbolMapper().to_canonical(str(raw.get("instId", fallback.symbol))),
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
            price=D(raw.get("fillPx", "0")),
            quantity=D(raw.get("fillSz", "0")),
            fee=D(raw.get("fee", "0")),
            fee_currency=raw.get("feeCcy"),
            timestamp=datetime.fromtimestamp(int(raw.get("ts", 0)) / 1000.0, tz=UTC),
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
