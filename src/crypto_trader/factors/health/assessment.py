"""Deterministic factor health assessment from legacy FactorResult captures.

Policy (code, not LLM):
- a real numerical zero with usable confidence is ``VALID_ZERO``;
- legacy unavailable-channel markers (``NO_BOOK``/``NO_TRADES``, confidence 0)
  map to ``MISSING_DATA`` and never produce a fake ``Decimal(0)``;
- calculation errors surface as ``CALCULATION_FAILED`` with the cause recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.factors.health.states import ALL_STATES, FactorHealthState
from crypto_trader.factors.models import FactorResult

# Legacy capture metadata marks for "the input channel had no data".
LEGACY_NO_DATA_STATUSES: frozenset[str] = frozenset({"NO_BOOK", "NO_TRADES"})


@dataclass(frozen=True)
class FactorHealthAssessment:
    factor_name: str
    state: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.state not in ALL_STATES:
            raise ValueError(f"unknown factor health state: {self.state!r}")

    def is_usable(self) -> bool:
        return self.state in (FactorHealthState.OK, FactorHealthState.VALID_ZERO)

    def to_dict(self) -> dict:
        return {
            "factor_name": self.factor_name,
            "state": self.state,
            "detail": self.detail,
        }


def failure_assessment(factor_name: str, detail: str) -> FactorHealthAssessment:
    return FactorHealthAssessment(
        factor_name=factor_name, state=FactorHealthState.CALCULATION_FAILED, detail=detail
    )


def insufficient_history_assessment(factor_name: str) -> FactorHealthAssessment:
    return FactorHealthAssessment(
        factor_name=factor_name, state=FactorHealthState.INSUFFICIENT_HISTORY
    )


def stale_input_assessment(factor_name: str, detail: str = "") -> FactorHealthAssessment:
    return FactorHealthAssessment(
        factor_name=factor_name, state=FactorHealthState.STALE_INPUT, detail=detail
    )


def report_from_legacy_result(result: FactorResult) -> FactorHealthAssessment:
    """Map a legacy ``FactorResult`` onto the explicit health states.

    Mapping rules, applied in order:

    1. legacy metadata channel status in {NO_BOOK, NO_TRADES} -> MISSING_DATA;
    2. value or confidence absent/unreadable     -> CALCULATION_FAILED / MISSING_DATA;
    3. confidence <= 0                            -> MISSING_DATA (legacy zero-confidence
       captures mean the channel was unavailable even when a placeholder zero was set);
    4. real Decimal(0) with positive confidence   -> VALID_ZERO;
    5. otherwise                                  -> OK.
    """
    metadata = result.metadata or {}
    legacy_status = str(metadata.get("status", "")).upper()
    if legacy_status in LEGACY_NO_DATA_STATUSES:
        return FactorHealthAssessment(
            factor_name=result.factor_name,
            state=FactorHealthState.MISSING_DATA,
            detail=legacy_status,
        )
    value = result.value
    if not isinstance(value, Decimal):
        return failure_assessment(result.factor_name, "NULL_VALUE")
    confidence = result.confidence
    if not isinstance(confidence, Decimal):
        return FactorHealthAssessment(
            factor_name=result.factor_name,
            state=FactorHealthState.MISSING_DATA,
            detail="CONFIDENCE_MISSING",
        )
    if confidence <= Decimal("0"):
        detail = f"LEGACY_CONFIDENCE_0:{legacy_status}" if legacy_status else "LEGACY_CONFIDENCE_0"
        return FactorHealthAssessment(
            factor_name=result.factor_name, state=FactorHealthState.MISSING_DATA, detail=detail
        )
    if value == Decimal("0"):
        return FactorHealthAssessment(
            factor_name=result.factor_name, state=FactorHealthState.VALID_ZERO
        )
    return FactorHealthAssessment(factor_name=result.factor_name, state=FactorHealthState.OK)
