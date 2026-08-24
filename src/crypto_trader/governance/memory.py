from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum


class FailureClass(str, Enum):
    REGIME_ERROR = "REGIME_ERROR"
    SIGNAL_ERROR = "SIGNAL_ERROR"
    CONFIDENCE_ERROR = "CONFIDENCE_ERROR"
    TIMING_ERROR = "TIMING_ERROR"
    POSITION_SIZE_ERROR = "POSITION_SIZE_ERROR"
    LEVERAGE_ERROR = "LEVERAGE_ERROR"
    LIQUIDITY_ERROR = "LIQUIDITY_ERROR"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    FUNDING_ERROR = "FUNDING_ERROR"
    CORRELATION_ERROR = "CORRELATION_ERROR"
    DATA_ERROR = "DATA_ERROR"
    EXCHANGE_ERROR = "EXCHANGE_ERROR"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    MARKET_SHOCK = "MARKET_SHOCK"


@dataclass
class TradeMemoryRecord:
    decision_id: str
    symbol: str
    side: str
    regime: str
    strategy_scores: dict
    effective_weights: dict
    raw_confidence: Decimal
    calibrated_confidence: Decimal
    recommended_position: Decimal
    approved_position: Decimal
    recommended_leverage: Decimal
    approved_leverage: Decimal
    entry: Decimal | None = None
    exit: Decimal | None = None
    mae: Decimal = Decimal("0")
    mfe: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    funding_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal | None = None
    r_multiple: Decimal = Decimal("0")
    failure_class: FailureClass | None = None
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))


class TradeMemory:
    def __init__(self) -> None:
        self.records: list[TradeMemoryRecord] = []

    def record(self, record: TradeMemoryRecord) -> None:
        self.records.append(record)

    def all(self) -> list[TradeMemoryRecord]:
        return list(self.records)

    def similar(
        self,
        symbol: str | None = None,
        side: str | None = None,
        regime: str | None = None,
        min_sample: int = 5,
    ) -> dict:
        rows = [
            r
            for r in self.records
            if (symbol is None or r.symbol == symbol)
            and (side is None or r.side == side)
            and (regime is None or r.regime == regime)
        ]
        if len(rows) < min_sample:
            return {"sample_count": len(rows), "status": "INSUFFICIENT_DATA"}
        wins = [r for r in rows if (r.realized_pnl or Decimal("0")) > 0]
        pnls = [r.realized_pnl for r in rows if r.realized_pnl is not None]
        win_rate = Decimal(len(wins)) / Decimal(len(rows)) if rows else Decimal("0")
        expectancy = sum(pnls, Decimal("0")) / Decimal(len(pnls)) if pnls else Decimal("0")
        avg_r = (
            sum((r.r_multiple for r in rows), Decimal("0")) / Decimal(len(rows))
            if rows
            else Decimal("0")
        )
        worst_r = min((r.r_multiple for r in rows), default=Decimal("0"))
        failure_dist = {
            cls.value: sum(1 for r in rows if r.failure_class == cls) for cls in FailureClass
        }
        return {
            "sample_count": len(rows),
            "status": "OK",
            "historical_win_rate": win_rate,
            "expectancy": expectancy,
            "average_R": avg_r,
            "worst_R": worst_r,
            "failure_distribution": failure_dist,
        }


class FailureMemory:
    def __init__(self) -> None:
        self.failures: list[tuple[str, FailureClass]] = []

    def record(self, decision_id: str, failure_class: FailureClass) -> None:
        self.failures.append((decision_id, failure_class))

    def distribution(self) -> dict[str, int]:
        dist: dict[str, int] = {}
        for _, cls in self.failures:
            dist[cls.value] = dist.get(cls.value, 0) + 1
        return dist

    def confidence_penalty(self, failure_class: FailureClass) -> Decimal:
        count = sum(1 for _, cls in self.failures if cls == failure_class)
        return min(Decimal(count) * Decimal("0.05"), Decimal("0.30"))
