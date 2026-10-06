"""Typed exit provenance from existing durable decisions, intents and fills.

No LLM decision is invented for a deterministic protection. Legacy recovery
can consume the existing producer audit only when all factual links agree.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.persistence.models import (
    AuditEventORM,
    FillORM,
    LedgerTransactionORM,
    LLMDecisionORM,
    OrderORM,
    RiskDecisionORM,
)

DETERMINISTIC_EXIT_AUTHORITIES = frozenset(
    {
        "FAST_PROFIT_PROTECTION",
        "RISK_HARD_EXIT",
        "OFFLINE_HARD_EXIT",
        "ACTIVE_BASE_EXIT",
    }
)


@dataclass(frozen=True)
class ExitDecisionEvidence:
    decision_id: str
    source: str
    trade_plan_id: str
    entry_decision_id: str
    order_id: str | None = None
    intent_audit_id: str | None = None


async def resolve_exit_evidence(session, plan, decision_id: str) -> ExitDecisionEvidence:
    chief = await session.get(LLMDecisionORM, decision_id)
    if chief is not None:
        if (
            chief.position_state != "OPEN"
            or chief.original_trade_plan_id != plan.trade_plan_id
            or chief.original_entry_decision_id != plan.decision_id
        ):
            raise ValueError("factual close requires canonical OPEN decision lineage")
        return ExitDecisionEvidence(decision_id, "LLM_CHIEF", plan.trade_plan_id, plan.decision_id)

    entry = await session.get(LLMDecisionORM, plan.decision_id)
    if (
        entry is None
        or entry.symbol != plan.symbol
        or entry.action not in {"LONG", "SHORT", "HEDGE", "REVERSE"}
    ):
        raise ValueError("EXIT_PROVENANCE_ENTRY_MISSING_OR_INVALID")

    orders = (
        (
            await session.execute(
                select(OrderORM).where(
                    OrderORM.symbol == plan.symbol,
                    OrderORM.metadata_json["decision_id"].as_string() == decision_id,
                    OrderORM.metadata_json["trade_plan_id"].as_string() == plan.trade_plan_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if len(orders) != 1:
        raise ValueError("EXIT_PROVENANCE_ORDER_MISSING_OR_AMBIGUOUS")
    order = orders[0]
    meta = order.metadata_json or {}
    source = meta.get("exit_authority")
    request = meta.get("exit_request_id")
    expected_side = "SELL" if plan.direction == "LONG" else "BUY"
    if (
        meta.get("deterministic_exit") is not True
        or meta.get("reduce_only") is not True
        or source not in DETERMINISTIC_EXIT_AUTHORITIES
        or not isinstance(request, str)
        or not request
        or decision_id != "det_" + request
        or order.side != expected_side
        or order.status != "FILLED"
        or order.filled_quantity <= 0
    ):
        raise ValueError("EXIT_PROVENANCE_ORDER_INVALID")
    intent_query = select(AuditEventORM).where(
        AuditEventORM.client_order_id == order.client_order_id,
        AuditEventORM.action == "DETERMINISTIC_EXIT_INTENT",
        AuditEventORM.actor == "engine",
    )
    if "exit_intent_audit_id" in meta:
        pointer = meta["exit_intent_audit_id"]
        if not isinstance(pointer, str) or not pointer:
            raise ValueError("EXIT_PROVENANCE_INTENT_POINTER_INVALID")
        intent_query = intent_query.where(AuditEventORM.audit_event_id == pointer)
    # Only old orders lacking the pointer use the original lookup. A present
    # but bad pointer must never fall back to a different record.
    intents = (await session.execute(intent_query)).scalars().all()
    if len(intents) != 1:
        raise ValueError("EXIT_PROVENANCE_INTENT_MISSING_OR_AMBIGUOUS")
    intent = intents[0]
    fact = intent.after_json or {}
    try:
        requested_quantity = Decimal(str(fact.get("quantity")))
    except Exception as exc:
        raise ValueError("EXIT_PROVENANCE_QUANTITY_INVALID") from exc
    if (
        fact.get("reservation_request_id") != request
        or fact.get("authority") != source
        or fact.get("symbol") != plan.symbol
        or fact.get("side") != plan.direction
        or fact.get("is_new_risk") is not False
        or not meta.get("state_version")
        or fact.get("state_version") != meta["state_version"]
        or fact.get("leg_id") != (meta.get("leg_id") or plan.trade_plan_id)
        or not requested_quantity.is_finite()
        or requested_quantity != order.quantity
    ):
        raise ValueError("EXIT_PROVENANCE_INTENT_INVALID")
    risk_id = meta.get("risk_decision_id")
    risk = await session.get(RiskDecisionORM, risk_id) if isinstance(risk_id, str) else None
    if (
        risk is None
        or risk.decision not in {"APPROVE", "SCALE_DOWN"}
        or risk.symbol != order.symbol
        or risk.side != order.side
        # Risk checks the SignalIntent; order client IDs add the strategy
        # prefix. Bind the factual signal ID, not a guessed string alias.
        or not meta.get("signal_id")
        or risk.client_order_id != meta["signal_id"]
    ):
        raise ValueError("EXIT_PROVENANCE_RISK_INVALID")
    fills = (
        (await session.execute(select(FillORM).where(FillORM.order_id == order.internal_order_id)))
        .scalars()
        .all()
    )
    if not fills or sum((f.quantity for f in fills), Decimal("0")) != order.filled_quantity:
        raise ValueError("EXIT_PROVENANCE_FILLS_INVALID")
    for fill in fills:
        transactions = (
            (
                await session.execute(
                    select(LedgerTransactionORM.transaction_id).where(
                        LedgerTransactionORM.fill_id == fill.fill_id,
                        LedgerTransactionORM.order_id == order.internal_order_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(transactions) != 1:
            raise ValueError("EXIT_PROVENANCE_LEDGER_MISSING_OR_AMBIGUOUS")
    return ExitDecisionEvidence(
        decision_id,
        source,
        plan.trade_plan_id,
        plan.decision_id,
        order.internal_order_id,
        intent.audit_event_id,
    )
