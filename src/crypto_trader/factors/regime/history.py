"""Regime history in-memory helper."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RegimeHistory:
    records: list[dict] = field(default_factory=list)

    def add(self, regime: dict) -> None:
        self.records.append(regime)

    def latest(self, symbol: str | None = None) -> dict | None:
        for record in reversed(self.records):
            if symbol is None or record.get("symbol") == symbol:
                return record
        return None

    def distribution(self, symbol: str | None = None) -> dict[str, int]:
        out: dict[str, int] = {}
        for record in self.records:
            if symbol is not None and record.get("symbol") != symbol:
                continue
            regime = record.get("regime", "UNKNOWN")
            out[regime] = out.get(regime, 0) + 1
        return out
