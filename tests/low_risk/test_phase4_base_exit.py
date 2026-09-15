"""Phase 4C tests: atomic Base Exit activation + stale-plan race safety.

Proves: an active Base Exit survives until a new version is atomically
activated; a stale LLM plan (position state moved) is rejected as
STALE_DECISION; an exit that already filled cannot be replaced; the exit
trigger only wakes the canonical exit path (never an order).
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from crypto_trader.execution import base_exit as module
from crypto_trader.execution.base_exit import (
    BaseExitRegistry,
    StaleBaseExitError,
)

BASE = datetime(2026, 9, 16, 0, 0, 0, tzinfo=UTC)


def _registry() -> BaseExitRegistry:
    registry = BaseExitRegistry()
    registry.stage(
        "leg1",
        plan_version=1,
        exit_type="PRICE",
        trigger=">=105",
        size_pct=100.0,
        reason_code="BASE_EXIT",
        based_on_state_version="pos_v1",
    )
    first = registry.by_leg["leg1"][0]
    registry.activate(first, factual_state_version="pos_v1", now=BASE)
    return registry


def test_staging_does_not_replace_active_exit() -> None:
    registry = _registry()
    active_before = registry.active("leg1")
    staged = registry.stage(
        "leg1",
        plan_version=2,
        exit_type="PRICE",
        trigger=">=108",
        size_pct=50.0,
        based_on_state_version="pos_v2",
    )
    assert registry.active("leg1").version_id == active_before.version_id
    assert staged.active is False
    assert [event["event"] for event in registry.events].count("BASE_EXIT_ACTIVATED") == 1


def test_activation_replaces_atomically() -> None:
    registry = _registry()
    old = registry.active("leg1")
    new = registry.stage(
        "leg1",
        plan_version=2,
        exit_type="PRICE",
        trigger=">=108",
        size_pct=50.0,
        based_on_state_version="pos_v2",
    )
    activated = registry.activate(new.version_id, factual_state_version="pos_v2", now=BASE)
    assert activated.active is True
    assert registry.active("leg1").version_id == new.version_id
    assert old.active is False
    assert old.superseded_at == BASE


def test_stale_llm_plan_is_rejected_and_old_exit_stays_active() -> None:
    registry = _registry()
    old = registry.active("leg1")
    staged = registry.stage(
        "leg1",
        plan_version=2,
        exit_type="PRICE",
        trigger=">=108",
        size_pct=50.0,
        based_on_state_version="pos_v1",  # built before the fill
    )
    with pytest.raises(StaleBaseExitError, match="STALE_DECISION"):
        registry.activate(staged.version_id, factual_state_version="pos_v2", now=BASE)
    assert registry.active("leg1").version_id == old.version_id
    assert staged.active is False
    assert any(event["event"] == "BASE_EXIT_STALE_REJECTED" for event in registry.events)


def test_exit_v1_to_v2_race_filled_then_stale_activation() -> None:
    registry = _registry()
    staged = registry.stage(
        "leg1",
        plan_version=2,
        exit_type="PRICE",
        trigger=">=108",
        size_pct=50.0,
        based_on_state_version="pos_v1",
    )
    # V1 exit fills while the LLM is thinking about V2.
    registry.mark_filled("leg1", now=BASE + timedelta(seconds=5))
    assert registry.active("leg1") is None
    with pytest.raises(StaleBaseExitError, match="already closed"):
        registry.activate(staged.version_id, factual_state_version="pos_v1")
    # New factual episode can reopen the leg with a fresh exit.
    registry.reopen_leg("leg1")
    fresh = registry.stage(
        "leg1",
        plan_version=3,
        exit_type="PRICE",
        trigger=">=110",
        based_on_state_version="pos_v3",
    )
    registry.activate(fresh.version_id, factual_state_version="pos_v3")
    assert registry.active("leg1").version_id == fresh.version_id


def test_active_exit_triggers_only_the_exit_decision() -> None:
    registry = _registry()
    not_due = registry.evaluate("leg1", now=BASE, price=Decimal("104.9"))
    assert not_due.due is False
    assert not_due.reason_code == "BASE_EXIT_NOT_TRIGGERED"
    due = registry.evaluate("leg1", now=BASE, price=Decimal("105.1"))
    assert due.due is True
    assert due.exit_pct == 100.0
    assert due.reason_code == "BASE_EXIT"
    assert due.authority == "ACTIVE_BASE_EXIT"
    assert due.is_new_risk is False


def test_time_trigger_and_partial_size() -> None:
    registry = BaseExitRegistry()
    version = registry.stage(
        "leg1",
        plan_version=1,
        exit_type="TIME",
        trigger="+300s",
        size_pct=40.0,
        based_on_state_version="pos_v1",
    )
    registry.activate(version.version_id, factual_state_version="pos_v1", now=BASE)
    early = registry.evaluate("leg1", now=BASE + timedelta(seconds=100), anchor_time=BASE)
    assert early.due is False
    late = registry.evaluate("leg1", now=BASE + timedelta(seconds=301), anchor_time=BASE)
    assert late.due is True
    assert late.exit_pct == 40.0


def test_indicator_event_conditions_need_injected_evaluator() -> None:
    registry = BaseExitRegistry()
    version = registry.stage(
        "leg1",
        plan_version=1,
        exit_type="EVENT",
        trigger="CVD_REVERSAL",
        based_on_state_version="pos_v1",
    )
    registry.activate(version.version_id, factual_state_version="pos_v1")
    unavailable = registry.evaluate("leg1", now=BASE)
    assert unavailable.due is False
    assert unavailable.detail == "NO_EVALUATOR_FOR_CONDITION"

    def evaluator(*, type, value, **kwargs):
        return value == "CVD_REVERSAL", "matched"

    with_eval = BaseExitRegistry(condition_evaluator=evaluator)
    v2 = with_eval.stage(
        "leg1",
        plan_version=1,
        exit_type="EVENT",
        trigger="CVD_REVERSAL",
        based_on_state_version="pos_v1",
    )
    with_eval.activate(v2.version_id, factual_state_version="pos_v1")
    assert with_eval.evaluate("leg1", now=BASE).due is True


def test_no_active_exit_is_explicit() -> None:
    registry = BaseExitRegistry()
    decision = registry.evaluate("leg1", now=BASE, price=Decimal("100"))
    assert decision.due is False
    assert decision.reason_code == "NO_ACTIVE_BASE_EXIT"


def test_base_exit_registry_has_no_order_authority() -> None:
    source = inspect.getsource(module)
    for forbidden in ("ExecutionAuthority", "OrderManager", "submit_order", "process_signal"):
        assert forbidden not in source
