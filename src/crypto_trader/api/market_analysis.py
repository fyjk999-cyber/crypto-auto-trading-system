"""Read-only OKX market intelligence endpoints for the frontend.

The API exposes real market state, advisory technical indicators, and paged
public OKX history. Quant/technical outputs are evidence only and never become
entry gates or execution authority.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from crypto_trader.api.deps import AppState
from crypto_trader.exchange.okx import OKXAdapter, OKXDiagnosticError
from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.market_data.okx_public_data import OKXPublicDataClient
from crypto_trader.market_data.technical_indicators import calculate_technical_indicators

_INTERVALS = {
    "1s": "1s",
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1H",
    "2h": "2H",
    "4h": "4H",
    "6h": "6H",
    "12h": "12H",
    "1d": "1D",
    "2d": "2D",
    "3d": "3D",
    "1w": "1W",
    "1M": "1M",
    "3M": "3M",
}

_DATASETS = (
    "candles",
    "trades",
    "funding",
    "index_candles",
    "mark_price_candles",
)


def _iso_from_ms(value: object) -> str | None:
    try:
        return datetime.fromtimestamp(int(str(value)) / 1000.0, tz=UTC).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def normalize_candle_rows(
    rows: list[list[str]],
    *,
    symbol: str,
    interval: str,
    source_kind: str,
) -> list[dict]:
    result: list[dict] = []
    for row in rows:
        if len(row) < 5:
            continue
        result.append(
            {
                "timestamp": _iso_from_ms(row[0]),
                "timestamp_ms": str(row[0]),
                "symbol": symbol,
                "interval": interval,
                "kind": source_kind,
                "open": str(row[1]),
                "high": str(row[2]),
                "low": str(row[3]),
                "close": str(row[4]),
                "volume": str(row[5]) if len(row) > 5 else None,
                "volume_ccy": str(row[6]) if len(row) > 6 else None,
                "volume_quote": str(row[7]) if len(row) > 7 else None,
                "confirmed": str(row[8]) == "1" if len(row) > 8 else None,
            }
        )
    return result


def normalize_trade_rows(rows: list[dict], *, symbol: str) -> list[dict]:
    return [
        {
            "timestamp": _iso_from_ms(row.get("ts")),
            "timestamp_ms": str(row.get("ts", "")),
            "symbol": symbol,
            "trade_id": row.get("tradeId"),
            "price": row.get("px"),
            "size": row.get("sz"),
            "side": row.get("side"),
            "count": row.get("count"),
        }
        for row in rows
    ]


def normalize_funding_rows(rows: list[dict], *, symbol: str) -> list[dict]:
    return [
        {
            "timestamp": _iso_from_ms(
                row.get("fundingTime") or row.get("nextFundingTime")
            ),
            "timestamp_ms": str(
                row.get("fundingTime") or row.get("nextFundingTime") or ""
            ),
            "symbol": symbol,
            "funding_rate": row.get("fundingRate"),
            "realized_rate": row.get("realizedRate"),
            "formula_type": row.get("formulaType"),
            "method": row.get("method"),
        }
        for row in rows
    ]


def history_cursor(rows: list[dict]) -> str | None:
    timestamps: list[int] = []
    for row in rows:
        value = row.get("timestamp_ms")
        try:
            timestamps.append(int(str(value)))
        except (TypeError, ValueError):
            continue
    return str(min(timestamps)) if timestamps else None


def _runtime_strategy(state: AppState):
    if state.engine is None:
        return None
    for strategy in state.engine.strategies:
        if getattr(strategy, "decision_context_provider", None) is not None:
            return strategy
    return None


async def _recent_candles_from_runtime(
    state: AppState,
    symbol: str,
) -> list[dict]:
    strategy = _runtime_strategy(state)
    provider = getattr(strategy, "decision_context_provider", None)
    get_candles = getattr(provider, "get_candles", None)
    if get_candles is None:
        return []
    try:
        return await get_candles(symbol)
    except Exception:
        return []


def create_market_analysis_router(state: AppState) -> APIRouter:
    router = APIRouter()
    mapper = SymbolMapper()

    @router.get("/market/analysis")
    async def market_analysis(symbol: str = "BTCUSDT"):
        canonical = mapper.to_canonical(symbol)
        market_payload: dict = {}
        adapter = getattr(state.engine, "adapter", None) if state.engine else None
        get_market_state = getattr(adapter, "get_market_state", None)
        if get_market_state is not None:
            try:
                market_state = await get_market_state(canonical)
                market_payload = market_state.model_dump(mode="json")
                market_payload.update(
                    provider="OKX",
                    source="OKX",
                    status=market_state.health.value,
                    data_source="REAL",
                )
            except Exception as exc:
                market_payload = {
                    "provider": "OKX",
                    "source": "OKX",
                    "status": "UNAVAILABLE",
                    "data_source": "REAL",
                    "symbol": canonical,
                    "last_error": str(exc),
                }

        candles = await _recent_candles_from_runtime(state, canonical)
        technical = calculate_technical_indicators(candles)
        strategy = _runtime_strategy(state)
        ranking = list(getattr(strategy, "opportunity_ranking", []) or [])
        status = "OK"
        if not market_payload and technical.get("status") == "UNAVAILABLE":
            status = "NOT_AVAILABLE"
        return {
            "status": status,
            "symbol": canonical,
            "source": "OKX",
            "market": market_payload,
            "technical_indicators": technical,
            "technical_indicator_authority": "ADVISORY",
            "opportunity_ranking": ranking,
            "opportunity_authority": "ADVISORY",
            "history": {
                "source": "OKX",
                "datasets": list(_DATASETS),
                "intervals": list(_INTERVALS),
                "pagination": "LOAD_EARLIER_ON_DEMAND",
            },
        }

    @router.get("/market/history")
    async def market_history(
        dataset: str = "candles",
        symbol: str = "BTCUSDT",
        interval: str = "1m",
        after: str | None = None,
        before: str | None = None,
        limit: int = 100,
    ):
        canonical = mapper.to_canonical(symbol)
        if dataset not in _DATASETS:
            return {
                "status": "INVALID_DATASET",
                "dataset": dataset,
                "rows": [],
            }
        if dataset.endswith("candles") and interval not in _INTERVALS:
            return {
                "status": "INVALID_INTERVAL",
                "dataset": dataset,
                "interval": interval,
                "rows": [],
            }

        provider_symbol = mapper.to_okx(canonical)
        index_symbol = provider_symbol.removesuffix("-SWAP")
        adapter = OKXAdapter(base_url=state.settings.okx_base_url)
        public = OKXPublicDataClient(adapter)
        try:
            if dataset == "candles":
                raw = await public.get_history_candles(
                    provider_symbol,
                    _INTERVALS[interval],
                    after=after,
                    before=before,
                    limit=limit,
                )
                rows = normalize_candle_rows(
                    raw,
                    symbol=canonical,
                    interval=interval,
                    source_kind="TRADE_PRICE",
                )
            elif dataset == "trades":
                raw = await public.get_trade_history(
                    provider_symbol,
                    after=after,
                    before=before,
                    limit=limit,
                )
                rows = normalize_trade_rows(raw, symbol=canonical)
            elif dataset == "funding":
                raw = await public.get_funding_rate_history(
                    provider_symbol,
                    after=after,
                    before=before,
                    limit=limit,
                )
                rows = normalize_funding_rows(raw, symbol=canonical)
            elif dataset == "index_candles":
                raw = await public.get_index_candles(
                    index_symbol,
                    _INTERVALS[interval],
                    history=True,
                    after=after,
                    limit=limit,
                )
                rows = normalize_candle_rows(
                    raw,
                    symbol=canonical,
                    interval=interval,
                    source_kind="INDEX_PRICE",
                )
            else:
                raw = await public.get_mark_price_candles(
                    provider_symbol,
                    _INTERVALS[interval],
                    history=True,
                    after=after,
                    limit=limit,
                )
                rows = normalize_candle_rows(
                    raw,
                    symbol=canonical,
                    interval=interval,
                    source_kind="MARK_PRICE",
                )
            return {
                "status": "HEALTHY",
                "source": "OKX",
                "dataset": dataset,
                "symbol": canonical,
                "provider_symbol": provider_symbol,
                "interval": interval if dataset.endswith("candles") else None,
                "rows": rows,
                "next_after": history_cursor(rows),
            }
        except OKXDiagnosticError as exc:
            return {
                "status": "UNAVAILABLE",
                "source": "OKX",
                "dataset": dataset,
                "symbol": canonical,
                "rows": [],
                "reason_code": exc.reason_code,
                "last_error": exc.safe_message,
            }
        finally:
            await adapter.disconnect()

    return router
