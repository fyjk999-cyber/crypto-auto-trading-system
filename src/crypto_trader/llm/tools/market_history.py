"""Bounded factual closed-candle history for ChiefTrader."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from crypto_trader.llm.tools.registry import LLMToolRegistry, ToolEvidence


def register_market_history_tool(registry: LLMToolRegistry, feed) -> None:
    registry.register(
        "multi_timeframe_history", _tool(feed),
        description="Up to 60 factual closed OKX candles for 1m, 15m, and 1H",
        version="okx-closed-candles-1.1.0",
        source="OKX_PUBLIC_CANDLES",
        data_time_semantics=(
            "confirm=1 closed candles only; candle timestamp must be <= decision as_of"
        ),
    )


def _tool(feed):
    async def execute(symbol: str, context: dict) -> ToolEvidence:
        instrument_id = feed.provider_symbol(symbol)

        async def fetch(interval: str):
            rows = await feed.client.get_candles(instrument_id, interval, 60)
            return interval, [
                {
                    "timestamp": datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC).isoformat(),
                    "open": str(row[1]), "high": str(row[2]), "low": str(row[3]),
                    "close": str(row[4]),
                    # OKX SWAP candle schema:
                    # vol=contracts, volCcy=base currency, volCcyQuote=quote currency.
                    "volume": str(row[5]),
                    "volume_contracts": str(row[5]),
                    "volume_base": str(row[6]),
                    "volume_quote": str(row[7]),
                    "volume_unit": "OKX_SWAP_CONTRACTS",
                }
                for row in reversed(rows)
                if isinstance(row, list) and len(row) >= 9 and str(row[8]) == "1"
                and datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC) <= context["as_of"]
            ]

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
