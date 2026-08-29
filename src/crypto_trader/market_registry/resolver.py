"""Canonical instrument resolver (Phase B §6: canonical symbol layer).

Single place where OKX exchange ids, canonical spot ids, execution ids and
reference-market ids are related - driven by the persisted registry, not by
scattered string surgery.

Layers (per long-goal §6):
- canonical:   BTCUSDT              (strategy/canonical layer)
- okx spot:    BTC-USDT             (exchange instrument id)
- okx swap:    BTC-USDT-SWAP        (perp execution id on OKX)
- reference:   BTCUSDT              (spot book used for perp marks)

The resolver NEVER invents a mapping: `to_swap`/`to_okx_spot` require the
target instrument to exist and be live in the registry (when a db_path is
given). Without a registry (pure string relation) the class works but the
runtime SHOULD always pass the registry path.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

_CREATE = (
    "CREATE TABLE IF NOT EXISTS okx_instruments ("
    "inst_id VARCHAR(64) PRIMARY KEY, inst_type VARCHAR(16), state VARCHAR(16))"
)


def _live_ok(db_path: str | None, inst_id: str, inst_type: str) -> bool:
    if db_path is None:
        return True  # no registry attached: relation-only mode
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_CREATE)
        row = conn.execute(
            "SELECT state FROM okx_instruments WHERE inst_id=? AND inst_type=?",
            (inst_id, inst_type),
        ).fetchone()
        return row is not None and row[0] == "live"
    finally:
        conn.close()


@dataclass(frozen=True)
class SymbolTriple:
    canonical: str
    okx_spot: str
    okx_swap: str


class InstrumentResolver:
    """Canonical <-> OKX instrument resolution (registry-checked)."""

    def __init__(self, db_path: str | None = None):
        self._db = db_path

    def from_okx(self, okx_inst_id: str) -> str:
        """BTC-USDT / BTC-USDT-SWAP -> BTCUSDT (canonical spot)."""
        base = okx_inst_id.split("-")[0]
        quote = "USDT"
        parts = okx_inst_id.split("-")
        if len(parts) >= 2 and parts[1]:
            quote = parts[1]
        return f"{base}{quote}"

    def to_okx_spot(self, canonical: str, *, require_live: bool = True) -> str:
        inst_id = self._swapless_spot_id(canonical)
        if require_live and not _live_ok(self._db, inst_id, "SPOT"):
            raise KeyError(f"okx spot instrument not live: {inst_id}")
        return inst_id

    def to_okx_swap(self, canonical: str, *, require_live: bool = True) -> str:
        inst_id = f"{self._base(canonical)}-{self._quote(canonical)}-SWAP"
        if require_live and not _live_ok(self._db, inst_id, "SWAP"):
            raise KeyError(f"okx swap instrument not live: {inst_id}")
        return inst_id

    def reference_symbol(self, canonical_or_execution: str) -> str:
        """Reference (spot book) symbol for marks: BTC-USDT-SWAP -> BTCUSDT."""
        return self.from_okx(canonical_or_execution)

    def triple(self, canonical: str) -> SymbolTriple:
        return SymbolTriple(
            canonical=canonical,
            okx_spot=self.to_okx_spot(canonical, require_live=False),
            okx_swap=self.to_okx_swap(canonical, require_live=False),
        )

    @staticmethod
    def _base(canonical: str) -> str:
        return canonical[:-4] if canonical.endswith("USDT") else canonical.split("-")[0]

    @staticmethod
    def _quote(canonical: str) -> str:
        return canonical[-4:] if canonical.endswith("USDT") else "USDT"

    def _swapless_spot_id(self, canonical: str) -> str:
        return f"{self._base(canonical)}-{self._quote(canonical)}"
