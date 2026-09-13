"""F6.3: EMERGENCY ACTIVE-POSITION migration gate.

The permanent gate (ZERO positions / ZERO orders / ZERO plans) is NOT relaxed.
This gate is hard bound to ONE incident class and answers one question: can this
factual position survive a single controlled PAPER migration, given that the
blocking UNKNOWN is PROVABLY a pre-broker rejection?

The tests below mostly prove the gate REFUSES. A gate that can be talked into
PASS by a plausible-looking but unproven state is worse than no gate, because it
would authorise migrating a position whose blocking order might really exist at
the exchange.
"""

from __future__ import annotations

import pathlib
from decimal import Decimal

from crypto_trader.domain.models import Position
from crypto_trader.order.emergency_migration_gate import (
    GATE_FAIL,
    GATE_PASS,
    GATE_UNKNOWN,
    INCIDENT_CLASS,
    R_ADDITIONAL_UNKNOWN_ORDER,
    R_IDENTITY_CONTRADICTION,
    R_LEGACY_ENTRY_UNRECOVERABLE,
    R_MISSING_ORDER,
    R_OTHER_POSITION_ACTION_PRESENT,
    R_PARTIAL_FILL_IN_SCOPE,
    R_PLAN_NOT_ACTIVE,
    R_PLAN_NOT_FOUND,
    R_POSITION_COUNT_NOT_ONE,
    R_RUNTIME_SAFETY_FAILED,
    R_RUNTIME_STATE_UNKNOWN,
    R_SPECIAL_UNKNOWN_NOT_CONFIRMED,
    R_UNKNOWN_COUNT_INVALID,
    evaluate_emergency_active_position_gate,
)
from crypto_trader.order.pre_broker_rejection import REASON_MARKET_DATA_UNAVAILABLE

INCIDENT_UNKNOWN_ID = "ord_4b4d845cf27d433dab72567f1bf77328"
ACTIVE_PLAN_ID = "plan_ca0660c80a154bfc88f2415f0e6bf258"
SOPH_ID = "ord_f9edfa0a41984a29892c94eee94b0b22"
IOST_ID = "ord_3f643bbfe22249ddbb9125112d07d2f5"


def _healthy_runtime(**overrides):
    facts = {
        "mode": "PAPER",
        "lease_healthy": True,
        "single_writer": True,
        "reconciliation_halted": False,
        "kill_switch": False,
        "runtime_sha": "460553f2d42b8fd650fb1e69b92943c62f31af3f",
        "target_sha": "bccb8a4881faf04226b51e46c39d5e62dedf1515",
        "position_side": "LONG",
        "active_plan": {
            "trade_plan_id": ACTIVE_PLAN_ID,
            "symbol": "IOSTUSDT",
            "state": "ACTIVE",
        },
    }
    facts.update(overrides)
    return facts


def _positions(qty="29", symbol="IOSTUSDT"):
    return {
        symbol: Position(
            symbol=symbol, base_asset="IOST", quote_asset="USDT", quantity=Decimal(qty)
        )
    }


def _special_unknown(**overrides):
    record = {
        "order_id": INCIDENT_UNKNOWN_ID,
        "purpose": "POSITION_REDUCE",
        "reconciliation": "UNKNOWN",
        "exchange_order_id": None,
        "filled_quantity": "0",
        "durable_fill_count": 0,
        "failure_reason": REASON_MARKET_DATA_UNAVAILABLE,
        "pre_broker_lineage_proven": True,
    }
    record.update(overrides)
    return record


def _legacy_entry(order_id, symbol="SOPHUSDT"):
    return {
        "order_id": order_id,
        "purpose": "ENTRY",
        "reconciliation": "CONFIRMED_OPEN",
        "exchange_order_id": f"sim_{order_id}",
        "filled_quantity": "0",
        "provenance_sha": "460553f2d42b8fd650fb1e69b92943c62f31af3f",
        "resting_timestamp_available": True,
        "recoverable_confirmed": True,
    }


def _gate(positions=None, records=None, runtime=None, **kwargs):
    return evaluate_emergency_active_position_gate(
        positions=_positions() if positions is None else positions,
        order_records=records
        if records is not None
        else [_special_unknown(), _legacy_entry(SOPH_ID), _legacy_entry(IOST_ID, "IOSTUSDT")],
        runtime_facts=_healthy_runtime() if runtime is None else runtime,
        expected_plan_id=ACTIVE_PLAN_ID,
        expected_unknown_order_id=INCIDENT_UNKNOWN_ID,
        **kwargs,
    )


# ------------------------------------------------------------- incident shape


def test_incident_shape_passes():
    verdict = _gate()
    assert verdict.state == GATE_PASS, verdict.reason_codes
    assert verdict.incident_class == INCIDENT_CLASS
    assert verdict.special_unknown_order_id == INCIDENT_UNKNOWN_ID
    assert verdict.position_symbol == "IOSTUSDT"
    assert verdict.position_quantity == "29"
    assert set(verdict.legacy_entry_ids) == {SOPH_ID, IOST_ID}


