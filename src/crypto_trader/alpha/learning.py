"""Fast and Slow Learning.

Fast Learning updates statistics only (performance, confidence calibration,
failure memory, regime stats). It never mutates production strategy parameters.

Slow Learning candidate parameters/weights must pass:
backtest -> out-of-sample -> walk-forward -> shadow -> promotion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from crypto_trader.domain.money import D


class SlowStage(str, Enum):
    BACKTEST = "BACKTEST"
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"
    WALK_FORWARD = "WALK_FORWARD"
    SHADOW = "SHADOW"
    PROMOTION = "PROMOTION"
    REJECTED = "REJECTED"


VALID_PROMOTION_ORDER = [
    SlowStage.BACKTEST,
    SlowStage.OUT_OF_SAMPLE,
    SlowStage.WALK_FORWARD,
    SlowStage.SHADOW,
    SlowStage.PROMOTION,
]


@dataclass
class SlowCandidate:
    id: str
    strategy: str
    parameter_json: dict
    evidence: list[str] = field(default_factory=list)
    status: str = "PROPOSED"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class FastLearning:
    def __init__(self) -> None:
        self.performance: dict[str, list[Decimal]] = {}
        self.confidence_cal: dict[tuple[str, str], Decimal] = {}
        self.failure_memory: dict[str, int] = {}
        self.regime_stats: dict[str, int] = {}

    def record_trade(self, strategy: str, side: str, pnl, confidence: str | Decimal = "0") -> None:
        self.performance.setdefault(strategy, []).append(D(pnl))
        # exponential moving calibration: positive pnl raises confidence, negative lowers
        key = (strategy, side)
        delta = D("0.02") if D(pnl) > 0 else D("-0.04")
        current = self.confidence_cal.get(key, D("0"))
        self.confidence_cal[key] = max(D("-0.25"), min(D("0.25"), current + delta))
        if D(pnl) < 0:
            self.failure_memory[strategy] = self.failure_memory.get(strategy, 0) + 1

    def record_regime(self, regime: str) -> None:
        self.regime_stats[regime] = self.regime_stats.get(regime, 0) + 1

    def strategy_score(self, strategy: str) -> Decimal | None:
        values = self.performance.get(strategy)
        if not values:
            return None
        # bounded average pnl score as a small weight prior
        avg = sum(values, D("0")) / Decimal(len(values))
        return max(D("-0.10"), min(D("0.10"), avg))

    def confidence_calibration(self, strategy: str, side: str) -> Decimal:
        return self.confidence_cal.get((strategy, side), D("0"))

    def failure_count(self, strategy: str) -> int:
        return self.failure_memory.get(strategy, 0)

    def snapshot(self) -> dict:
        return {
            "performance": {k: [str(v) for v in vals] for k, vals in self.performance.items()},
            "confidence_cal": {f"{k[0]}:{k[1]}": str(v) for k, v in self.confidence_cal.items()},
            "failure_memory": dict(self.failure_memory),
            "regime_stats": dict(self.regime_stats),
        }


class SlowLearning:
    def __init__(self) -> None:
        self.candidates: dict[str, SlowCandidate] = {}
        self.promoted: dict[str, dict] = {}

    def propose(self, candidate_id: str, strategy: str, parameter_json: dict) -> SlowCandidate:
        candidate = SlowCandidate(id=candidate_id, strategy=strategy, parameter_json=parameter_json)
        self.candidates[candidate_id] = candidate
        return candidate

    def add_evidence(self, candidate_id: str, stage: SlowStage, result: dict) -> SlowCandidate:
        candidate = self.candidates[candidate_id]
        if stage == SlowStage.REJECTED:
            candidate.status = SlowStage.REJECTED.value
            candidate.evidence.append(stage.value)
            return candidate
        expected_index = len([e for e in candidate.evidence if e != SlowStage.REJECTED.value])
        if stage not in VALID_PROMOTION_ORDER:
            candidate.status = SlowStage.REJECTED.value
            candidate.evidence.append(stage.value)
            return candidate
        if stage != VALID_PROMOTION_ORDER[expected_index]:
            candidate.status = SlowStage.REJECTED.value
            candidate.evidence.append(f"INVALID_ORDER:{stage.value}")
            return candidate
        candidate.evidence.append(stage.value)
        candidate.parameter_json = {**candidate.parameter_json, **result}
        if stage == SlowStage.PROMOTION:
            candidate.status = "PROMOTED"
        return candidate

    def promote(self, candidate_id: str, strategy: str) -> dict:
        candidate = self.candidates[candidate_id]
        if candidate.status != "PROMOTED":
            raise ValueError("slow learning candidate not validated for promotion")
        promoted = {
            "strategy": strategy,
            "parameters": candidate.parameter_json,
            "evidence": candidate.evidence,
            "promoted_at": datetime.now(UTC).isoformat(),
        }
        self.promoted[candidate_id] = promoted
        return promoted
