"""F6.3: one-time EMERGENCY ACTIVE-POSITION migration gate.

Why this exists
---------------
The permanent deployment gate is ZERO positions / ZERO orders / ZERO plans, and
it stays that way. But a runtime that shipped without ENTRY liveness can never
reach it: its stale ENTRY orders have no way to expire. Combined with the F6.2
incident - a pre-broker rejection recorded as UNKNOWN, permanently blocking a
plan's REDUCE/EXIT path - the old runtime is in a deadlock it cannot leave on
its own.

This is NOT a general "deploy while holding a position" back door. It is hard
bound to ONE incident class:

    incident_class     = PRE_BROKER_POSITION_ACTION_DEADLOCK
    source_runtime     = 460553f2...
    target_min_lineage = bccb8a48...

It answers a single question: can THIS factual position survive ONE controlled
PAPER migration, given that the blocking UNKNOWN is provably a pre-broker
rejection rather than an order that might exist at the exchange?

It is a pure read-only checker. It never submits, cancels, fills, closes a
position, changes an order/plan, writes the database, deploys or restarts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from crypto_trader.order.pre_broker_rejection import (
    CLASSIFICATION_PRE_BROKER_REJECTION_CONFIRMED,
    classify_pre_broker_rejection,
)
from crypto_trader.order.reconciliation import (
    ORDER_PURPOSE_ENTRY,
    ORDER_PURPOSE_POSITION_EXIT,
    ORDER_PURPOSE_POSITION_REDUCE,
)

GATE_PASS = "PASS"
GATE_FAIL = "FAIL"
GATE_UNKNOWN = "UNKNOWN"

#: Hard binding: this gate is valid for exactly one incident class.
INCIDENT_CLASS = "PRE_BROKER_POSITION_ACTION_DEADLOCK"
SOURCE_RUNTIME_SHA = "460553f2d42b8fd650fb1e69b92943c62f31af3f"
TARGET_MIN_LINEAGE_SHA = "bccb8a4881faf04226b51e46c39d5e62dedf1515"

R_POSITION_COUNT_NOT_ONE = "POSITION_COUNT_NOT_ONE"
R_POSITION_FACT_CONTRADICTION = "POSITION_FACT_CONTRADICTION"
R_PLAN_NOT_FOUND = "ACTIVE_PLAN_NOT_FOUND"
R_PLAN_NOT_ACTIVE = "ACTIVE_PLAN_STATE_INVALID"
R_PLAN_POSITION_MISMATCH = "PLAN_POSITION_MISMATCH"
R_UNKNOWN_COUNT_INVALID = "UNKNOWN_COUNT_INVALID"
R_ADDITIONAL_UNKNOWN_ORDER = "ADDITIONAL_UNKNOWN_ORDER"
R_SPECIAL_UNKNOWN_NOT_CONFIRMED = "SPECIAL_UNKNOWN_NOT_PRE_BROKER_CONFIRMED"
R_SPECIAL_UNKNOWN_DRIFT = "SPECIAL_UNKNOWN_FACT_DRIFT"
R_OTHER_POSITION_ACTION_PRESENT = "OTHER_POSITION_ACTION_ORDER_PRESENT"
R_PARTIAL_FILL_IN_SCOPE = "PARTIAL_FILL_STILL_UNRESOLVED"
R_MISSING_ORDER = "MISSING_ORDER_PRESENT"
R_IDENTITY_CONTRADICTION = "IDENTITY_CONTRADICTION"
R_LEGACY_ENTRY_UNRECOVERABLE = "LEGACY_ENTRY_NOT_RECOVERABLE"
R_RUNTIME_STATE_UNKNOWN = "RUNTIME_STATE_UNKNOWN"
R_RUNTIME_SAFETY_FAILED = "RUNTIME_SAFETY_FAILED"
R_SOURCE_RUNTIME_MISMATCH = "SOURCE_RUNTIME_MISMATCH"
R_TARGET_LINEAGE_MISMATCH = "TARGET_LINEAGE_MISMATCH"

#: Reasons that mean "this fact could not be read", not "this fact is unsafe".
UNKNOWN_REASON_CODES = frozenset({R_RUNTIME_STATE_UNKNOWN})


@dataclass(frozen=True, slots=True)
class EmergencyGateVerdict:
    state: str
    incident_class: str = INCIDENT_CLASS
    reason_codes: tuple[str, ...] = ()
    special_unknown_order_id: str | None = None
    position_symbol: str | None = None
    position_quantity: str | None = None
    legacy_entry_ids: tuple[str, ...] = ()
    details: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.state == GATE_PASS

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "incident_class": self.incident_class,
            "reason_codes": list(self.reason_codes),
            "special_unknown_order_id": self.special_unknown_order_id,
            "position_symbol": self.position_symbol,
            "position_quantity": self.position_quantity,
            "legacy_entry_ids": list(self.legacy_entry_ids),
            "details": self.details,
        }


def _lineage_ok(candidate: str | None, required: str) -> bool | None:
    """None when lineage cannot be judged from the inputs given."""
    if not candidate:
        return None
    return str(candidate) == required or str(candidate).startswith(required[:7])


def _runtime_safety(runtime_facts: dict, codes: list[str]) -> int:
    """Check mode/lease/writer/halt/kill. Returns the unknown-fact count."""
    unknowns = 0
    mode = runtime_facts.get("mode")
    if mode is None:
        codes.append(R_RUNTIME_STATE_UNKNOWN)
        unknowns += 1
    elif str(mode).upper() != "PAPER":
        codes.append(R_RUNTIME_SAFETY_FAILED)

    for key, expected in (
        ("lease_healthy", True),
        ("single_writer", True),
        ("reconciliation_halted", False),
        ("kill_switch", False),
    ):
        raw = runtime_facts.get(key)
        if raw is None:
            codes.append(R_RUNTIME_STATE_UNKNOWN)
            unknowns += 1
        elif bool(raw) is not expected:
            codes.append(R_RUNTIME_SAFETY_FAILED)
    return unknowns


def _position_checks(
    positions, runtime_facts: dict, codes: list[str]
) -> tuple[int, str | None, str | None]:
    """Returns (live_count, symbol, quantity)."""
    live = [p for p in (positions or {}).values() if getattr(p, "quantity", 0) != 0]
    if len(live) != 1:
        # Zero means the NORMAL gate applies and this one must not be used;
        # more than one is outside this incident's scope entirely.
        codes.append(R_POSITION_COUNT_NOT_ONE)
        return len(live), None, None

    only = live[0]
    symbol = str(getattr(only, "symbol", "") or "")
    quantity = str(getattr(only, "quantity", ""))
    if not symbol or quantity in ("", "0"):
        codes.append(R_POSITION_FACT_CONTRADICTION)
    return len(live), symbol, quantity


def _plan_checks(
    runtime_facts: dict,
    codes: list[str],
    position_symbol: str | None,
    expected_plan_id: str | None,
) -> None:
    plan = runtime_facts.get("active_plan") or {}
    plan_id = plan.get("trade_plan_id")
    if not plan_id:
        codes.append(R_PLAN_NOT_FOUND)
        return
    if expected_plan_id and str(plan_id) != str(expected_plan_id):
        codes.append(R_PLAN_NOT_FOUND)
    if str(plan.get("state") or "") != "ACTIVE":
        codes.append(R_PLAN_NOT_ACTIVE)
    if position_symbol and str(plan.get("symbol") or "") != position_symbol:
        codes.append(R_PLAN_POSITION_MISMATCH)


def _side_consistency(
    runtime_facts: dict, position_quantity: str | None, codes: list[str]
) -> int:
    """The position sign must be explainable by the recorded direction."""
    if position_quantity is None:
        return 0
    side = runtime_facts.get("position_side")
    if side is None:
        codes.append(R_RUNTIME_STATE_UNKNOWN)
        return 1
    upper = str(side).upper()
    negative = position_quantity.startswith("-")
    consistent = (upper == "LONG" and not negative) or (upper == "SHORT" and negative)
    if not consistent:
        codes.append(R_PLAN_POSITION_MISMATCH)
    return 0


def evaluate_emergency_active_position_gate(
    *,
    positions,
    order_records,
    runtime_facts: dict,
    expected_plan_id: str | None = None,
    expected_unknown_order_id: str | None = None,
    source_runtime_sha: str | None = None,
    target_lineage_sha: str | None = None,
) -> EmergencyGateVerdict:
    """Evaluate the emergency gate from FACTS ONLY."""
    codes: list[str] = []
    details: dict = {}

    unknowns = _runtime_safety(runtime_facts, codes)

    source = source_runtime_sha or runtime_facts.get("runtime_sha")
    if source is None:
        codes.append(R_RUNTIME_STATE_UNKNOWN)
        unknowns += 1
    elif str(source) != SOURCE_RUNTIME_SHA:
        codes.append(R_SOURCE_RUNTIME_MISMATCH)

    lineage = target_lineage_sha or runtime_facts.get("target_sha")
    lineage_ok = _lineage_ok(lineage, TARGET_MIN_LINEAGE_SHA)
    if lineage_ok is None:
        codes.append(R_RUNTIME_STATE_UNKNOWN)
        unknowns += 1
    elif lineage_ok is False:
        codes.append(R_TARGET_LINEAGE_MISMATCH)

    live_count, position_symbol, position_quantity = _position_checks(
        positions, runtime_facts, codes
    )
    details["position_count"] = live_count

    _plan_checks(runtime_facts, codes, position_symbol, expected_plan_id)
    unknowns += _side_consistency(runtime_facts, position_quantity, codes)

    # ------------------------------------------------ special UNKNOWN + scope
    records = list(order_records or [])
    unknown_records = [r for r in records if str(r.get("reconciliation")) == "UNKNOWN"]
    missing_records = [r for r in records if str(r.get("reconciliation")) == "MISSING"]
    details["unknown_count"] = len(unknown_records)
    details["missing_count"] = len(missing_records)

    if missing_records:
        codes.append(R_MISSING_ORDER)

    if len(unknown_records) != 1:
        codes.append(R_UNKNOWN_COUNT_INVALID)
        if len(unknown_records) > 1:
            codes.append(R_ADDITIONAL_UNKNOWN_ORDER)

    special_id = (
        str(unknown_records[0].get("order_id")) if len(unknown_records) == 1 else None
    )
    if expected_unknown_order_id and special_id != str(expected_unknown_order_id):
        codes.append(R_SPECIAL_UNKNOWN_DRIFT)

    legacy_entries: list[str] = []
    for record in records:
        order_id = str(record.get("order_id", ""))
        purpose = record.get("purpose")
        recon = record.get("reconciliation")

        if recon == "UNKNOWN":
            verdict = classify_pre_broker_rejection(
                status="UNKNOWN",
                exchange_order_id=record.get("exchange_order_id"),
                filled_quantity=record.get("filled_quantity", 0),
                durable_fill_count=record.get("durable_fill_count", 0),
                failure_reason=record.get("failure_reason"),
                audit_lineage_proves_pre_broker=bool(
                    record.get("pre_broker_lineage_proven")
                ),
            )
            details.setdefault("special_unknown", {})[order_id] = verdict.as_dict()
            if verdict.classification != CLASSIFICATION_PRE_BROKER_REJECTION_CONFIRMED:
                codes.append(R_SPECIAL_UNKNOWN_NOT_CONFIRMED)
            continue

        if purpose in (ORDER_PURPOSE_POSITION_REDUCE, ORDER_PURPOSE_POSITION_EXIT):
            # Any OTHER unresolved position action is outside this incident.
            codes.append(R_OTHER_POSITION_ACTION_PRESENT)
            continue

        if purpose == ORDER_PURPOSE_ENTRY:
            try:
                if float(str(record.get("filled_quantity", 0))) > 0:
                    codes.append(R_PARTIAL_FILL_IN_SCOPE)
                    continue
            except (TypeError, ValueError):
                codes.append(R_LEGACY_ENTRY_UNRECOVERABLE)
                continue
            recoverable = (
                record.get("exchange_order_id")
                and record.get("provenance_sha")
                and record.get("resting_timestamp_available")
                and record.get("recoverable_confirmed")
            )
            if not recoverable:
                codes.append(R_LEGACY_ENTRY_UNRECOVERABLE)
                continue
            legacy_entries.append(order_id)
            continue

        # Unclassified or unsupported purpose: never silently allowed through.
        if record.get("identity_conflict"):
            codes.append(R_IDENTITY_CONTRADICTION)
        else:
            codes.append(R_LEGACY_ENTRY_UNRECOVERABLE)

    details["legacy_entry_count"] = len(legacy_entries)

    seen: list[str] = []
    for code in codes:
        if code not in seen:
            seen.append(code)

    # A "could not read this fact" reason means UNKNOWN, not FAIL: reporting a
    # failure would claim knowledge we do not have. Only reasons asserting a
    # concrete unsafe condition produce FAIL.
    if not seen:
        state = GATE_UNKNOWN if unknowns else GATE_PASS
    elif set(seen) <= UNKNOWN_REASON_CODES:
        state = GATE_UNKNOWN
    else:
        state = GATE_FAIL

    return EmergencyGateVerdict(
        state=state,
        reason_codes=tuple(seen),
        special_unknown_order_id=special_id,
        position_symbol=position_symbol,
        position_quantity=position_quantity,
        legacy_entry_ids=tuple(legacy_entries),
        details=details,
    )
