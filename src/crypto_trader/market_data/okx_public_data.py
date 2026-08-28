"""Expanded OKX public market-data access using the canonical OKX transport.

The hot trading loop should use only small cached recent windows. Backfill
methods here are intended for research/review/persistence jobs and page through
as much history as OKX exposes for the requested endpoint.
"""

from __future__ import annotations

from crypto_trader.exchange.okx import OKXAdapter, OKXDiagnosticError


class OKXPublicDataClient:
    def __init__(self, adapter: OKXAdapter) -> None:
        self.adapter = adapter

    async def get_ticker(self, inst_id: str) -> dict:
        data = await self.adapter._public_request(  # noqa: SLF001 - shared canonical transport
            "GET", "/api/v5/market/ticker", params={"instId": inst_id}
        )
        rows = data.get("data")
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            raise OKXDiagnosticError("MALFORMED_RESPONSE", "OKX ticker response is incomplete")
        raw = rows[0]
        return {
            "symbol": raw.get("instId", inst_id),
            "last": raw.get("last", "0"),
            "last_size": raw.get("lastSz"),
            "bid": raw.get("bidPx", "0"),
            "bid_size": raw.get("bidSz"),
            "ask": raw.get("askPx", "0"),
            "ask_size": raw.get("askSz"),
            "open_24h": raw.get("open24h"),
            "high_24h": raw.get("high24h"),
            "low_24h": raw.get("low24h"),
            "volume_24h": raw.get("vol24h"),
            "quote_volume_24h": raw.get("volCcy24h"),
            "open_utc0": raw.get("sodUtc0"),
            "open_utc8": raw.get("sodUtc8"),
            "timestamp": raw.get("ts", "0"),
        }

    async def get_recent_candles(
        self,
        inst_id: str,
        bar: str = "1m",
        *,
        after: str | None = None,
        before: str | None = None,
        limit: int = 300,
    ) -> list[list[str]]:
        params: dict[str, object] = {
            "instId": inst_id,
            "bar": bar,
            "limit": min(max(limit, 1), 300),
        }
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        data = await self.adapter._public_request(  # noqa: SLF001
            "GET", "/api/v5/market/candles", params=params
        )
        return self._candle_rows(data, "recent candle")

    async def get_history_candles(
        self,
        inst_id: str,
        bar: str = "1m",
        *,
        after: str | None = None,
        before: str | None = None,
        limit: int = 100,
    ) -> list[list[str]]:
        params: dict[str, object] = {
            "instId": inst_id,
            "bar": bar,
            "limit": min(max(limit, 1), 100),
        }
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        data = await self.adapter._public_request(  # noqa: SLF001
            "GET", "/api/v5/market/history-candles", params=params
        )
        return self._candle_rows(data, "history candle")

    async def backfill_candles(
        self,
        inst_id: str,
        bar: str = "1m",
        *,
        max_pages: int | None = None,
    ) -> list[list[str]]:
        """Page backwards until OKX is exhausted or ``max_pages`` is reached."""
        by_timestamp: dict[str, list[str]] = {}
        after: str | None = None
        pages = 0
        while max_pages is None or pages < max_pages:
            rows = await self.get_history_candles(inst_id, bar, after=after, limit=100)
            if not rows:
                break
            for row in rows:
                by_timestamp[str(row[0])] = row
            oldest = min(int(row[0]) for row in rows)
            next_after = str(oldest)
            pages += 1
            if next_after == after or len(rows) < 100:
                break
            after = next_after
        return [by_timestamp[key] for key in sorted(by_timestamp, key=int)]

    async def get_recent_trades(self, inst_id: str, limit: int = 500) -> list[dict]:
        data = await self.adapter._public_request(  # noqa: SLF001
            "GET",
            "/api/v5/market/trades",
            params={"instId": inst_id, "limit": min(max(limit, 1), 500)},
        )
        rows = data.get("data")
        if not isinstance(rows, list):
            raise OKXDiagnosticError("MALFORMED_RESPONSE", "OKX trades response is incomplete")
        return [row for row in rows if isinstance(row, dict)]

    async def get_trade_history(
        self,
        inst_id: str,
        *,
        after: str | None = None,
        before: str | None = None,
        pagination_type: str = "1",
        limit: int = 100,
    ) -> list[dict]:
        params: dict[str, object] = {
            "instId": inst_id,
            "type": pagination_type,
            "limit": min(max(limit, 1), 100),
        }
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        data = await self.adapter._public_request(  # noqa: SLF001
            "GET", "/api/v5/market/history-trades", params=params
        )
        rows = data.get("data")
        if not isinstance(rows, list):
            raise OKXDiagnosticError(
                "MALFORMED_RESPONSE", "OKX trade history response is incomplete"
            )
        return [row for row in rows if isinstance(row, dict)]

    async def get_funding_rate_history(
        self,
        inst_id: str,
        *,
        after: str | None = None,
        before: str | None = None,
        limit: int = 400,
    ) -> list[dict]:
        params: dict[str, object] = {
            "instId": inst_id,
            "limit": min(max(limit, 1), 400),
        }
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        data = await self.adapter._public_request(  # noqa: SLF001
            "GET", "/api/v5/public/funding-rate-history", params=params
        )
        rows = data.get("data")
        if not isinstance(rows, list):
            raise OKXDiagnosticError(
                "MALFORMED_RESPONSE", "OKX funding history response is incomplete"
            )
        return [row for row in rows if isinstance(row, dict)]

    async def get_index_candles(
        self,
        index_id: str,
        bar: str = "1m",
        *,
        history: bool = False,
        after: str | None = None,
        limit: int = 100,
    ) -> list[list[str]]:
        path = "/api/v5/market/history-index-candles" if history else "/api/v5/market/index-candles"
        params: dict[str, object] = {
            "instId": index_id,
            "bar": bar,
            "limit": min(max(limit, 1), 100),
        }
        if after:
            params["after"] = after
        data = await self.adapter._public_request("GET", path, params=params)  # noqa: SLF001
        return self._candle_rows(data, "index candle", minimum_fields=6)

    async def get_mark_price_candles(
        self,
        inst_id: str,
        bar: str = "1m",
        *,
        history: bool = False,
        after: str | None = None,
        limit: int = 100,
    ) -> list[list[str]]:
        path = (
            "/api/v5/market/history-mark-price-candles"
            if history
            else "/api/v5/market/mark-price-candles"
        )
        params: dict[str, object] = {
            "instId": inst_id,
            "bar": bar,
            "limit": min(max(limit, 1), 100),
        }
        if after:
            params["after"] = after
        data = await self.adapter._public_request("GET", path, params=params)  # noqa: SLF001
        return self._candle_rows(data, "mark-price candle", minimum_fields=6)

    @staticmethod
    def _candle_rows(data: dict, name: str, minimum_fields: int = 6) -> list[list[str]]:
        rows = data.get("data")
        if not isinstance(rows, list):
            raise OKXDiagnosticError("MALFORMED_RESPONSE", f"OKX {name} response is incomplete")
        if not all(isinstance(row, list) and len(row) >= minimum_fields for row in rows):
            raise OKXDiagnosticError("MALFORMED_RESPONSE", f"OKX {name} response has invalid rows")
        return rows
