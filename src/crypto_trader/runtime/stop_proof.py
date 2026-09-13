"""Pre-start gate: prove the OLD execution writer is dead before a new process starts.

Why this matters here specifically
----------------------------------
F6.2's pre-broker repair writes to the database BEFORE the execution lease is
acquired (the repair runs inside ``_restore_paper_adapter_state``; the lease is
taken later in ``start()``). Single-writer exclusivity therefore cannot be
delegated to "the new process's lease acquisition will fail if a writer is
alive" - by then the repair may already have written, and two writers on one
ledger is unrecoverable.

The only safe ordering is:

    stop old writer -> PROVE it is dead -> start new runtime

Hard rules encoded here
-----------------------
* ``None`` means UNREADABLE, and UNREADABLE IS NOT SAFE. Every input is
  three-state and an unreadable one yields UNKNOWN, which blocks.
* ANY execution lease that is still active blocks, whatever its owner: before the
  new runtime starts there is no legitimate reason for one to exist, and an
  unexpected owner is exactly the case worth refusing.
* A listener on the runtime port blocks even if it is not the old PID's - it may
  be another runtime or a stray writer.
* EngineRun state/ended_at is a real fact, NOT a heartbeat. There is no
  periodic heartbeat write for it, so two equal samples prove nothing and are
  not used as evidence.

This module is a pure evaluator: it never signals, stops, starts, mutates a lease
or writes anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

PROOF_PASS = "PASS"
PROOF_FAIL = "FAIL"
PROOF_UNKNOWN = "UNKNOWN"

R_PID_ALIVE = "OLD_PID_STILL_ALIVE"
R_PID_UNKNOWN = "OLD_PID_UNPROVABLE"

R_LISTENER_PRESENT = "RUNTIME_LISTENER_PRESENT"
R_LISTENER_UNKNOWN = "OLD_HTTP_LISTENER_UNPROVABLE"

R_RUN_NOT_STOPPED = "OLD_ENGINE_RUN_NOT_STOPPED"
R_RUN_ENDED_AT_MISSING = "OLD_ENGINE_RUN_ENDED_AT_MISSING"
R_RUN_UNKNOWN = "OLD_ENGINE_RUN_UNPROVABLE"

R_LEASE_ACTIVE = "EXECUTION_LEASE_STILL_ACTIVE"
R_LEASE_UNREADABLE = "EXECUTION_LEASE_UNREADABLE"
R_LEASE_EXPIRY_MALFORMED = "EXECUTION_LEASE_EXPIRY_MALFORMED"

#: Reasons that mean "this fact could not be established".
UNKNOWN_REASON_CODES = frozenset(
    {
        R_PID_UNKNOWN,
        R_LISTENER_UNKNOWN,
        R_RUN_UNKNOWN,
        R_LEASE_UNREADABLE,
        # A lease row whose expiry cannot be parsed is unreadable in the only
        # sense that matters, so it must not be treated as "free".
        R_LEASE_EXPIRY_MALFORMED,
    }
)

STOPPED_RUN_STATES = frozenset({"STOPPED", "STOPPING"})


@dataclass(frozen=True, slots=True)
class StopProofVerdict:
    state: str
    reason_codes: tuple[str, ...] = ()
    details: dict = field(default_factory=dict)

    @property
    def proved_dead(self) -> bool:
        return self.state == PROOF_PASS

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "reason_codes": list(self.reason_codes),
            "details": self.details,
        }


def _epoch(value) -> float | None:
    """Parse an expiry into epoch seconds. Accepts float/int epoch or ISO text."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def evaluate_old_writer_stop_proof(
    *,
    old_pid_alive: bool | None,
    runtime_listener_present: bool | None,
    old_run_state: str | None,
    old_run_ended_at: str | None,
    lease_query_ok: bool,
    lease_expires_at,
    observed_now_epoch: float,
    lease_owner_id: str | None = None,
) -> StopProofVerdict:
    """Judge whether the previous execution writer is PROVABLY gone.

    All three-state inputs accept None to mean "could not be established", which
    yields UNKNOWN rather than an optimistic reading.
    """
    codes: list[str] = []
    details: dict = {"lease_owner_id": lease_owner_id}

    # ------------------------------------------------------------- process
    if old_pid_alive is None:
        codes.append(R_PID_UNKNOWN)
    elif old_pid_alive:
        codes.append(R_PID_ALIVE)

    # ------------------------------------------------------------ listener
    # ANY listener on the runtime port blocks: it need not be the old PID's for
    # the port to be occupied by something that may write.
    if runtime_listener_present is None:
        codes.append(R_LISTENER_UNKNOWN)
    elif runtime_listener_present:
        codes.append(R_LISTENER_PRESENT)

    # ----------------------------------------------------------- engine run
    if not old_run_state:
        codes.append(R_RUN_UNKNOWN)
    else:
        if str(old_run_state).upper() not in STOPPED_RUN_STATES:
            codes.append(R_RUN_NOT_STOPPED)
        if not old_run_ended_at:
            # A stopped row without an end timestamp is not proof of a clean stop.
            codes.append(R_RUN_ENDED_AT_MISSING)

    # --------------------------------------------------------------- lease
    if not lease_query_ok:
        codes.append(R_LEASE_UNREADABLE)
    else:
        expiry = _epoch(lease_expires_at)
        details["lease_expires_at_epoch"] = expiry
        if expiry is None:
            # A readable lease row whose expiry cannot be parsed is unreadable in
            # the only sense that matters.
            codes.append(R_LEASE_EXPIRY_MALFORMED)
        elif expiry > float(observed_now_epoch):
            # Owner is deliberately irrelevant: any live execution lease blocks.
            codes.append(R_LEASE_ACTIVE)
        else:
            details["lease_expired"] = True

    seen: list[str] = []
    for code in codes:
        if code not in seen:
            seen.append(code)

    if not seen:
        state = PROOF_PASS
    elif set(seen) <= UNKNOWN_REASON_CODES:
        state = PROOF_UNKNOWN
    else:
        state = PROOF_FAIL

    return StopProofVerdict(state=state, reason_codes=tuple(seen), details=details)


def may_start_new_runtime(verdict: StopProofVerdict) -> bool:
    """Hard gate: start ONLY on a proven-dead old writer.

    Deliberately not "unless proven alive": an UNPROVABLE stop must also block,
    because a second writer that repairs before acquiring the lease would
    double-write.
    """
    return verdict.proved_dead
