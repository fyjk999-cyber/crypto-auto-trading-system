"""Anomaly history."""

from __future__ import annotations

from dataclasses import dataclass, field

from crypto_trader.factors.anomaly.models import MarketAnomaly


@dataclass
class AnomalyHistory:
    records: list[dict] = field(default_factory=list)

    def add(self, anomaly: MarketAnomaly) -> None:
        self.records.append(anomaly.to_dict())

    def latest(self, symbol: str | None = None, top_k: int = 10) -> list[dict]:
        out = [r for r in self.records if symbol is None or r.get("symbol") == symbol]
        return out[-top_k:]

    def count(self) -> int:
        return len(self.records)
