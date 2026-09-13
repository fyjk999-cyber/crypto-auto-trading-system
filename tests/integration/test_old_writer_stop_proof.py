"""Pre-start gate: the old execution writer must be PROVEN DEAD before start.

F6.2's repair writes before the lease is acquired, so single-writer exclusivity
cannot be left to "the new process's lease acquisition will fail". A second
writer that starts and repairs first would double-write.

The bias of every assertion here is that UNPROVABLE MUST BLOCK. A stop that
cannot be confirmed is treated exactly like a stop that did not happen, because
the failure mode - two writers on one ledger - is unrecoverable, while a delayed
deployment is not.
"""

from __future__ import annotations

import pathlib

from crypto_trader.runtime.stop_proof import (
    PROOF_FAIL,
    PROOF_PASS,
    PROOF_UNKNOWN,
    R_HEARTBEAT_ADVANCING,
    R_LEASE_UNKNOWN,
    R_LEASE_VALID,
    R_LISTENER_ALIVE,
    R_PID_ALIVE,
    R_PID_UNKNOWN,
    R_WRITER_ACTIVE,
    evaluate_old_writer_stop_proof,
    may_start_new_runtime,
)

OLD_OWNER = "engine_run_old_writer"


def _proven_dead(**overrides):
    facts = {
        "old_pid_alive": False,
        "listener_served_by_old_pid": False,
        "heartbeat_observed_at": "2026-09-13T01:00:00+00:00",
        "heartbeat_now": "2026-09-13T01:00:00+00:00",
        "writer_row_active": False,
        "lease_owner_id": "engine_run_new",
        "expected_old_owner_id": OLD_OWNER,
        "lease_expires_at": "2026-09-13T00:59:00+00:00",
    }
    facts.update(overrides)
    return evaluate_old_writer_stop_proof(**facts)


def test_proven_dead_passes_and_allows_start():
    verdict = _proven_dead()
    assert verdict.state == PROOF_PASS, verdict.reason_codes
    assert may_start_new_runtime(verdict) is True


def test_pid_alive_blocks():
    verdict = _proven_dead(old_pid_alive=True)
    assert verdict.state == PROOF_FAIL
    assert R_PID_ALIVE in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_unprovable_pid_blocks():
    """§18: an unprovable PID must not be read as dead."""
    verdict = _proven_dead(old_pid_alive=None)
    assert verdict.state == PROOF_UNKNOWN
    assert R_PID_UNKNOWN in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_listener_still_serving_blocks():
    verdict = _proven_dead(listener_served_by_old_pid=True)
    assert verdict.state == PROOF_FAIL
    assert R_LISTENER_ALIVE in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_advancing_heartbeat_blocks():
    verdict = _proven_dead(heartbeat_now="2026-09-13T01:00:05+00:00")
    assert verdict.state == PROOF_FAIL
    assert R_HEARTBEAT_ADVANCING in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_absent_heartbeat_facts_block():
    verdict = _proven_dead(heartbeat_observed_at=None)
    assert may_start_new_runtime(verdict) is False


def test_active_writer_row_blocks():
    verdict = _proven_dead(writer_row_active=True)
    assert verdict.state == PROOF_FAIL
    assert R_WRITER_ACTIVE in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_lease_still_held_by_old_owner_blocks():
    verdict = _proven_dead(lease_owner_id=OLD_OWNER)
    assert verdict.state == PROOF_FAIL
    assert R_LEASE_VALID in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_unprovable_lease_blocks():
    verdict = _proven_dead(lease_owner_id=None)
    assert verdict.state == PROOF_UNKNOWN
    assert R_LEASE_UNKNOWN in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_missing_expected_owner_blocks():
    verdict = _proven_dead(expected_old_owner_id=None)
    assert may_start_new_runtime(verdict) is False


def test_expired_lease_is_reported():
    verdict = _proven_dead(lease_expires_at="2020-01-01T00:00:00+00:00")
    assert verdict.details["lease_expired"] is True


def test_sigterm_success_is_not_treated_as_proof():
    """§20: a delivered signal is not an exit.

    The gate has no "signal sent" input at all, so a stop procedure cannot claim
    completion merely because SIGTERM was accepted.
    """
    import ast as _ast

    tree = _ast.parse(pathlib.Path("src/crypto_trader/runtime/stop_proof.py").read_text())
    # Assert on real CALLS/imports, not on prose: the module legitimately names
    # SIGTERM in its docstring while explaining why it is not proof.
    signals = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in {"kill", "terminate", "system", "popen"}:
                signals.add(name)
        elif isinstance(node, _ast.Attribute) and node.attr in {"SIGTERM", "SIGKILL"}:
            signals.add(node.attr)
    assert not signals, f"stop proof can signal processes: {sorted(signals)}"


def test_gate_is_read_only():
    import ast as _ast

    tree = _ast.parse(pathlib.Path("src/crypto_trader/runtime/stop_proof.py").read_text())
    forbidden = {"kill", "terminate", "system", "popen", "commit", "create_task", "submit_order"}
    reached = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in forbidden:
                reached.add(name)
        elif isinstance(node, _ast.Attribute) and node.attr in forbidden:
            reached.add(node.attr)
    assert not reached, f"stop proof is not read-only: {sorted(reached)}"
