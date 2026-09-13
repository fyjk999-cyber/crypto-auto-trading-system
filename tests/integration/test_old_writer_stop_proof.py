"""Pre-start gate: the old execution writer must be PROVEN DEAD before start.

F6.2's repair writes BEFORE the lease is acquired, so single-writer exclusivity
cannot be left to "the new process's lease acquisition will fail". A second
writer that repairs first would double-write the ledger.

Every assertion here encodes one rule: UNREADABLE IS NOT SAFE. A fact that could
not be established blocks exactly like a fact that is bad, because the failure
mode - two writers on one ledger - is unrecoverable while a delayed deployment
is not.

T1-T10 are the negative/positive matrix required by the hardening directive.
"""

from __future__ import annotations

import pathlib

from crypto_trader.runtime.stop_proof import (
    PROOF_FAIL,
    PROOF_PASS,
    PROOF_UNKNOWN,
    R_LEASE_ACTIVE,
    R_LEASE_EXPIRY_MALFORMED,
    R_LEASE_UNREADABLE,
    R_LISTENER_PRESENT,
    R_LISTENER_UNKNOWN,
    R_PID_ALIVE,
    R_PID_UNKNOWN,
    R_RUN_ENDED_AT_MISSING,
    R_RUN_NOT_STOPPED,
    R_RUN_UNKNOWN,
    _epoch,
    evaluate_old_writer_stop_proof,
    may_start_new_runtime,
)

OLD_OWNER = "engine_run_old_writer"
NOW = 1_700_000_000.0


def _facts(**overrides):
    base = {
        "old_pid_alive": False,
        "runtime_listener_present": False,
        "old_run_state": "STOPPED",
        "old_run_ended_at": "2026-09-13T01:00:00+00:00",
        "lease_query_ok": True,
        "lease_expires_at": 0.0,  # released tombstone
        "observed_now_epoch": NOW,
        "lease_owner_id": OLD_OWNER,
    }
    base.update(overrides)
    return evaluate_old_writer_stop_proof(**base)


# ------------------------------------------------------------------ T10 first


def test_T10_fully_proven_stop_passes():
    verdict = _facts()
    assert verdict.state == PROOF_PASS, verdict.reason_codes
    assert may_start_new_runtime(verdict) is True


# ------------------------------------------------------------------ T1/T3-T6


def test_T1_listener_unknown_is_unknown_and_blocks():
    """listener=None must NOT be read as False."""
    verdict = _facts(runtime_listener_present=None)
    assert verdict.state == PROOF_UNKNOWN
    assert R_LISTENER_UNKNOWN in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_T2_writer_run_state_unreadable_is_unknown():
    verdict = _facts(old_run_state=None)
    assert verdict.state == PROOF_UNKNOWN
    assert R_RUN_UNKNOWN in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_T3_active_lease_owned_by_old_owner_blocks():
    verdict = _facts(lease_expires_at=NOW + 60)
    assert verdict.state == PROOF_FAIL
    assert R_LEASE_ACTIVE in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_T4_active_lease_owned_by_a_DIFFERENT_owner_blocks():
    """Owner is irrelevant: any live execution lease blocks."""
    verdict = _facts(lease_expires_at=NOW + 60, lease_owner_id="engine_run_someone_else")
    assert verdict.state == PROOF_FAIL
    assert R_LEASE_ACTIVE in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_T4b_active_lease_with_unknown_owner_still_blocks():
    verdict = _facts(lease_expires_at=NOW + 60, lease_owner_id=None)
    assert verdict.state == PROOF_FAIL
    assert may_start_new_runtime(verdict) is False


def test_T5_unreadable_expiry_is_unknown():
    verdict = _facts(lease_expires_at="not-a-time")
    assert verdict.state == PROOF_UNKNOWN
    assert R_LEASE_EXPIRY_MALFORMED in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_T6_lease_query_failure_is_unknown_not_free():
    verdict = _facts(lease_query_ok=False, lease_expires_at=None)
    assert verdict.state == PROOF_UNKNOWN
    assert R_LEASE_UNREADABLE in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


# ------------------------------------------------------------------ T7/T8/T9


