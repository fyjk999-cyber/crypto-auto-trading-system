"""Bounded factual closed-candle history for ChiefTrader."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from crypto_trader.llm.tools.registry import LLMToolRegistry, ToolEvidence

_INTERVAL_DURATION = {
    "1m": timedelta(minutes=1),
    "15m": timedelta(minutes=15),
    "1H": timedelta(hours=1),
}


def register_market_history_tool(registry: LLMToolRegistry, feed) -> None:
    registry.register(
        "multi_timeframe_history", _tool(feed),
        description="Up to 60 factual closed OKX candles for 1m, 15m, and 1H",
    )


def _tool(feed):
    async def execute(symbol: str, context: dict) -> ToolEvidence:
        instrument_id = feed.provider_symbol(symbol)

        async def fetch(interval: str):
            duration = _INTERVAL_DURATION[interval]
            as_of = context["as_of"]
            rows = await feed.client.get_candles(instrument_id, interval, 60)
            selected = []
            for row in reversed(rows):
                if not isinstance(row, list) or len(row) < 9:
                    continue
                if str(row[8]) != "1":
                    continue
                open_at = datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC)
                # A candle is factual closed history only once its full
                # interval has ended; confirm=1 today cannot backfill a
                # historical decision as-of.
                if open_at + duration > as_of:
                    continue
                selected.append(
                    {
                        "timestamp": open_at.isoformat(),
                        "open": str(row[1]),
                        "high": str(row[2]),
                        "low": str(row[3]),
                        "close": str(row[4]),
                        "volume": str(row[5]),
                    }
                )
            return interval, selected

        results = await asyncio.gather(*(fetch(item) for item in ("1m", "15m", "1H")))
        payload = {interval: rows for interval, rows in results}
        latest = [datetime.fromisoformat(rows[-1]["timestamp"]) for _, rows in results if rows]
        return ToolEvidence(
            tool_name="multi_timeframe_history", symbol=symbol,
            timestamp=max(latest, default=context["as_of"]), features=payload,
            supporting_evidence=[],
            contrary_evidence=[] if latest else ["no closed candles"],
            confidence_of_measurement=1.0 if latest else 0.0,
            data_quality="FACTUAL_OKX_CLOSED" if latest else "UNAVAILABLE",
            source_refs=[f"okx:{instrument_id}:candles"] if latest else [],
        )

    return execute
