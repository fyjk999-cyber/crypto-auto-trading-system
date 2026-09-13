"""POSITION SIZING V2 PATCH — ADD safety at the integration boundaries.

These tests prove the three things that must be true while auto scale-in stays
DISABLED:

1. ``ADD`` as a position-review action is REFUSED and is never silently
   converted into a REDUCE (which would invert its intent).
2. A future ``POSITION_ADD`` order has its own order purpose and can never be
   classified as a plain ``ENTRY`` (so entry-only rules cannot touch it).
3. Nothing in the runtime creates an ADD order, however the risk verdict goes.

No order is created anywhere in this module.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from crypto_trader.llm_chief.decision import ChiefTraderDecision, OpenAction, PositionState
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
from crypto_trader.observability.audit import AuditService
from crypto_trader.order.entry_ttl import (
    ACTION_NOT_APPLICABLE,
    evaluate_entry_ttl,
)
from crypto_trader.order.reconciliation import (
    ORDER_PURPOSE_ENTRY,
    ORDER_PURPOSE_OTHER,
    ORDER_PURPOSE_POSITION_ADD,
    ORDER_PURPOSE_POSITION_EXIT,
    ORDER_PURPOSE_POSITION_REDUCE,
    ORDER_PURPOSES,
    classify_order_purpose,
)
from crypto_trader.persistence.models import TradePlanORM
from crypto_trader.scale_in.contract import SCALE_IN_STRATEGY_ID
from crypto_trader.scale_in.service import ADD_EXECUTION_ENABLED
from crypto_trader.trade_plan.service import TradePlanService
from tests.llm_chief.test_position_manager import (
    Chief as _BaseChief,
)
from tests.llm_chief.test_position_manager import (
    Evidence,
    active_plan,
    context,
    manager,
)


class AddChief(_BaseChief):
    """A ChiefTrader that asks to ADD to an existing position."""

    def __init__(self, action: str = "ADD", quantity: str = "5") -> None:
        super().__init__(action, quantity)

    async def decide(self, ctx):
        self.calls += 1
        return ChiefTraderDecision(
            decision_id="open-add",
            symbol=ctx.symbol,
            position_state=PositionState.OPEN,
            action=OpenAction.ADD,
            market_regime=ctx.regime,
            thesis="trend continuation with new structure",
            # Advisory only: never an order quantity.
            position_size_request=float(self.quantity),
            stop_loss=98.0,
            model_provider="deepseek",
            model="deepseek-v4-pro",
        )


# ===================================================== §123: ADD cannot execute
async def test_add_position_decision_is_refused_and_never_becomes_a_reduce(database):
    await active_plan(database, "LONG")
    ctx, position = context("2")

    signal = await manager(database, AddChief()).review(ctx, position)

    # It produced NO order at all ...
    assert signal is None
    # ... the decision is durably recorded as a risk-increasing request ...
    stored = await LLMDecisionStore(database.session_factory).get("open-add")
    assert stored is not None and stored.action == "ADD"


async def test_add_refusal_is_audited_as_a_blocked_reduce_substitution(database):
    await active_plan(database, "LONG")
    ctx, position = context("2")
    audit = AuditService(database.session_factory)

    signal = await LLMPositionManagerWithAudit(database, audit).review(ctx, position)

    assert signal is None
    events = [
        row
        for row in await audit.list_recent(limit=50)
        if row.action == "LIVE_LLM_POSITION_ADD_REFUSED"
    ]
    assert len(events) == 1
    payload = events[0].after_json
    assert payload["reason"] == "ADD_EXECUTION_DISABLED_FEATURE_FLAG"
    assert payload["risk_increasing"] is True
    assert payload["auto_scale_in_enabled"] is False
    assert payload["reduce_substitution_blocked"] is True


async def test_add_never_produces_a_reduce_only_signal(database):
    """The dangerous inversion would be ADD silently becoming a REDUCE."""
    await active_plan(database, "LONG")
    ctx, position = context("2")

    for _ in range(3):
        signal = await manager(database, AddChief()).review(ctx, position)
        assert signal is None

    # The position is untouched: ADD is not risk-reducing either.
    assert position.quantity == Decimal("2")


def LLMPositionManagerWithAudit(database, audit) -> LiveLLMPositionManager:
    return LiveLLMPositionManager(
        chief=AddChief(),
        evidence_engine=Evidence(),
        decisions=LLMDecisionStore(database.session_factory),
        plans=TradePlanService(database.session_factory),
        audit=audit,
    )


async def test_add_at_max_hold_falls_back_to_the_time_stop_safety_boundary(database):
    """§109 — REDUCE outranks ADD, so the holding-period safety still fires.

    With the factual maximum holding period already elapsed, an ADD request must
    not become a no-op: the existing TIME_STOP reduce-only boundary takes over.
    """
    plan = await active_plan(database, "LONG")
    ctx, position = context("2")
    # Age the PLAN past its factual maximum holding period (86400s): the
    # holding clock starts at the plan's own opened_at fact.
    async with database.session_factory() as session:
        row = await session.get(TradePlanORM, plan.trade_plan_id)
        assert row is not None
        row.opened_at = ctx.clock_time - timedelta(days=3)
        await session.commit()

    audit = AuditService(database.session_factory)
    subject = LLMPositionManagerWithAudit(database, audit)
    signal = await subject.review(ctx, position)

    assert signal is not None
    assert signal.metadata["reduce_only"] is True
    assert signal.metadata["lifecycle_action"] == "TIME_STOP_SAFETY_FALLBACK"
    assert any(
        row.action == "LIVE_LLM_POSITION_ADD_OVERRIDDEN_BY_TIME_STOP"
        for row in await audit.list_recent(limit=50)
    )


async def test_execution_is_disabled_at_the_module_level():
    assert ADD_EXECUTION_ENABLED is False


# ============================================= §116: purpose is never a plain ENTRY
def test_scale_in_order_purpose_is_its_own_value_and_never_entry():
    """A future ADD order must never inherit entry-only rules."""
    for kwargs in (
        {"strategy_id": SCALE_IN_STRATEGY_ID, "trade_plan_state": "ACTIVE"},
        {"strategy_id": SCALE_IN_STRATEGY_ID, "trade_plan_state": "PLANNED"},
        {"strategy_id": "live_llm", "position_action": "ADD"},
        {"strategy_id": "live_llm_position_add", "reduce_only": False},
    ):
        assert classify_order_purpose(**kwargs) == ORDER_PURPOSE_POSITION_ADD
        assert classify_order_purpose(**kwargs) != ORDER_PURPOSE_ENTRY


def test_existing_purpose_classification_is_completely_unchanged():
    """F5 must not shift: every pre-existing input keeps its exact result."""
    assert (
        classify_order_purpose(strategy_id="live_llm", trade_plan_state="ACTIVE")
        == ORDER_PURPOSE_ENTRY
    )
    assert (
        classify_order_purpose(strategy_id="live_llm", trade_plan_state="PLANNED")
        == ORDER_PURPOSE_ENTRY
    )
    assert (
        classify_order_purpose(strategy_id="live_llm")
        == ORDER_PURPOSE_ENTRY
    )
    assert (
        classify_order_purpose(strategy_id="live_llm_position", direction="EXIT")
        == ORDER_PURPOSE_POSITION_EXIT
    )
    assert (
        classify_order_purpose(strategy_id="live_llm_position", direction="REDUCE")
        == ORDER_PURPOSE_POSITION_REDUCE
    )
    assert (
        classify_order_purpose(
            strategy_id="live_llm", reduce_only=True, direction="EXIT"
        )
        == ORDER_PURPOSE_POSITION_EXIT
    )
    assert (
        classify_order_purpose(strategy_id="live_llm", reduce_only=True)
        == ORDER_PURPOSE_POSITION_REDUCE
    )
    assert classify_order_purpose(strategy_id="some_other") == ORDER_PURPOSE_ENTRY
    assert classify_order_purpose(strategy_id="other_position") == ORDER_PURPOSE_OTHER
    assert classify_order_purpose(strategy_id=None) == ORDER_PURPOSE_OTHER


def test_position_add_is_part_of_the_declared_purpose_taxonomy():
    assert ORDER_PURPOSE_POSITION_ADD in ORDER_PURPOSES


def test_scale_in_orders_are_not_subject_to_the_entry_ttl():
    """§112 — ADD gets its own TTL later; the ENTRY TTL must not touch it."""
    fact = type(
        "Fact",
        (),
        {
            "order_id": "live_llm_position_add_add-1",
            "purpose": ORDER_PURPOSE_POSITION_ADD,
            "state": "CONFIRMED_OPEN",
            "filled_quantity": "0",
            "remaining_quantity": "10",
        },
    )()
    decision = evaluate_entry_ttl(
        fact=fact, durable_status="OPEN", resting_age=10_000.0, ttl_seconds=60.0
    )
    assert decision.action == ACTION_NOT_APPLICABLE
    assert decision.reason == "PURPOSE_NOT_ENTRY"
    assert decision.cancel_remaining_only is False

    # The ENTRY scope itself is untouched: a genuine entry still expires.
    entry_fact = type(
        "Fact",
        (),
        {
            "order_id": "entry-1",
            "purpose": ORDER_PURPOSE_ENTRY,
            "state": "CONFIRMED_OPEN",
            "filled_quantity": "0",
            "remaining_quantity": "10",
        },
    )()
    entry_decision = evaluate_entry_ttl(
        fact=entry_fact, durable_status="OPEN", resting_age=10_000.0, ttl_seconds=60.0
    )
    assert entry_decision.action == "CANCEL_REMAINING"
