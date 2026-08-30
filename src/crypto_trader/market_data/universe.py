"""Dynamic observable market universe + all-market Layer-1 factual scan.

Reads instrument truth from the persisted OKX registry. Produces compact
factual market summaries only - no trading score, no composite opportunity
ranking. Missing data stays NOT_AVAILABLE per symbol; cross-symbol fallback
is forbidden.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from crypto_trader.market_data.okx_public_data import OKXPublicDataClient
from crypto_trader.market_registry.registry import registry_stats_sync


@dataclass
class Layer1Fact:
    inst_id: str
    inst_type: str
    last: str = "NOT_AVAILABLE"
    bid: str = "NOT_AVAILABLE"
    ask: str = "NOT_AVAILABLE"
    bid_size: str = "NOT_AVAILABLE"
    ask_size: str = "NOT_AVAILABLE"
    spread: str = "NOT_AVAILABLE"
    high_24h: str = "NOT_AVAILABLE"
    low_24h: str = "NOT_AVAILABLE"
    volume_24h: str = "NOT_AVAILABLE"
    volume_ccy_24h: str = "NOT_AVAILABLE"
    timestamp: str = ""
    source: str = "OKX"
    freshness: str = "NOT_AVAILABLE"

    def to_dict(self) -> dict:
        return {
            "inst_id": self.inst_id, "inst_type": self.inst_type,
            "last": self.last, "bid": self.bid, "ask": self.ask,
            "bid_size": self.bid_size, "ask_size": self.ask_size,
            "spread": self.spread, "high_24h": self.high_24h,
            "low_24h": self.low_24h, "volume_24h": self.volume_24h,
            "volume_ccy_24h": self.volume_ccy_24h, "timestamp": self.timestamp,
            "source": self.source, "freshness": self.freshness,
        }


@dataclass
class MarketSnapshotBatch:
    batch_id: str
    inst_type: str
    captured_at: str
    facts: list[Layer1Fact] = field(default_factory=list)
    request_count: int = 1

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id, "inst_type": self.inst_type,
            "captured_at": self.captured_at,
            "facts": [f.to_dict() for f in self.facts],
            "request_count": self.request_count,
        }


def _num(value: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        return Decimal("0")


class DynamicMarketUniverse:
    """Read-only dynamic universe + Layer-1 factual compression."""

    def __init__(self, db_path: str, data_client: OKXPublicDataClient | None = None):
        self.db_path = db_path
        self.data_client = data_client

    def stats(self) -> dict:
        return registry_stats_sync(self.db_path)

    def observable_universe(self, *, inst_type: str | None = None,
                            quote_ccy: str = "USDT",
                            max_instruments: int = 5000) -> list[dict]:
        """Live instruments from the persisted registry, ordered by inst_id."""
        conn = sqlite3.connect(self.db_path)
        try:
            sql = ("SELECT inst_id, inst_type, state FROM okx_instruments "
                   "WHERE state='live'")
            params: list[object] = []
            if inst_type:
                sql += " AND inst_type=?"
                params.append(inst_type)
            if quote_ccy:
                sql += " AND (quote_ccy=? OR quote_ccy IS NULL)"
                params.append(quote_ccy)
            sql += " ORDER BY inst_id LIMIT ?"
            params.append(int(max_instruments))
            rows = conn.execute(sql, params).fetchall()
            return [{"inst_id": r[0], "inst_type": r[1], "state": r[2]} for r in rows]
        finally:
            conn.close()

    async def layer1_batch(self, inst_type: str) -> MarketSnapshotBatch:
        """One batch tickers call per product class. Never per-symbol REST."""
        if self.data_client is None:
            raise RuntimeError("data_client required for layer1_batch")
        rows = await self.data_client.get_tickers(inst_type)
        facts: list[Layer1Fact] = []
        for raw in rows:
            inst_id = str(raw.get("instId") or "")
            if not inst_id:
                continue
            bid = str(raw.get("bidPx") or "NOT_AVAILABLE")
            ask = str(raw.get("askPx") or "NOT_AVAILABLE")
            spread = "NOT_AVAILABLE"
            if bid != "NOT_AVAILABLE" and ask != "NOT_AVAILABLE":
                spread = str(_num(ask) - _num(bid))
            facts.append(Layer1Fact(
                inst_id=inst_id,
                inst_type=inst_type,
                last=str(raw.get("last") or "NOT_AVAILABLE"),
                bid=bid,
                ask=ask,
                bid_size=str(raw.get("bidSz") or "NOT_AVAILABLE"),
                ask_size=str(raw.get("askSz") or "NOT_AVAILABLE"),
                spread=spread,
                high_24h=str(raw.get("high24h") or "NOT_AVAILABLE"),
                low_24h=str(raw.get("low24h") or "NOT_AVAILABLE"),
                volume_24h=str(raw.get("vol24h") or "NOT_AVAILABLE"),
                volume_ccy_24h=str(raw.get("volCcy24h") or "NOT_AVAILABLE"),
                timestamp=str(raw.get("ts") or ""),
                freshness="LIVE",
            ))
        return MarketSnapshotBatch(
            batch_id=f"l1-{inst_type}-{datetime.now(UTC).isoformat()}",
            inst_type=inst_type,
            captured_at=datetime.now(UTC).isoformat(),
            facts=facts,
        )
