"""Dynamic OKX instrument registry (PHASE B: OKX all-market data layer).

Replaces hardcoded symbol constants as the truth source for universe
membership. Facts only:

- discovery: /api/v5/public/instruments (SPOT, SWAP, FUTURES; OPTION tracked
  by underlying count - full option chains are research-only, not persisted
  row-by-row)
- persistence: `okx_instruments` table (migration 0019) via sqlite3 direct
  writes from this OPS-ONLY refresh path - never from the trading runtime
- state tracking: live / suspend / preopen / delisted (absent after refresh)

The trading runtime, Market Observer, and Chief Trader read universe
membership from the persisted registry. No cross-symbol fallback is ever
performed: a symbol without its own data stays NOT_AVAILABLE.

Live API field audit (2026-08-29, www.okx.com):
- instruments fields include: instId, instType, uly, instFamily, baseCcy,
  quoteCcy, settleCcy, state, tickSz, lotSz, minSz, ctVal, ctValCcy,
  ctType, lever, expTime, listTime (all persisted here)
- market/tickers supports instType batch (one call per product class)
- public/open-interest supports instType batch with oi/oiCcy/oiUsd
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime

DEFAULT_TIMEOUT = 30.0
INSTRUMENT_TYPES = ("SPOT", "SWAP", "FUTURES")
OKX_BASE_URL = "https://www.okx.com"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS okx_instruments (
    inst_id VARCHAR(64) PRIMARY KEY,
    inst_type VARCHAR(16) NOT NULL,
    uly VARCHAR(64),
    inst_family VARCHAR(64),
    base_ccy VARCHAR(32),
    quote_ccy VARCHAR(32),
    settle_ccy VARCHAR(32),
    state VARCHAR(16) NOT NULL,
    tick_sz VARCHAR(32),
    lot_sz VARCHAR(32),
    min_sz VARCHAR(32),
    ct_val VARCHAR(32),
    ct_val_ccy VARCHAR(32),
    ct_type VARCHAR(16),
    lever VARCHAR(32),
    exp_time VARCHAR(32),
    list_time VARCHAR(32),
    first_seen_at TIMESTAMP NOT NULL,
    last_seen_at TIMESTAMP NOT NULL,
    refreshed_at TIMESTAMP NOT NULL
)
"""

_PERSIST_FIELDS = (
    "inst_id", "inst_type", "uly", "inst_family", "base_ccy", "quote_ccy",
    "settle_ccy", "state", "tick_sz", "lot_sz", "min_sz", "ct_val",
    "ct_val_ccy", "ct_type", "lever", "exp_time", "list_time",
)


@dataclass
class InstrumentRecord:
    inst_id: str
    inst_type: str
    uly: str | None = None
    inst_family: str | None = None
    base_ccy: str | None = None
    quote_ccy: str | None = None
    settle_ccy: str | None = None
    state: str = "unknown"
    tick_sz: str | None = None
    lot_sz: str | None = None
    min_sz: str | None = None
    ct_val: str | None = None
    ct_val_ccy: str | None = None
    ct_type: str | None = None
    lever: str | None = None
    exp_time: str | None = None
    list_time: str | None = None

    @classmethod
    def from_api(cls, raw: dict) -> InstrumentRecord:
        return cls(
            inst_id=str(raw.get("instId") or ""),
            inst_type=str(raw.get("instType") or ""),
            uly=raw.get("uly") or None,
            inst_family=raw.get("instFamily") or None,
            base_ccy=raw.get("baseCcy") or None,
            quote_ccy=raw.get("quoteCcy") or None,
            settle_ccy=raw.get("settleCcy") or None,
            state=str(raw.get("state") or "unknown"),
            tick_sz=raw.get("tickSz") or None,
            lot_sz=raw.get("lotSz") or None,
            min_sz=raw.get("minSz") or None,
            ct_val=raw.get("ctVal") or None,
            ct_val_ccy=raw.get("ctValCcy") or None,
            ct_type=raw.get("ctType") or None,
            lever=raw.get("lever") or None,
            exp_time=raw.get("expTime") or None,
            list_time=raw.get("listTime") or None,
        )


