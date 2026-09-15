"""Low-Risk V2 hedge leg contract (Phase 4D).

SPEC: LONG and SHORT may coexist on the same symbol, but the opposite leg must
carry its own strategy, model-family evidence, thesis, Base Exit and invalidation.
Merely "reducing the original position's loss" is not a legal hedge reason.

This is a deterministic validation / book-keeping layer. It never submits an
order: every hedge/reverse is still NEW RISK and must come from the Core LLM and
pass the canonical TradePlan + ExecutionAuthority path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class LegKind(StrEnum):
    ENTRY = "ENTRY"
    ADD = "ADD"
    HEDGE = "HEDGE"
    REVERSE = "REVERSE"


ILLEGAL_HEDGE_REASON_TOKENS = (
    "减少原仓亏损",
    "降低原仓亏损",
    "对冲原仓亏损",
    "cover the loss",
    "cover loss",
    "reduce the loss",
    "reduce loss",
    "offset the loss",
    "offset loss",
    "avoid admitting",
)


@dataclass
class HedgeLegContract:
    leg_id: str
    symbol: str
    side: str  # LONG | SHORT
    kind: LegKind
    strategy: str
    thesis: str
    base_exit: dict | None
    invalidation: str | None
    evidence_families: list[str] = field(default_factory=list)
    reason: str = ""
    reverse_of: str | None = None
    authority: str = "NEW_RISK_REQUIRES_CORE_LLM"
    is_order: bool = False

    @property
    def label(self) -> str:
        return "HEDGE_LEG_CONTRACT"


@dataclass
class LegValidation:
    allowed: bool
    violations: list[str]
    authority: str = "NEW_RISK_REQUIRES_CORE_LLM"
    is_order: bool = False


def validate_hedge_leg(
    contract: HedgeLegContract, existing: list[HedgeLegContract]
) -> LegValidation:
    violations: list[str] = []
    if not contract.strategy.strip():
        violations.append("MISSING_STRATEGY")
    if not contract.thesis.strip():
        violations.append("MISSING_INDEPENDENT_THESIS")
    if not contract.base_exit:
        violations.append("MISSING_BASE_EXIT")
    if not (contract.invalidation or "").strip():
        violations.append("MISSING_INVALIDATION")
    if not contract.evidence_families:
        violations.append("MISSING_EVIDENCE_FAMILIES")

    opposite = [
        leg
        for leg in existing
        if leg.symbol == contract.symbol and leg.side != contract.side
    ]
    needs_independence = contract.kind in {LegKind.HEDGE, LegKind.REVERSE} or bool(opposite)
    if needs_independence:
        reason = contract.reason.lower()
        if any(token.lower() in reason for token in ILLEGAL_HEDGE_REASON_TOKENS):
            violations.append("ILLEGAL_HEDGE_REASON_LOSS_MITIGATION_ONLY")
        for leg in opposite:
            if leg.strategy == contract.strategy:
                violations.append("SAME_STRATEGY_NOT_INDEPENDENT")
            if leg.thesis.strip().lower() == contract.thesis.strip().lower():
                violations.append("DUPLICATE_THESIS_NOT_INDEPENDENT")
        if not contract.reverse_of and contract.kind == LegKind.REVERSE:
            violations.append("REVERSE_MISSING_SOURCE_LEG")
    return LegValidation(allowed=not violations, violations=violations)


class HedgeLegRegistry:
    """Tracks factual legs so opposite-side independence can be verified."""

    def __init__(self) -> None:
        self._legs: dict[str, HedgeLegContract] = {}

    def register(self, contract: HedgeLegContract) -> LegValidation:
        validation = validate_hedge_leg(contract, list(self._legs.values()))
        if validation.allowed:
            self._legs[contract.leg_id] = contract
        return validation

    def legs_for(self, symbol: str) -> list[HedgeLegContract]:
        return [leg for leg in self._legs.values() if leg.symbol == symbol]

    def has_opposite(self, symbol: str, side: str) -> bool:
        return any(leg.symbol == symbol and leg.side != side for leg in self._legs.values())

    def snapshot(self, symbol: str | None = None) -> dict:
        legs = (
            self.legs_for(symbol) if symbol is not None else list(self._legs.values())
        )
        return {
            "legs": [
                {
                    "leg_id": leg.leg_id,
                    "symbol": leg.symbol,
                    "side": leg.side,
                    "kind": leg.kind.value,
                    "strategy": leg.strategy,
                    "has_base_exit": bool(leg.base_exit),
                    "has_invalidation": bool(leg.invalidation),
                    "evidence_families": list(leg.evidence_families),
                }
                for leg in legs
            ],
            "both_sides": (
                {leg.side for leg in legs} == {"LONG", "SHORT"} if legs else False
            ),
            "authority": "NEW_RISK_REQUIRES_CORE_LLM",
            "not_an_order": True,
        }