def test_T7_pid_dead_but_listener_present_blocks():
    verdict = _facts(runtime_listener_present=True)
    assert verdict.state == PROOF_FAIL
    assert R_LISTENER_PRESENT in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_T8_pid_dead_listener_absent_run_stopped_but_lease_active_blocks():
    verdict = _facts(lease_expires_at=NOW + 3600)
    assert verdict.state == PROOF_FAIL
    assert R_LEASE_ACTIVE in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_T9_sigterm_delivered_but_pid_alive_blocks():
    """A delivered signal is not an exit."""
    verdict = _facts(old_pid_alive=True)
    assert verdict.state == PROOF_FAIL
    assert R_PID_ALIVE in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


# ------------------------------------------------------------ extra fail-closed


def test_unprovable_pid_blocks():
    verdict = _facts(old_pid_alive=None)
    assert verdict.state == PROOF_UNKNOWN
    assert R_PID_UNKNOWN in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_run_state_not_stopped_blocks():
    verdict = _facts(old_run_state="RUNNING")
    assert verdict.state == PROOF_FAIL
    assert R_RUN_NOT_STOPPED in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_stopped_run_without_ended_at_blocks():
    verdict = _facts(old_run_ended_at=None)
    assert verdict.state == PROOF_FAIL
    assert R_RUN_ENDED_AT_MISSING in verdict.reason_codes
    assert may_start_new_runtime(verdict) is False


def test_stopping_run_is_accepted_as_stopped():
    verdict = _facts(old_run_state="STOPPING")
    assert verdict.state == PROOF_PASS


# ------------------------------------------------------------------ epoch facts


def test_lease_expiry_accepts_epoch_float():
    assert _epoch(1_700_000_000.0) == 1_700_000_000.0
    assert _epoch("1700000000.0") == 1_700_000_000.0


def test_lease_expiry_accepts_iso_text():
    parsed = _epoch("2026-09-13T01:00:00+00:00")
    assert parsed is not None and parsed > 0


def test_lease_expiry_rejects_garbage():
    assert _epoch("nonsense") is None
    assert _epoch("") is None
    assert _epoch(True) is None


def test_expiry_equal_to_now_counts_as_expired():
    verdict = _facts(lease_expires_at=NOW)
    assert verdict.state == PROOF_PASS


# ------------------------------------------------------------------ honesty rules


def test_engine_run_is_not_used_as_a_heartbeat():
    """Two equal samples are not proof: there is no periodic heartbeat write."""
    import ast as _ast

    # Assert on identifiers actually referenced, not on prose: the module
    # explains in a docstring why a heartbeat is not usable.
    tree = _ast.parse(pathlib.Path("src/crypto_trader/runtime/stop_proof.py").read_text())
    referenced = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Name):
            referenced.add(node.id.lower())
        elif isinstance(node, _ast.Attribute):
            referenced.add(node.attr.lower())
        elif isinstance(node, _ast.arg):
            referenced.add(node.arg.lower())
    for forbidden in ("heartbeat", "renewed_at", "sleep"):
        assert forbidden not in referenced, (
            f"stop proof relies on {forbidden}, which is not a real truth source"
        )


def test_stop_proof_is_read_only():
    import ast as _ast

    tree = _ast.parse(pathlib.Path("src/crypto_trader/runtime/stop_proof.py").read_text())
    forbidden = {
        "kill",
        "terminate",
        "system",
        "popen",
        "commit",
        "create_task",
        "submit_order",
        "cancel_pending",
        "start",
    }
    reached = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in forbidden:
                reached.add(name)
        elif isinstance(node, _ast.Attribute) and node.attr in forbidden:
            reached.add(node.attr)
    assert not reached, f"stop proof is not read-only: {sorted(reached)}"


def test_sigterm_is_not_an_input():
    """The gate has no 'signal was sent' input at all."""
    import ast as _ast

    tree = _ast.parse(pathlib.Path("src/crypto_trader/runtime/stop_proof.py").read_text())
    names = {n.arg.lower() for n in _ast.walk(tree) if isinstance(n, _ast.arg)}
    assert not {n for n in names if "signal" in n or "sigterm" in n}
