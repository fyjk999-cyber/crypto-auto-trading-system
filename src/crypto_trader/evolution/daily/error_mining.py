"""Error mining and clustering."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ErrorEvent:
    decision_id: str
    category: str
    avoidable: bool
    evidence: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "category": self.category,
            "avoidable": self.avoidable,
            "evidence": self.evidence,
        }


def classify_decision_quality(*, decision_quality: str, outcome_quality: str) -> str:
    return f"{decision_quality}_{outcome_quality}"


def mine_error(
    *,
    decision_quality: str,
    outcome_quality: str,
    rule_violation: bool = False,
    factor_conflict: bool = False,
    market_shock: bool = False,
) -> ErrorEvent | None:
    if rule_violation:
        return ErrorEvent("", "RULE_VIOLATION", True, ["deterministic rule broken"])
    if decision_quality == "BAD" and outcome_quality == "BAD":
        if factor_conflict:
            return ErrorEvent("", "FACTOR_CONFLICT", True, ["conflicting factors"])
        return ErrorEvent("", "SIGNAL_ERROR", True, ["bad decision realized"])
    if decision_quality == "BAD" and outcome_quality == "GOOD":
        return ErrorEvent("", "BAD_DECISION_GOOD_OUTCOME", False, ["luck not a system error"])
    if decision_quality == "GOOD" and outcome_quality == "BAD":
        if market_shock:
            return ErrorEvent("", "MARKET_SHOCK", False, ["unavoidable market shock"])
        return None  # normal stochastic loss is not an error