def test_position_quantity_is_read_not_hardcoded():
    verdict = _gate(positions=_positions(qty="77"))
    assert verdict.state == GATE_PASS
    assert verdict.position_quantity == "77"


# ------------------------------------------------------ §3 position conditions


def test_zero_positions_means_this_gate_does_not_apply():
    """No position -> the NORMAL gate is the right one, not this one."""
    verdict = _gate(positions={})
    assert verdict.state == GATE_FAIL
    assert R_POSITION_COUNT_NOT_ONE in verdict.reason_codes


def test_two_positions_are_out_of_scope():
    positions = _positions()
    positions["OTHERUSDT"] = Position(
        symbol="OTHERUSDT", base_asset="OTH", quote_asset="USDT", quantity=Decimal("5")
    )
    verdict = _gate(positions=positions)
    assert verdict.state == GATE_FAIL
    assert R_POSITION_COUNT_NOT_ONE in verdict.reason_codes


# ------------------------------------------------------------- §4 plan binding


def test_plan_missing_blocks():
    runtime = _healthy_runtime(active_plan={})
    verdict = _gate(runtime=runtime)
    assert verdict.state == GATE_FAIL
    assert R_PLAN_NOT_FOUND in verdict.reason_codes


def test_wrong_plan_id_blocks():
    runtime = _healthy_runtime(
        active_plan={"trade_plan_id": "plan_other", "symbol": "IOSTUSDT", "state": "ACTIVE"}
    )
    verdict = _gate(runtime=runtime)
    assert verdict.state == GATE_FAIL
    assert R_PLAN_NOT_FOUND in verdict.reason_codes


def test_plan_not_active_blocks():
    runtime = _healthy_runtime(
        active_plan={"trade_plan_id": ACTIVE_PLAN_ID, "symbol": "IOSTUSDT", "state": "RECOVERY"}
    )
    verdict = _gate(runtime=runtime)
    assert verdict.state == GATE_FAIL
    assert R_PLAN_NOT_ACTIVE in verdict.reason_codes


def test_position_side_mismatch_blocks():
    runtime = _healthy_runtime(position_side="SHORT")
    verdict = _gate(runtime=runtime)
    assert verdict.state == GATE_FAIL


# ------------------------------------------------- §5/§6 the special UNKNOWN


def test_special_unknown_must_be_proven_pre_broker():
    """§5: unproven lineage keeps the gate closed."""
    verdict = _gate(
        records=[
            _special_unknown(pre_broker_lineage_proven=False),
            _legacy_entry(SOPH_ID),
        ]
    )
    assert verdict.state == GATE_FAIL
    assert R_SPECIAL_UNKNOWN_NOT_CONFIRMED in verdict.reason_codes


def test_special_unknown_with_a_fill_is_not_repairable():
    verdict = _gate(
        records=[_special_unknown(durable_fill_count=1), _legacy_entry(SOPH_ID)]
    )
    assert verdict.state == GATE_FAIL
    assert R_SPECIAL_UNKNOWN_NOT_CONFIRMED in verdict.reason_codes


def test_special_unknown_with_broker_id_is_not_repairable():
    verdict = _gate(
        records=[_special_unknown(exchange_order_id="sim_x"), _legacy_entry(SOPH_ID)]
    )
    assert verdict.state == GATE_FAIL
    assert R_SPECIAL_UNKNOWN_NOT_CONFIRMED in verdict.reason_codes


def test_special_unknown_drift_blocks():
    """A different UNKNOWN order id than the incident is not this incident."""
    verdict = _gate(records=[_special_unknown(order_id="ord_other"), _legacy_entry(SOPH_ID)])
    assert verdict.state == GATE_FAIL


def test_zero_unknowns_blocks():
    """If the incident UNKNOWN is gone, this gate must not be used."""
    verdict = _gate(records=[_legacy_entry(SOPH_ID)])
    assert verdict.state == GATE_FAIL
    assert R_UNKNOWN_COUNT_INVALID in verdict.reason_codes


def test_two_unknowns_block():
    """§6: a second UNKNOWN is out of scope."""
    verdict = _gate(
        records=[
            _special_unknown(),
            _special_unknown(order_id="ord_second"),
            _legacy_entry(SOPH_ID),
        ]
    )
    assert verdict.state == GATE_FAIL
    assert R_ADDITIONAL_UNKNOWN_ORDER in verdict.reason_codes


# --------------------------------------------------- §11/§12 other orders


def test_other_position_action_blocks():
    record = _legacy_entry("ord_pa")
    record["purpose"] = "POSITION_REDUCE"
    verdict = _gate(records=[_special_unknown(), record])
    assert verdict.state == GATE_FAIL
    assert R_OTHER_POSITION_ACTION_PRESENT in verdict.reason_codes


def test_position_exit_order_blocks():
    record = _legacy_entry("ord_px")
    record["purpose"] = "POSITION_EXIT"
    verdict = _gate(records=[_special_unknown(), record])
    assert verdict.state == GATE_FAIL
    assert R_OTHER_POSITION_ACTION_PRESENT in verdict.reason_codes


