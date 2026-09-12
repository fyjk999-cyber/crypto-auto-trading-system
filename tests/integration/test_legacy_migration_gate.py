"""F6.1: legacy order-migration preflight gate (G1-G17).

The permanent deployment rule stays zero/zero/zero. This gate exists only
because a runtime that shipped without ENTRY liveness can never reach that
state: its stale ENTRY orders have no mechanism to expire, so the normal gate
deadlocks. The gate decides whether a ONE-TIME migration is safe to attempt.

Every test asserts on the reason codes as well as the verdict, because "FAIL"
without a machine-readable cause cannot be acted on or audited, and because a
verdict that flips between PASS/FAIL on identical facts is worse than no gate.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from crypto_trader.domain.models import Order, Position
from crypto_trader.order.migration_preflight import (
    GATE_FAIL,
    GATE_PASS,
    GATE_UNKNOWN,
    LEGACY_SOURCE_RUNTIME_SHA,
    R_IDENTITY_CONTRADICTION,
    R_KILL_SWITCH,
    R_LEASE_UNHEALTHY,
    R_LEGACY_ENTRY_HAS_FACTUAL_FILL,
    R_MODE_NOT_PAPER,
    R_ORDER_MISSING,
    R_ORDER_UNKNOWN,
    R_POSITION_ACTION_ORDER_PRESENT,
    R_POSITION_NONZERO,
    R_PROVENANCE_UNPROVEN,
    R_RECONCILIATION_HALTED,
    R_RECOVERY_FACTS_INSUFFICIENT,
    R_RESTING_TIMESTAMP_INSUFFICIENT,
    R_RUNTIME_STATE_UNKNOWN,
    R_SINGLE_WRITER_FALSE,
    R_UNSUPPORTED_UNRESOLVED_ORDER_PURPOSE,
    evaluate_legacy_migration_gate,
)

SONE = "SOPHUSDT"


def _healthy_runtime(**overrides):
    facts = {
        "mode": "PAPER",
        "lease_healthy": True,
        "single_writer": True,
        "reconciliation_halted": False,
        "kill_switch": False,
    }
    facts.update(overrides)
    return facts


def _durable(
    *,
    order_id="ord_f9edfa0a41984a29892c94eee94b0b22",
    symbol="SOPHUSDT",
    side=OrderSide.SELL,
    quantity="3000",
    filled="0",
    status=OrderStatus.OPEN,
    exchange_order_id="sim_81ef1044f5ee4571b201ac49972f43db",
    age_seconds=7 * 3600,
):
    now = datetime.now(UTC)
    return Order(
        internal_order_id=order_id,
        client_order_id=f"cid_{order_id}",
        exchange_order_id=exchange_order_id,
        symbol=symbol,
        side=side,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price=Decimal("0.00475"),
        quantity=Decimal(quantity),
        filled_quantity=Decimal(filled),
        status=status,
        strategy_id="live_llm",
        created_at=now - timedelta(seconds=age_seconds),
        updated_at=now - timedelta(seconds=age_seconds),
        metadata={},
    )


def _record(
    *,
    order_id="ord_f9edfa0a41984a29892c94eee94b0b22",
    purpose="ENTRY",
    reconciliation="CONFIRMED_OPEN",
    filled_quantity="0",
    provenance=LEGACY_SOURCE_RUNTIME_SHA,
    resting_timestamp_available=True,
    durable=None,
    broker_hint=None,
):
    return {
        "order_id": order_id,
        "purpose": purpose,
        "reconciliation": reconciliation,
        "filled_quantity": filled_quantity,
        "provenance_sha": provenance,
        "resting_timestamp_available": resting_timestamp_available,
        "durable_order": durable or _durable(order_id=order_id),
        "broker_hint": broker_hint,
    }


def _gate(positions=None, records=None, runtime=None):
    return evaluate_legacy_migration_gate(
        positions=positions if positions is not None else {},
        order_records=records if records is not None else [],
        runtime_facts=runtime if runtime is not None else _healthy_runtime(),
    )


# ------------------------------------------------------------------ G1


def test_G1_zero_state_does_not_use_the_migration_path():
    """With nothing outstanding the migration gate must not be the route."""
    verdict = _gate(positions={}, records=[])
    assert verdict.passed, "zero state must not be blocked"
    assert verdict.eligible_order_ids == ()
    assert verdict.details.get("note") == "NO_LEGACY_ENTRY_TO_MIGRATE"


def test_G1b_normal_gate_is_not_modified_by_this_module():
    """F6.1 must not touch the permanent zero/zero/zero rule."""
    source = pathlib.Path("src/crypto_trader/order/migration_preflight.py").read_text()
    for forbidden in ("POSITIONS_GATE", "UNRESOLVED_ORDERS_GATE", "IMMINENT_PLANS_GATE"):
        assert forbidden not in source, f"F6.1 touched the normal gate: {forbidden}"


# ------------------------------------------------------------------ G2


def test_G2_position_nonzero_blocks():
    positions = {
        "LABUSDT": Position(
            symbol="LABUSDT", base_asset="LAB", quote_asset="USDT",
            quantity=Decimal("-2.4"),
        )
    }
    verdict = _gate(positions=positions, records=[_record()])
    assert verdict.state == GATE_FAIL
    assert R_POSITION_NONZERO in verdict.reason_codes


def test_G2b_a_tiny_position_still_blocks():
    """Size is irrelevant: any exposure means the migration is premature."""
    positions = {
        "X": Position(
            symbol="X", base_asset="X", quote_asset="USDT",
            quantity=Decimal("0.0001"),
        )
    }
    verdict = _gate(positions=positions, records=[_record()])
    assert verdict.state == GATE_FAIL
    assert R_POSITION_NONZERO in verdict.reason_codes


# ------------------------------------------------------------------ G3


def test_G3_only_recoverable_legacy_entries_passes():
    records = [
        _record(order_id="ord_soph"),
        _record(
            order_id="ord_iost",
            durable=_durable(
                order_id="ord_iost",
                symbol="IOSTUSDT",
                side=OrderSide.BUY,
                quantity="2468",
                exchange_order_id="sim_b43a8a98151f4a76a733316dbfbc1b57",
            ),
        ),
    ]
    verdict = _gate(positions={}, records=records)
    assert verdict.state == GATE_PASS, verdict.reason_codes
    assert set(verdict.eligible_order_ids) == {"ord_soph", "ord_iost"}
    assert verdict.blocking_order_ids == ()
    assert verdict.details["legacy_entry_count"] == 2


# ------------------------------------------------------------------ G4-G8


def test_G4_unknown_order_blocks():
    verdict = _gate(records=[_record(reconciliation="UNKNOWN")])
    assert verdict.state == GATE_FAIL
    assert R_ORDER_UNKNOWN in verdict.reason_codes


def test_G5_missing_order_blocks():
    verdict = _gate(records=[_record(reconciliation="MISSING")])
    assert verdict.state == GATE_FAIL
    assert R_ORDER_MISSING in verdict.reason_codes


def test_G6_position_action_orders_block():
    for purpose in ("POSITION_REDUCE", "POSITION_EXIT"):
        verdict = _gate(records=[_record(purpose=purpose)])
        assert verdict.state == GATE_FAIL, purpose
        assert R_POSITION_ACTION_ORDER_PRESENT in verdict.reason_codes


def test_G6b_other_purpose_blocks_with_its_own_code():
    verdict = _gate(records=[_record(purpose="OTHER")])
    assert verdict.state == GATE_FAIL
    assert R_UNSUPPORTED_UNRESOLVED_ORDER_PURPOSE in verdict.reason_codes


def test_G7_identity_mismatch_blocks():
    # The durable row says SOPHUSDT while the surviving broker record says
    # IOSTUSDT under the SAME exchange id: identity cannot be confirmed.
    conflicted = _durable(symbol="IOSTUSDT")
    conflicted.exchange_order_id = "sim_81ef1044f5ee4571b201ac49972f43db"
    verdict = _gate(records=[_record(durable=conflicted, broker_hint=_durable())])
    assert verdict.state == GATE_FAIL
    assert R_IDENTITY_CONTRADICTION in verdict.reason_codes


def test_G8_insufficient_recovery_facts_block():
    no_identity = _durable()
    no_identity.exchange_order_id = None
    verdict = _gate(records=[_record(durable=no_identity)])
    assert verdict.state == GATE_FAIL
    assert R_RECOVERY_FACTS_INSUFFICIENT in verdict.reason_codes


# ------------------------------------------------------------------ G9-G13


def test_G9_lease_unhealthy_blocks():
    verdict = _gate(records=[_record()], runtime=_healthy_runtime(lease_healthy=False))
    assert verdict.state == GATE_FAIL
    assert R_LEASE_UNHEALTHY in verdict.reason_codes


def test_G10_single_writer_false_blocks():
    verdict = _gate(records=[_record()], runtime=_healthy_runtime(single_writer=False))
    assert verdict.state == GATE_FAIL
    assert R_SINGLE_WRITER_FALSE in verdict.reason_codes


def test_G11_reconciliation_halted_blocks():
    verdict = _gate(
        records=[_record()], runtime=_healthy_runtime(reconciliation_halted=True)
    )
    assert verdict.state == GATE_FAIL
    assert R_RECONCILIATION_HALTED in verdict.reason_codes


def test_G12_kill_switch_blocks():
    verdict = _gate(records=[_record()], runtime=_healthy_runtime(kill_switch=True))
    assert verdict.state == GATE_FAIL
    assert R_KILL_SWITCH in verdict.reason_codes


def test_G13_unknown_runtime_fact_yields_unknown_not_a_guess():
    """An unavailable fact must never be downgraded to PASS or FAIL."""
    for key in ("lease_healthy", "single_writer", "reconciliation_halted", "kill_switch"):
        verdict = _gate(records=[_record()], runtime=_healthy_runtime(**{key: None}))
        assert verdict.state == GATE_UNKNOWN, key
        assert R_RUNTIME_STATE_UNKNOWN in verdict.reason_codes


def test_G13b_non_paper_mode_blocks():
    verdict = _gate(records=[_record()], runtime=_healthy_runtime(mode="LIVE"))
    assert verdict.state == GATE_FAIL
    assert R_MODE_NOT_PAPER in verdict.reason_codes


# ------------------------------------------------------------------ G14-G16


def test_G14_partial_legacy_fill_blocks():
    """A factual partial fill implies real exposure."""
    durable = _durable(status=OrderStatus.PARTIALLY_FILLED, quantity="3000", filled="400")
    verdict = _gate(records=[_record(filled_quantity="400", durable=durable)])
    assert verdict.state == GATE_FAIL
    assert R_LEGACY_ENTRY_HAS_FACTUAL_FILL in verdict.reason_codes


def test_G15_created_at_only_blocks():
    """Without a brokered acceptance instant the new runtime cannot TTL it."""
    verdict = _gate(records=[_record(resting_timestamp_available=False)])
    assert verdict.state == GATE_FAIL
    assert R_RESTING_TIMESTAMP_INSUFFICIENT in verdict.reason_codes


def test_G16_wrong_source_runtime_blocks():
    verdict = _gate(records=[_record(provenance="some_other_sha")])
    assert verdict.state == GATE_FAIL
    assert R_PROVENANCE_UNPROVEN in verdict.reason_codes


def test_G16b_unprovable_provenance_is_unknown_not_pass():
    verdict = _gate(records=[_record(provenance=None)])
    assert verdict.state == GATE_UNKNOWN
    assert R_PROVENANCE_UNPROVEN in verdict.reason_codes


# ------------------------------------------------------------------ G17


def test_G17_determinism_over_ten_runs():
    records = [
        _record(order_id="ord_soph"),
        _record(order_id="ord_iost", reconciliation="MISSING"),
    ]

    def snapshot():
        v = _gate(positions={}, records=records)
        return (v.state, v.reason_codes, v.eligible_order_ids, v.blocking_order_ids)

    results = {snapshot() for _ in range(10)}
    assert len(results) == 1, "gate verdict is not deterministic"


# ----------------------------------------------------------- purity / scope


def test_gate_is_a_pure_read_only_checker():
    """§33: the gate must not be able to write, cancel, submit or call a model."""
    source = pathlib.Path("src/crypto_trader/order/migration_preflight.py").read_text()
    for forbidden in (
        "submit_order",
        "cancel_pending",
        "complete_json",
        "try_acquire",
        "session_factory",
        "commit(",
        "UPDATE ",
        "DELETE ",
        "create_task",
        "asyncio",
    ):
        assert forbidden not in source, f"gate is not pure: {forbidden}"


def test_gate_creates_no_executor_or_canceller():
    """§44: a preflight checker only."""
    source = pathlib.Path("src/crypto_trader/order/migration_preflight.py").read_text()
    for forbidden in ("class MigrationExecutor", "def deploy", "def execute_migration"):
        assert forbidden not in source


def test_gate_returns_reason_codes_not_only_a_boolean():
    verdict = _gate(records=[_record(reconciliation="UNKNOWN")])
    payload = verdict.as_dict()
    assert isinstance(payload["reason_codes"], list)
    assert payload["reason_codes"]
    assert set(payload) >= {
        "state",
        "reason_codes",
        "eligible_order_ids",
        "blocking_order_ids",
    }
