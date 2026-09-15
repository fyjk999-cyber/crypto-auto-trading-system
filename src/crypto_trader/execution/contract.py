"""V2 execution terms: Core LLM owns size/leverage (Low-Risk V2 Phase 4H).

Adapts the historical Risk -> APPROVE/SCALE_DOWN coupling:

  * V2 entries (plan_version >= 2) carry the LLM's capital allocation and
    leverage into execution unchanged. Risk may still REJECT on hard safety
    state, but it never silently shrinks an LLM trade. Execution validates the
    constitutional contract (<=25% child / <=20x / Base Exit) and rejects
    invalid orders instead of resizing them.
  * Legacy entries and all reduce/close actions keep the historical behavior
    so existing canonical callers and tests remain valid.

This module performs no I/O and cannot submit an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from crypto_trader.domain.enums import ExecutionDecision
from crypto_trader.domain.models import RiskDecision, SignalIntent
from crypto_trader.execution.authority import NewRiskOrderContract
from crypto_trader.trade_plan.service import TradePlan


def plan_contract_version(metadata: dict | None) -> int:
    try:
        return int((metadata or {}).get("plan_version", 1) or 1)
    except (TypeError, ValueError):
        return 1


def _to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


@dataclass(slots=True)
class ExecutionTerms:
    quantity: Decimal
    leverage: str
    order_contract: NewRiskOrderContract | None
    risk_observation: dict = field(default_factory=dict)


def derive_execution_terms(
    *,
    is_entry: bool,
    signal: SignalIntent,
    plan: TradePlan | None,
    risk_decision: RiskDecision,
) -> ExecutionTerms:
    """Resolve executable quantity/leverage and the V2 contract (if any)."""
    metadata = signal.metadata or {}
    requested_leverage = str(metadata.get("requested_leverage", "1"))
    v2 = plan_contract_version(metadata) >= 2 and plan is not None
    if not v2:
        if not (is_entry and plan is not None):
            # Reduces/exits on legacy plans keep the legacy observation path.
            quantity = signal.quantity
            leverage = str(risk_decision.checks.get("approved_leverage", requested_leverage))
            if risk_decision.decision == ExecutionDecision.SCALE_DOWN:
                approved_quantity = _to_decimal(risk_decision.checks.get("approved_quantity"))
                if approved_quantity is not None and approved_quantity > 0:
                    quantity = approved_quantity
            return ExecutionTerms(
                quantity=quantity,
                leverage=leverage,
                order_contract=None,
                risk_observation={
                    "mode": "LEGACY_RISK_APPROVAL",
                    "risk_decision": risk_decision.decision.value,
                    "risk_reason": risk_decision.reason,
                },
            )
        # Constitution: a legacy-format Core LLM decision may still create new
        # risk ONLY through the same hard contract. Missing Base Exit or
        # missing/oversized allocation is rejected, never resized.

    base_exit_present = bool(plan.base_exit) or bool(metadata.get("base_exit"))
    contract = NewRiskOrderContract(
        is_new_risk=True,
        capital_allocation_pct=_to_decimal(metadata.get("capital_allocation_pct")),
        leverage=_to_decimal(requested_leverage),
        base_exit_present=base_exit_present,
        strategy=str(plan.strategy or metadata.get("strategy") or ""),
        based_on_state_version=plan.based_on_state_version,
    )
    observation = {
        "mode": (
            "V2_LLM_OWNS_SIZE_AND_LEVERAGE"
            if v2
            else "V2_HARD_CONTRACT_APPLIED_TO_LEGACY_PLAN"
        ),
        "risk_decision": risk_decision.decision.value,
        "risk_reason": risk_decision.reason,
        "requested_quantity": str(signal.quantity),
        "requested_leverage": requested_leverage,
        "capital_allocation_pct": str(contract.capital_allocation_pct),
        "scaled_by_risk": False,
    }
    # Risk may still hard-REJECT (kill switch, hard limits). It may not resize.
    return ExecutionTerms(
        quantity=signal.quantity,
        leverage=requested_leverage,
        order_contract=contract,
        risk_observation=observation,
    )