@dataclass
class RegistrySnapshot:
    refreshed_at: str
    counts: dict = field(default_factory=dict)
    states: dict = field(default_factory=dict)
    option_underlyings: int = 0
    inserted: int = 0
    updated: int = 0
    delisted: int = 0

    def to_dict(self) -> dict:
        return {
            "refreshed_at": self.refreshed_at,
            "counts": self.counts,
            "states": self.states,
            "option_underlyings": self.option_underlyings,
            "inserted": self.inserted,
            "updated": self.updated,
            "delisted": self.delisted,
        }


class OkxPublicClient:
    """Minimal public-only OKX v5 client for the registry refresh path.

    Public endpoints only - no credentials, no trading, no account access.
    """

    def __init__(self, base_url: str = OKX_BASE_URL, timeout: float = DEFAULT_TIMEOUT,
                 transport=None):
        import httpx

        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def get_instruments(self, inst_type: str, uly: str | None = None) -> list[dict]:
        params: dict = {"instType": inst_type}
        if uly:
            params["uly"] = uly
        resp = self._client.get("/api/v5/public/instruments", params=params)
        resp.raise_for_status()
        payload = resp.json()
        if str(payload.get("code")) != "0":
            raise RuntimeError(f"okx instruments {inst_type} code={payload.get('code')}")
        return list(payload.get("data") or [])

    def get_option_underlyings(self, inst_type: str = "OPTION") -> list[str]:
        resp = self._client.get("/api/v5/public/underlying", params={"instType": inst_type})
        resp.raise_for_status()
        payload = resp.json()
        if str(payload.get("code")) != "0":
            return []
        data = payload.get("data") or []
        return [u for row in data for u in (row if isinstance(row, list) else [])]

    def close(self) -> None:
        self._client.close()


def fetch_registry_snapshot(
    client: OkxPublicClient | None = None,
    inst_types: tuple[str, ...] = INSTRUMENT_TYPES,
) -> tuple[list[InstrumentRecord], RegistrySnapshot, int]:
    """Fetch current instruments for the given product classes.

    Returns (records, snapshot, option_underlying_count). OPTION instruments
    are counted by underlying (research-only context) and NOT persisted
    row-by-row (thousands of dated contracts, no PAPER execution support).
    """
    own_client = client is None
    client = client or OkxPublicClient()
    try:
        records: list[InstrumentRecord] = []
        counts: dict[str, int] = {}
        for inst_type in inst_types:
            raw_rows = client.get_instruments(inst_type)
            counts[inst_type] = len(raw_rows)
            records.extend(InstrumentRecord.from_api(r) for r in raw_rows)
        option_underlyings = client.get_option_underlyings("OPTION")
        snapshot = RegistrySnapshot(
            refreshed_at=datetime.now(UTC).isoformat(),
            counts=counts,
            option_underlyings=len(option_underlyings),
        )
        return records, snapshot, len(option_underlyings)
    finally:
        if own_client:
            client.close()


