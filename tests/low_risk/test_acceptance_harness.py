"""Engineering regressions for the read-only final acceptance harness."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "final_acceptance", ROOT / "scripts" / "acceptance" / "final_acceptance.py"
)
assert SPEC is not None and SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def _ready(*, mode: str = "PAPER", live: bool = False, held: bool = True, single: bool = True):
    return {
        "mode": mode,
        "live_trading_enabled": live,
        "runtime": {
            "execution_lease": {"held": held, "single_writer": single},
            "llm_router": {"pause": {"provider_calls_paused": True}},
        },
    }


def test_evaluate_p0_flags_live_lease_sha_duplicate_and_paused_new_risk():
    events = harness.evaluate_p0(
        _ready(live=True, held=False, single=False),
        {
            "provider_call_pause": {"provider_calls_paused": True},
            "configured_provider": "deepseek-chat",
            "configured_model": "deepseek-chat",
        },
        {
            "duplicate_client_order_ids": 1,
            "new_risk_decisions": 1,
            "new_risk_decisions_since_pause": 1,
            "plans_over_25pct_allocation": 1,
            "plans_over_20x_leverage": 1,
            "plans_missing_base_exit": 1,
        },
        expected_sha="expected",
        running_sha="actual",
    )
    codes = {event["code"] for event in events}
    assert {
        "LIVE_TRADING_ENABLED",
        "LEASE_NOT_HELD",
        "MULTIPLE_WRITERS",
        "RUNTIME_SHA_DRIFT",
        "DUPLICATE_ORDER_ID",
        "PAUSED_LLM_NEW_RISK",
        "CHILD_ALLOCATION_OVER_25",
        "LEVERAGE_OVER_20",
        "MISSING_BASE_EXIT",
        "PROVIDER_MODEL_DRIFT",
    } <= codes


def test_collect_db_metrics_detects_duplicate_client_order_ids(tmp_path):
    db_path = tmp_path / "paper.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE orders (client_order_id TEXT, internal_order_id TEXT)")
    connection.execute("INSERT INTO orders VALUES ('c1', 'o1')")
    connection.execute("INSERT INTO orders VALUES ('c1', 'o2')")
    connection.execute(
        "CREATE TABLE trade_plans ("
        "capital_allocation_pct REAL, leverage_request REAL, base_exit_json TEXT"
        ")"
    )
    connection.execute("INSERT INTO trade_plans VALUES (30, 25, '')")
    connection.commit()
    connection.close()

    metrics = harness.collect_db_metrics(str(db_path))
    assert metrics["available"] is True
    assert metrics["orders_count"] == 2
    assert metrics["duplicate_client_order_ids"] == 1
    assert metrics["plans_over_25pct_allocation"] == 1
    assert metrics["plans_over_20x_leverage"] == 1
    assert metrics["plans_missing_base_exit"] == 1


def test_missing_readiness_does_not_fabricate_live_or_writer_p0():
    events = harness.evaluate_p0({}, {}, {}, expected_sha="expected", running_sha="expected")
    assert [event["code"] for event in events] == ["RUNTIME_UNAVAILABLE"]
    assert "LIVE_TRADING_ENABLED" not in {event["code"] for event in events}
    assert "NON_PAPER_MODE" not in {event["code"] for event in events}
    assert "MULTIPLE_WRITERS" not in {event["code"] for event in events}


def test_partial_readiness_reports_unknown_not_false_factual_violation():
    events = harness.evaluate_p0({"mode": "PAPER"}, {}, {}, expected_sha=None, running_sha=None)
    codes = {event["code"] for event in events}
    assert "READINESS_UNKNOWN" in codes
    assert "LEASE_UNAVAILABLE" in codes
    assert "LIVE_TRADING_ENABLED" not in codes
    assert "MULTIPLE_WRITERS" not in codes
    assert "WRITER_STATE_UNKNOWN" in codes


def test_factual_live_and_writer_still_raise_p0():
    events = harness.evaluate_p0(
        _ready(live=True, held=True, single=False), {}, {}, expected_sha=None, running_sha=None
    )
    codes = {event["code"] for event in events}
    assert "LIVE_TRADING_ENABLED" in codes
    assert "MULTIPLE_WRITERS" in codes


def test_missing_lease_fields_are_unknown_not_lease_lost():
    ready = {"mode": "PAPER", "live_trading_enabled": False, "runtime": {}}
    events = harness.evaluate_p0(ready, {}, {}, expected_sha=None, running_sha=None)
    codes = {event["code"] for event in events}
    assert "LEASE_UNAVAILABLE" in codes
    assert "WRITER_STATE_UNKNOWN" in codes
    assert "LEASE_NOT_HELD" not in codes


@pytest.mark.parametrize(
    "authority,action",
    [
        ("FAST_PROFIT_PROTECTION", "FAST_PROFIT_PROTECTION"),
        ("RISK_HARD_EXIT", "RISK_HARD_EXIT"),
        ("OFFLINE_HARD_EXIT", "OFFLINE_HARD_EXIT"),
        ("ACTIVE_BASE_EXIT", "BASE_EXIT"),
        ("ACTIVE_BASE_EXIT", "STOP_LOSS"),
    ],
)
def test_observer_recognizes_typed_deterministic_reduce_order(authority, action):
    metadata = dict(
        reduce_only=True,
        deterministic_exit=True,
        lifecycle_action=action,
        exit_authority=authority,
        exit_request_id="exit_fixture",
        decision_id="det_exit_fixture",
        trade_plan_id="fixture-plan",
        state_version="fixture-version",
        risk_decision_id="fixture-risk",
    )
    assert harness.order_violation(metadata, "PAPER", "FILLED") is False


@pytest.mark.parametrize("bad_authority", ["UNKNOWN", None, [], {"source": "RISK_HARD_EXIT"}])
def test_observer_rejects_unknown_or_malformed_exit_authority(bad_authority):
    metadata = dict(
        reduce_only=True,
        deterministic_exit=True,
        lifecycle_action="RISK_HARD_EXIT",
        exit_authority=bad_authority,
        exit_request_id="exit_fixture",
        decision_id="det_exit_fixture",
        trade_plan_id="fixture-plan",
        state_version="fixture-version",
        risk_decision_id="fixture-risk",
    )
    assert harness.order_violation(metadata, "PAPER", "FILLED") is True


@pytest.mark.parametrize("action", ["EXIT", "REDUCE", "CLOSE"])
def test_observer_preserves_canonical_chief_reduction_vocabulary(action):
    assert (
        harness.order_violation(
            {"reduce_only": True, "lifecycle_action": action}, "PAPER", "FILLED"
        )
        is False
    )


@pytest.mark.parametrize("action", [None, [], "UNKNOWN", "ADD", "HEDGE", "REVERSE"])
def test_observer_does_not_accept_unknown_or_new_risk_as_reduce(action):
    assert (
        harness.order_violation(
            {"reduce_only": True, "lifecycle_action": action}, "PAPER", "FILLED"
        )
        is True
    )


def test_observer_deterministic_provenance_links_and_paper_boundary_remain_required():
    valid = dict(
        reduce_only=True,
        deterministic_exit=True,
        lifecycle_action="RISK_HARD_EXIT",
        exit_authority="RISK_HARD_EXIT",
        exit_request_id="exit_fixture",
        decision_id="det_exit_fixture",
        trade_plan_id="fixture-plan",
        state_version="fixture-version",
        risk_decision_id="fixture-risk",
    )
    for key in (
        "exit_request_id",
        "decision_id",
        "trade_plan_id",
        "state_version",
        "risk_decision_id",
    ):
        assert harness.order_violation({**valid, key: None}, "PAPER", "FILLED") is True
    assert harness.order_violation({**valid, "decision_id": "det_wrong"}, "PAPER", "FILLED") is True
    assert harness.order_violation(valid, "LIVE", "FILLED") is True
    assert (
        harness.order_violation({**valid, "deterministic_exit": False}, "PAPER", "FILLED") is True
    )


def test_observer_new_risk_limits_and_rejection_semantics_are_unchanged():
    valid = dict(
        capital_allocation_pct="25",
        approved_leverage="20",
        base_exit={"trigger": "1"},
        trade_plan_id="plan",
        decision_id="chief",
        risk_decision_id="risk",
    )
    assert harness.order_violation(valid, "PAPER", "FILLED") is False
    for change in (
        {"capital_allocation_pct": "25.01"},
        {"approved_leverage": "20.01"},
        {"approved_leverage": "NaN"},
        {"base_exit": None},
        {"decision_id": None},
    ):
        assert harness.order_violation({**valid, **change}, "PAPER", "FILLED") is True
    assert harness.order_violation({}, "PAPER", "REJECTED") is False
    assert harness.order_violation({}, "LIVE", "REJECTED") is True