def test_partial_fill_in_scope_blocks():
    """§12: an unresolved partial fill is never swept into this exception."""
    record = _legacy_entry("ord_pf")
    record["filled_quantity"] = "300"
    verdict = _gate(records=[_special_unknown(), record])
    assert verdict.state == GATE_FAIL
    assert R_PARTIAL_FILL_IN_SCOPE in verdict.reason_codes


def test_legacy_entry_without_identity_blocks():
    record = _legacy_entry("ord_noid")
    record["exchange_order_id"] = None
    verdict = _gate(records=[_special_unknown(), record])
    assert verdict.state == GATE_FAIL
    assert R_LEGACY_ENTRY_UNRECOVERABLE in verdict.reason_codes


def test_legacy_entry_without_provenance_blocks():
    record = _legacy_entry("ord_noprov")
    record["provenance_sha"] = None
    verdict = _gate(records=[_special_unknown(), record])
    assert verdict.state == GATE_FAIL
    assert R_LEGACY_ENTRY_UNRECOVERABLE in verdict.reason_codes


def test_legacy_entry_without_resting_timestamp_blocks():
    record = _legacy_entry("ord_nots")
    record["resting_timestamp_available"] = False
    verdict = _gate(records=[_special_unknown(), record])
    assert verdict.state == GATE_FAIL
    assert R_LEGACY_ENTRY_UNRECOVERABLE in verdict.reason_codes


# ------------------------------------------------------------- §13 missing


def test_missing_order_blocks():
    record = _legacy_entry("ord_missing")
    record["reconciliation"] = "MISSING"
    verdict = _gate(records=[_special_unknown(), record])
    assert verdict.state == GATE_FAIL
    assert R_MISSING_ORDER in verdict.reason_codes


def test_identity_conflict_blocks():
    record = _legacy_entry("ord_conflict")
    record["identity_conflict"] = True
    record["purpose"] = "OTHER"
    verdict = _gate(records=[_special_unknown(), record])
    assert verdict.state == GATE_FAIL
    assert R_IDENTITY_CONTRADICTION in verdict.reason_codes


# ------------------------------------------------------- §14 runtime safety


def test_runtime_safety_failures_block():
    for key, value in (
        ("lease_healthy", False),
        ("single_writer", False),
        ("reconciliation_halted", True),
        ("kill_switch", True),
    ):
        verdict = _gate(runtime=_healthy_runtime(**{key: value}))
        assert verdict.state == GATE_FAIL, key
        assert R_RUNTIME_SAFETY_FAILED in verdict.reason_codes


def test_unknown_runtime_fact_yields_unknown():
    verdict = _gate(runtime=_healthy_runtime(lease_healthy=None))
    assert verdict.state == GATE_UNKNOWN
    assert R_RUNTIME_STATE_UNKNOWN in verdict.reason_codes


def test_wrong_source_runtime_blocks():
    verdict = _gate(runtime=_healthy_runtime(runtime_sha="deadbeef"))
    assert verdict.state == GATE_FAIL


def test_wrong_target_lineage_blocks():
    verdict = _gate(runtime=_healthy_runtime(target_sha="0000000"))
    assert verdict.state == GATE_FAIL


# ------------------------------------------------------- §31/§33 purity+scope


def test_normal_gate_is_not_modified():
    """§31: the permanent zero/zero/zero rule must be untouched."""
    source = pathlib.Path(
        "src/crypto_trader/order/emergency_migration_gate.py"
    ).read_text()
    for forbidden in ("UNRESOLVED_ORDERS_GATE", "IMMINENT_PLANS_GATE"):
        assert forbidden not in source
    # It must not weaken the position condition into a general allowance.
    assert "POSITION_COUNT_NOT_ONE" in source


def test_gate_declares_incident_binding():
    from crypto_trader.order import emergency_migration_gate as module

    assert module.INCIDENT_CLASS == INCIDENT_CLASS
    assert module.SOURCE_RUNTIME_SHA.startswith("460553f2")
    assert module.TARGET_MIN_LINEAGE_SHA.startswith("bccb8a4")


def test_gate_is_pure_read_only():
    import ast as _ast

    tree = _ast.parse(
        pathlib.Path("src/crypto_trader/order/emergency_migration_gate.py").read_text()
    )
    forbidden = {
        "submit_order",
        "cancel_pending",
        "apply_fill",
        "complete_json",
        "try_acquire",
        "create_task",
        "commit",
        "close_position",
    }
    reached = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in forbidden:
                reached.add(name)
        elif isinstance(node, _ast.Attribute) and node.attr in forbidden:
            reached.add(node.attr)
    assert not reached, f"gate is not pure: {sorted(reached)}"


def test_gate_returns_reason_codes():
    verdict = _gate(positions={})
    payload = verdict.as_dict()
    assert payload["reason_codes"]
    assert set(payload) >= {
        "state",
        "incident_class",
        "reason_codes",
        "special_unknown_order_id",
    }


def test_gate_creates_no_executor():
    source = pathlib.Path(
        "src/crypto_trader/order/emergency_migration_gate.py"
    ).read_text()
    for forbidden in ("class EmergencyExecutor", "def deploy", "def execute_migration"):
        assert forbidden not in source
