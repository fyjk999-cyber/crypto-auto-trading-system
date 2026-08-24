"""-M Futures PUBLIC market-data client.

No API key is required. SPOT and USD-M FUTURES are strictly separated.
This client only calls public market-data endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from crypto_trader.domain.money import D


class BinancePublicDataUnavailable(Exception):
    """Raised when Binance public data cannot be fetched (network/geo/5xx)."""


class BinanceUSDMFuturesPublicClient:
    BASE_URL = "https://fapi.binance.com"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(base_url=self.BASE_URL, timeout=10.0)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> Any:
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise BinancePublicDataUnavailable(
                f"binance futures public request failed: {exc}"
            ) from exc
        if response.status_code != 200:
            raise BinancePublicDataUnavailable(
                f"binance futures public {path} status={response.status_code}"
            )
        try:
            return response.json()
        except Exception as exc:
            raise BinancePublicDataUnavailable(
                f"binance futures public {path} bad json: {exc}"
            ) from exc

    async def get_orderbook(self, symbol: str, limit: int = 100) -> dict:
        return await self._get("/fapi/v1/depth", {"symbol": symbol, "limit": limit})

    async def get_mark_price(self, symbol: str) -> dict:
        data = await self._get("/fapi/v1/premiumIndex", {"symbol": symbol})
        # premiumIndex contains markPrice, indexPrice, lastFundingRate, nextFundingTime
        if isinstance(data, dict):
            return data
        raise BinancePublicDataUnavailable("unexpected premiumIndex response")

    async def get_ticker(self, symbol: str) -> dict:
        data = await self._get("/fapi/v1/ticker/24hr", {"symbol": symbol})
        if isinstance(data, dict):
            return data
        raise BinancePublicDataUnavailable("unexpected ticker response")

    async def get_funding_rate(self, symbol: str, limit: int = 1) -> dict:
        data = await self._get("/fapi/v1/fundingRate", {"symbol": symbol, "limit": limit})
        if isinstance(data, list) and data:
            return data[0]
        raise BinancePublicDataUnavailable("unexpected fundingRate response")

    async def get_open_interest(self, symbol: str) -> dict:
        return await self._get("/fapi/v1/openInterest", {"symbol": symbol})

    async def get_aggregate_trades(self, symbol: str, limit: int = 100) -> list[dict]:
        data = await self._get("/fapi/v1/aggTrades", {"symbol": symbol, "limit": limit})
        if isinstance(data, list):
            return data
        raise BinancePublicDataUnavailable("unexpected aggTrades response")

    async def get_klines(self, symbol: str, interval: str = "1m", limit: int = 300) -> list[dict]:
        data = await self._get(
            "/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit}
        )
        if isinstance(data, list):
            return data
        raise BinancePublicDataUnavailable("unexpected klines response")

    @staticmethod
    def normalize_mark_price(raw: dict) -> dict:
        return {
            "symbol": raw["symbol"],
            "mark_price": D(raw["markPrice"]),
            "index_price": D(raw["indexPrice"]),
            "funding_rate": D(raw.get("lastFundingRate", "0")),
            "next_funding_time": datetime.fromtimestamp(
                int(raw["nextFundingTime"]) / 1000.0, tz=UTC
            )
            if raw.get("nextFundingTime")
            else None,
        }

    @staticmethod
    def normalize_open_interest(raw: dict) -> dict:
        return {
            "symbol": raw["symbol"],
            "open_interest": D(raw["openInterest"]),
        }

    @staticmethod
    def normalize_orderbook(raw: dict) -> dict:
        return {
            "symbol": raw["symbol"],
            "sequence": int(raw.get("lastUpdateId", 0)),
            "bids": [(D(b[0]), D(b[1])) for b in raw.get("bids", [])],
            "asks": [(D(a[0]), D(a[1])) for a in raw.get("asks", [])],
        }

    @staticmethod
    def normalize_kline(raw: dict) -> dict:
        return {
            "symbol": raw.get("symbol"),
            "interval": raw.get("interval", "1m"),
            "open_time": datetime.fromtimestamp(int(raw["openTime"]) / 1000.0, tz=UTC)
            if isinstance(raw.get("openTime"), (int, float))
            else None,
            "open": D(raw["open"]),
            "high": D(raw["high"]),
            "low": D(raw["low"]),
            "close": D(raw["close"]),
            "volume": D(raw["volume"]),
            "close_time": datetime.fromtimestamp(int(raw["closeTime"]) / 1000.0, tz=UTC)
            if isinstance(raw.get("closeTime"), (int, float))
            else None,
            "closed": bool(raw.get("closed", True)),
            "source": "BINANCE_USDM",
        }

    @staticmethod
    def normalize_kline_stream(raw: dict) -> dict:
        k = raw.get("k", raw)
        return BinanceUSDMFuturesPublicClient.normalize_kline(k)

    @staticmethod
    def normalize_kline_array(rows: list[dict], symbol: str, interval: str) -> list[dict]:
        out = []
        for row in rows:
            try:
                out.append(
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "open_time": datetime.fromtimestamp(int(row[0]) / 1000.0, tz=UTC),
                        "open": D(row[1]),
                        "high": D(row[2]),
                        "low": D(row[3]),
                        "close": D(row[4]),
                        "volume": D(row[5]),
                        "close_time": datetime.fromtimestamp(int(row[6]) / 1000.0, tz=UTC),
                        "closed": True,
                        "source": "BINANCE_USDM",
                    }
                )
            except Exception:
                continue
        return out

    async def get_basis(self, symbol: str, period: str = "1h", limit: int = 10) -> list[dict]:
        return await self._get(
            "/futures/data/basis", {"symbol": symbol, "period": period, "limit": limit}
        )
