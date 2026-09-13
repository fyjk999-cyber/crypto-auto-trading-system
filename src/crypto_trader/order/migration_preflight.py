"""F6.1: legacy order-migration PREFLIGHT GATE.

Purpose
-------
The permanent deployment rule stays ``positions = orders = plans = ZERO``. A
runtime that shipped without ENTRY liveness can never reach that state on its
own: its stale ENTRY orders have no mechanism to expire, so the normal gate
deadlocks. This module decides - from FACTS ONLY - whether a one-time legacy
order migration is safe to ATTEMPT.

It is a checker, not an actor
-----------------------------
It never deploys, cancels, submits, trades, writes the database or calls a
model. It reads facts and returns a verdict plus machine-readable reason codes.
``PASS`` means "safe to attempt the migration", never "deploy now".

The asymmetry is deliberate: every uncertain input BLOCKS. A missing fact is
never treated as a satisfied one, because the failure mode this guards against -
losing or duplicating a real PAPER order during a restart - is unrecoverable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from crypto_trader.order.reconciliation import (
    ORDER_PURPOSE_ENTRY,
    ORDER_PURPOSE_POSITION_EXIT,
    ORDER_PURPOSE_POSITION_REDUCE,
    RECON_MISSING,
    RECON_UNKNOWN,
)
from crypto_trader.order.restart_recovery import (
    IDENTITY_CONTRADICTION,
    RECOVERED_CONFIRMED,
    RECOVERED_PARTIAL,
    classify_recoverability,
)

GATE_PASS = "PASS"
GATE_FAIL = "FAIL"
GATE_UNKNOWN = "UNKNOWN"

#: The runtime whose orders lack F3 ENTRY TTL semantics. Provenance must be
#: provable, never assumed from age.
LEGACY_SOURCE_RUNTIME_SHA = "460553f2d42b8fd650fb1e69b92943c62f31af3f"

# ------------------------------------------------------------- reason codes

R_POSITION_NONZERO = "POSITION_NONZERO"
R_LEGACY_ENTRY_HAS_FACTUAL_FILL = "LEGACY_ENTRY_HAS_FACTUAL_FILL"
R_POSITION_ACTION_ORDER_PRESENT = "POSITION_ACTION_ORDER_PRESENT"
R_UNSUPPORTED_UNRESOLVED_ORDER_PURPOSE = "UNSUPPORTED_UNRESOLVED_ORDER_PURPOSE"
R_ORDER_UNKNOWN = "ORDER_UNKNOWN"
R_ORDER_MISSING = "ORDER_MISSING"
R_IDENTITY_CONTRADICTION = "ORDER_IDENTITY_CONTRADICTION"
R_RECOVERY_FACTS_INSUFFICIENT = "RECOVERY_FACTS_INSUFFICIENT"
R_RESTING_TIMESTAMP_INSUFFICIENT = "RESTING_TIMESTAMP_INSUFFICIENT"
R_PROVENANCE_UNPROVEN = "LEGACY_PROVENANCE_UNPROVEN"
R_LEASE_UNHEALTHY = "LEASE_UNHEALTHY"
R_SINGLE_WRITER_FALSE = "SINGLE_WRITER_FALSE"
R_RECONCILIATION_HALTED = "RECONCILIATION_HALTED"
R_KILL_SWITCH = "KILL_SWITCH_ENGAGED"
R_MODE_NOT_PAPER = "MODE_NOT_PAPER"
R_RUNTIME_STATE_UNKNOWN = "RUNTIME_STATE_UNKNOWN"

#: Reason codes that make the verdict UNKNOWN rather than FAIL: the fact itself
#: is unavailable, so no honest PASS or FAIL can be given.
UNKNOWN_REASON_CODES = frozenset(
    {R_RUNTIME_STATE_UNKNOWN, R_PROVENANCE_UNPROVEN}
)


@dataclass(frozen=True, slots=True)
class GateVerdict:
    state: str
    reason_codes: tuple[str, ...] = ()
    eligible_order_ids: tuple[str, ...] = ()
    blocking_order_ids: tuple[str, ...] = ()
    details: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.state == GATE_PASS

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "reason_codes": list(self.reason_codes),
            "eligible_order_ids": list(self.eligible_order_ids),
            "blocking_order_ids": list(self.blocking_order_ids),
            "details": self.details,
        }


def _resolve(verdicts: list[str], codes: list[str]) -> str:
    if any(v == GATE_FAIL for v in verdicts):
        return GATE_FAIL
    if codes and all(c in UNKNOWN_REASON_CODES for c in codes):
        return GATE_UNKNOWN
    if any(v == GATE_UNKNOWN for v in verdicts):
        return GATE_UNKNOWN
    return GATE_PASS


def _tri(value) -> str:
    """Map a three-state runtime fact to PASS/FAIL/UNKNOWN."""
    if value is None:
        return GATE_UNKNOWN
    return GATE_PASS if value else GATE_FAIL


def evaluate_legacy_migration_gate(
    *,
    positions,
    order_records,
    runtime_facts: dict,
    source_runtime_sha: str | None = None,
) -> GateVerdict:
    """Evaluate the one-time legacy migration gate from facts only.

    ``order_records`` are dicts containing at least ``order_id``, ``purpose``,
    ``reconciliation``, ``filled_quantity``, ``durable_order`` (the ORM/domain
    object F6 classifies) and ``provenance_sha``.
    ``runtime_facts`` carries ``mode``, ``lease_healthy``, ``single_writer``,
    ``reconciliation_halted``, ``kill_switch`` (each True/False/None).
    """
    codes: list[str] = []
    verdicts: list[str] = []
    eligible: list[str] = []
    blocking: list[str] = []
    details: dict = {}

    # ---------------------------------------------------- runtime safety first
    mode = runtime_facts.get("mode")
    if mode is None:
        codes.append(R_RUNTIME_STATE_UNKNOWN)
        verdicts.append(GATE_UNKNOWN)
    elif str(mode).upper() != "PAPER":
        codes.append(R_MODE_NOT_PAPER)
        verdicts.append(GATE_FAIL)

    for key, code in (
        ("lease_healthy", R_LEASE_UNHEALTHY),
        ("single_writer", R_SINGLE_WRITER_FALSE),
    ):
        tri = _tri(runtime_facts.get(key))
        if tri == GATE_UNKNOWN:
            codes.append(R_RUNTIME_STATE_UNKNOWN)
            verdicts.append(GATE_UNKNOWN)
        elif tri == GATE_FAIL:
            codes.append(code)
            verdicts.append(GATE_FAIL)

    for key, code in (
        ("reconciliation_halted", R_RECONCILIATION_HALTED),
        ("kill_switch", R_KILL_SWITCH),
    ):
        # These are INVERTED flags: True means the safety mechanism is engaged
        # and the migration must not proceed. Unknown still means UNKNOWN -
        # an unavailable fact is never read as "not engaged".
        raw = runtime_facts.get(key)
        if raw is None:
            codes.append(R_RUNTIME_STATE_UNKNOWN)
            verdicts.append(GATE_UNKNOWN)
        elif raw is True:
            codes.append(code)
            verdicts.append(GATE_FAIL)

    # ------------------------------------------------------------ positions
    # A hard condition: even a tiny exposure means the migration is premature,
    # because a partially filled legacy entry produces a real position.
    live_positions = [
        p for p in (positions or {}).values() if getattr(p, "quantity", 0) != 0
    ]
    details["position_count"] = len(live_positions)
    if live_positions:
        codes.append(R_POSITION_NONZERO)
        verdicts.append(GATE_FAIL)

    # --------------------------------------------------------------- orders
    expected_sha = source_runtime_sha or LEGACY_SOURCE_RUNTIME_SHA
    legacy_entries: list[str] = []
    for record in order_records or []:
        order_id = str(record.get("order_id", ""))
        purpose = record.get("purpose")
        recon = record.get("reconciliation")

        if recon == RECON_UNKNOWN:
            codes.append(R_ORDER_UNKNOWN)
            verdicts.append(GATE_FAIL)
            blocking.append(order_id)
            continue
        if recon == RECON_MISSING:
            codes.append(R_ORDER_MISSING)
            verdicts.append(GATE_FAIL)
            blocking.append(order_id)
            continue

        if purpose in (ORDER_PURPOSE_POSITION_REDUCE, ORDER_PURPOSE_POSITION_EXIT):
            codes.append(R_POSITION_ACTION_ORDER_PRESENT)
            verdicts.append(GATE_FAIL)
            blocking.append(order_id)
            continue
        if purpose != ORDER_PURPOSE_ENTRY:
            # "OTHER" is not provably an entry, so it cannot ride this path.
            codes.append(R_UNSUPPORTED_UNRESOLVED_ORDER_PURPOSE)
            verdicts.append(GATE_FAIL)
            blocking.append(order_id)
            continue

        # Provenance: an order that cannot be shown to come from the pre-TTL
        # runtime is not a legacy order, whatever its age.
        provenance = record.get("provenance_sha")
        if not provenance:
            codes.append(R_PROVENANCE_UNPROVEN)
            verdicts.append(GATE_UNKNOWN)
            blocking.append(order_id)
            continue
        if str(provenance) != str(expected_sha):
            codes.append(R_PROVENANCE_UNPROVEN)
            verdicts.append(GATE_FAIL)
            blocking.append(order_id)
            continue

        durable = record.get("durable_order")
        outcome = classify_recoverability(
            order=durable,
            broker_hint=record.get("broker_hint"),
        )
        if outcome.verdict == IDENTITY_CONTRADICTION:
            codes.append(R_IDENTITY_CONTRADICTION)
            verdicts.append(GATE_FAIL)
            blocking.append(order_id)
            continue
        if outcome.verdict == RECOVERED_PARTIAL:
            # A partial fill means real exposure exists.
            codes.append(R_LEGACY_ENTRY_HAS_FACTUAL_FILL)
            verdicts.append(GATE_FAIL)
            blocking.append(order_id)
            continue
        if outcome.verdict != RECOVERED_CONFIRMED:
            codes.append(R_RECOVERY_FACTS_INSUFFICIENT)
            verdicts.append(GATE_FAIL)
            blocking.append(order_id)
            continue

        if not record.get("resting_timestamp_available"):
            # Without a brokered acceptance instant the new runtime cannot
            # evaluate the 60s TTL at all, so the entry could never expire.
            codes.append(R_RESTING_TIMESTAMP_INSUFFICIENT)
            verdicts.append(GATE_FAIL)
            blocking.append(order_id)
            continue

        filled = record.get("filled_quantity", "0")
        try:
            if float(str(filled)) > 0:
                codes.append(R_LEGACY_ENTRY_HAS_FACTUAL_FILL)
                verdicts.append(GATE_FAIL)
                blocking.append(order_id)
                continue
        except (TypeError, ValueError):
            codes.append(R_RECOVERY_FACTS_INSUFFICIENT)
            verdicts.append(GATE_FAIL)
            blocking.append(order_id)
            continue

        legacy_entries.append(order_id)
        eligible.append(order_id)

    details["legacy_entry_count"] = len(legacy_entries)
    if not legacy_entries and not codes:
        # Nothing to migrate is not a migration: with zero orders the NORMAL
        # zero/zero/zero gate applies and this path must not be used.
        details["note"] = "NO_LEGACY_ENTRY_TO_MIGRATE"

    state = _resolve(verdicts, codes)
    # Preserve first-seen order while de-duplicating reasons.
    seen: list[str] = []
    for code in codes:
        if code not in seen:
            seen.append(code)
    return GateVerdict(
        state=state,
        reason_codes=tuple(seen),
        eligible_order_ids=tuple(eligible),
        blocking_order_ids=tuple(blocking),
        details=details,
    )
