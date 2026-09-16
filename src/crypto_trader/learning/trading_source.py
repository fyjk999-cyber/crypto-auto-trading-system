# Read-only Growth trading source adapter (no source mutation).
from __future__ import annotations

import sqlite3
from pathlib import Path

CONTRACT_TABLE = "growth_lifecycle_events"


class GrowthTradingSource:
    def __init__(self, db_path: str | None) -> None:
        self.db_path = db_path

    def available(self) -> bool:
        return bool(self.db_path and Path(self.db_path).exists())

    def has_contract(self) -> bool:
        if not self.available():
            return False
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (CONTRACT_TABLE,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def events_after(self, cursor: int, limit: int = 100) -> list[dict]:
        if not self.has_contract():
            return []
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                f"SELECT * FROM {CONTRACT_TABLE} WHERE id > ? ORDER BY id LIMIT ?",
                (int(cursor), int(limit)),
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]
