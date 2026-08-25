"""Factor data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal


@dataclass
class FactorResult:
    factor_name: str
    symbol: str
    timeframe: str
    value: Decimal
    confidence: Decimal
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "factor_name": self.factor_name,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "value": str(self.value),
            "confidence": str(self.confidence),
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class FactorSnapshot:
    symbol: str
    timeframe: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    factors: dict[str, Decimal] = field(default_factory=dict)
    confidence: dict[str, Decimal] = field(default_factory=dict)
    market_state: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "factors": {k: str(v) for k, v in self.factors.items()},
            "confidence": {k: str(v) for k, v in self.confidence.items()},
            "market_state": self.market_state,
        }


@dataclass
class FactorPerformance:
    factor_name: str
    symbol: str
    timeframe: str
    sample_size: int
    win_rate: Decimal
    average_return: Decimal
    sharpe: Decimal
    max_drawdown: Decimal
    profit_factor: Decimal
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "factor_name": self.factor_name,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "sample_size": self.sample_size,
            "win_rate": str(self.win_rate),
            "average_return": str(self.average_return),
            "sharpe": str(self.sharpe),
            "max_drawdown": str(self.max_drawdown),
            "profit_factor": str(self.profit_factor),
            "timestamp": self.timestamp,
        }


@dataclass
class FactorHealth:
    factor_name: str
    symbol: str
    status: str  # EXPERIMENTAL | TESTING | HEALTHY | DEGRADING | RETIRED
    sample_size: int = 0
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "factor_name": self.factor_name,
            "symbol": self.symbol,
            "status": self.status,
            "sample_size": self.sample_size,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


@dataclass
class FactorAttributionResult:
    trade_id: str
    result: str
    contributors: dict[str, Decimal]
    negative: dict[str, Decimal]
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "result": self.result,
            "contributors": {k: str(v) for k, v in self.contributors.items()},
            "negative": {k: str(v) for k, v in self.negative.items()},
            "timestamp": self.timestamp,
        }


@dataclass
class FactorDecayResult:
    factor_name: str
    symbol: str
    status: str
    old_performance: Decimal
    new_performance: Decimal
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "factor_name": self.factor_name,
            "symbol": self.symbol,
            "status": self.status,
            "old_performance": str(self.old_performance),
            "new_performance": str(self.new_performance),
            "reason": self.reason,
            "timestamp": self.timestamp,
        }