def persist_registry_sync(
    db_path: str,
    records: list[InstrumentRecord],
    snapshot: RegistrySnapshot | None = None,
) -> RegistrySnapshot:
    """Upsert the fetched instruments into `okx_instruments`.

    - new instId -> INSERT (first_seen_at = now)
    - existing   -> UPDATE fields + last_seen_at/refreshed_at
    - previously seen instId absent from this refresh -> state='DELISTED'
      (kept as observation history; universe queries filter it out)
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_CREATE_TABLE)
        now = datetime.now(UTC).isoformat()
        existing = {
            r[0] for r in conn.execute("SELECT inst_id FROM okx_instruments").fetchall()
        }
        seen: set[str] = set()
        inserted = 0
        updated = 0
        for rec in records:
            if not rec.inst_id or rec.inst_id in seen:
                continue
            seen.add(rec.inst_id)
            vals = [getattr(rec, f) for f in _PERSIST_FIELDS]
            if rec.inst_id in existing:
                conn.execute(
                    "UPDATE okx_instruments SET "
                    + ", ".join(f"{f}=?" for f in _PERSIST_FIELDS[1:])
                    + ", last_seen_at=?, refreshed_at=? WHERE inst_id=?",
                    (*vals[1:], now, now, rec.inst_id),
                )
                updated += 1
            else:
                conn.execute(
                    f"INSERT INTO okx_instruments ({', '.join(_PERSIST_FIELDS)}, "
                    "first_seen_at, last_seen_at, refreshed_at) "
                    f"VALUES ({', '.join('?' for _ in range(len(_PERSIST_FIELDS) + 3))})",
                    (*vals, now, now, now),
                )
                inserted += 1
        delisted = 0
        if seen:
            gone = [i for i in existing if i not in seen]
            for inst_id in gone:
                conn.execute(
                    "UPDATE okx_instruments SET state='DELISTED', "
                    "last_seen_at=last_seen_at, refreshed_at=? WHERE inst_id=? "
                    "AND state!='DELISTED'",
                    (now, inst_id),
                )
            delisted = len(gone)
        conn.commit()
        states: dict[str, int] = {}
        for r in conn.execute(
            "SELECT inst_type, state, COUNT(*) FROM okx_instruments "
            "GROUP BY inst_type, state"
        ).fetchall():
            states[f"{r[0]}:{r[1]}"] = r[2]
        snap = snapshot or RegistrySnapshot(refreshed_at=now)
        snap.inserted, snap.updated, snap.delisted = inserted, updated, delisted
        snap.states = states
        return snap
    finally:
        conn.close()


def refresh_sync(db_path: str, client: OkxPublicClient | None = None) -> dict:
    """One-shot registry refresh: fetch + persist. Returns snapshot dict."""
    records, snapshot, option_count = fetch_registry_snapshot(client)
    snapshot.option_underlyings = option_count
    snap = persist_registry_sync(db_path, records, snapshot)
    return snap.to_dict()


def registry_stats_sync(db_path: str) -> dict:
    """Read-only universe stats from the persisted registry."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_CREATE_TABLE)
        stats: dict = {"total": 0, "live": {}, "delisted": 0, "by_type": {}}
        stats["total"] = conn.execute("SELECT COUNT(*) FROM okx_instruments").fetchone()[0]
        stats["delisted"] = conn.execute(
            "SELECT COUNT(*) FROM okx_instruments WHERE state='DELISTED'"
        ).fetchone()[0]
        for inst_type in INSTRUMENT_TYPES:
            live = conn.execute(
                "SELECT COUNT(*) FROM okx_instruments "
                "WHERE inst_type=? AND state='live'",
                (inst_type,),
            ).fetchone()[0]
            total = conn.execute(
                "SELECT COUNT(*) FROM okx_instruments WHERE inst_type=?",
                (inst_type,),
            ).fetchone()[0]
            stats["by_type"][inst_type] = {"live": live, "total": total}
            stats["live"][inst_type] = live
        last = conn.execute("SELECT MAX(refreshed_at) FROM okx_instruments").fetchone()[0]
        stats["last_refreshed_at"] = last
        return stats
    finally:
        conn.close()


def tradeable_universe_sync(
    db_path: str,
    inst_type: str = "SPOT",
    quote_ccy: str = "USDT",
    limit: int | None = None,
) -> list[str]:
    """Live instruments of a product class (universe membership source).

    Delisted/suspended instruments NEVER appear - no new trades can be
    generated for a delisted instrument (§52).
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_CREATE_TABLE)
        cur = conn.execute(
            "SELECT inst_id FROM okx_instruments WHERE inst_type=? AND state='live' "
            "AND (quote_ccy=? OR quote_ccy IS NULL) ORDER BY inst_id"
            + (f" LIMIT {int(limit)}" if limit else ""),
            (inst_type, quote_ccy),
        )
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
