"""Pre-start gate: prove the OLD execution writer is dead before a new process starts.

Why this matters here specifically
----------------------------------
F6.2's pre-broker repair writes to the database BEFORE the execution lease is
acquired (engine.py: repair runs inside ``_restore_paper_adapter_state``, the
lease is taken later). So a new runtime cannot rely on "the lease acquisition
will fail if another writer is alive" to keep single-writer exclusivity: the
repair may already have written by then.

The only safe ordering is therefore:

    stop old writer -> PROVE it is dead -> start new runtime

This module evaluates that proof from OBSERVABLE signals. It is read-only and
never stops, starts or signals anything. A signal being delivered successfully
is explicitly NOT proof: SIGTERM returning does not mean the process exited.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

PROOF_PASS = "PASS"
PROOF_FAIL = "FAIL"
PROOF_UNKNOWN = "UNKNOWN"

R_PID_ALIVE = "OLD_PID_STILL_ALIVE"
R_PID_UNKNOWN = "OLD_PID_UNPROVABLE"
R_LISTENER_ALIVE = "OLD_HTTP_LISTENER_STILL_SERVING"
R_HEARTBEAT_ADVANCING = "OLD_HEARTBEAT_STILL_ADVANCING"
R_HEARTBEAT_UNKNOWN = "OLD_HEARTBEAT_UNPROVABLE"
R_WRITER_ACTIVE = "OLD_WRITER_ROW_STILL_ACTIVE"
R_LEASE_VALID = "OLD_LEASE_STILL_VALID"
R_LEASE_UNKNOWN = "OLD_LEASE_UNPROVABLE"


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


def evaluate_old_writer_stop_proof(
    *,
    old_pid_alive: bool | None,
    listener_served_by_old_pid: bool | None,
    heartbeat_observed_at: str | None,
    heartbeat_now: str | None,
    writer_row_active: bool | None,
    lease_owner_id: str | None,
    expected_old_owner_id: str | None,
    lease_expires_at: str | None,
) -> StopProofVerdict:
    """Judge whether the previous execution writer is provably gone.

    Every input is three-state: ``None`` means "could not be established", which
    yields UNKNOWN rather than being optimistically read as "dead".
    """
    codes: list[str] = []
    details: dict = {}

    if old_pid_alive is None:
        codes.append(R_PID_UNKNOWN)
    elif old_pid_alive:
        codes.append(R_PID_ALIVE)

    if listener_served_by_old_pid:
        codes.append(R_LISTENER_ALIVE)

    # Heartbeat must have STOPPED advancing.
    if not heartbeat_observed_at or not heartbeat_now:
        codes.append(R_HEARTBEAT_UNKNOWN)
    elif str(heartbeat_observed_at) != str(heartbeat_now):
        codes.append(R_HEARTBEAT_ADVANCING)

    if writer_row_active:
        codes.append(R_WRITER_ACTIVE)

    # The lease must no longer be held by the old owner. An unreadable lease is
    # UNKNOWN: "I could not check" is not "it is free".
    if expected_old_owner_id is None or lease_owner_id is None:
        codes.append(R_LEASE_UNKNOWN)
    elif str(lease_owner_id) == str(expected_old_owner_id):
        codes.append(R_LEASE_VALID)

    details["lease_expires_at"] = lease_expires_at
    if lease_expires_at:
        try:
            expiry = datetime.fromisoformat(str(lease_expires_at).replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            details["lease_expired"] = expiry <= datetime.now(UTC)
        except ValueError:
            details["lease_expired"] = None

    seen: list[str] = []
    for code in codes:
        if code not in seen:
            seen.append(code)

    unknown_only = {
        R_PID_UNKNOWN,
        R_HEARTBEAT_UNKNOWN,
        R_LEASE_UNKNOWN,
    }
    if not seen:
        state = PROOF_PASS
    elif set(seen) <= unknown_only:
        state = PROOF_UNKNOWN
    else:
        state = PROOF_FAIL

    return StopProofVerdict(state=state, reason_codes=tuple(seen), details=details)


def may_start_new_runtime(verdict: StopProofVerdict) -> bool:
    """Hard gate: the new process may start ONLY on a proven-dead old writer.

    Deliberately NOT "unless proven alive": an unprovable stop must block, because
    starting a second writer would double-write the ledger.
    """
    return verdict.proved_dead
