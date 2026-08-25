"""Market anomaly models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class MarketAnomaly:
    type: str
    symbol: str
    severity: float
    evidence: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "symbol": self.symbol,
            "severity": self.severity,
            "evidence": self.evidence,
            "timestamp": self.timestamp,
        }
