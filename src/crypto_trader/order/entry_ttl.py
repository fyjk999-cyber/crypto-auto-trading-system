"""F3: short-term ENTRY orders have a finite lifetime.

Business rule
-------------
A short-term new-position ENTRY limit order that has not fully filled within 60
seconds no longer represents a valid view of the market: the price, the factors
and the regime that justified it belong to a different moment. Letting such an
order rest for hours (live evidence: a ``live_llm`` ENTRY rested OPEN, 0/3000
filled, for 278 minutes) means an old opinion silently controls a future fill.

Scope is deliberately narrow. This applies ONLY to ENTRY orders. Position
reduce/exit orders keep their existing 900s liveness policy: they are protective
actions whose late completion is usually *desirable*, and shortening them would
change risk behaviour rather than order hygiene.

Policy, not mechanism
---------------------
This module decides WHAT should happen and records WHY. It does not place
orders, does not cancel by itself, and never invents state:

    resting < TTL                          -> HOLD (no cancel, no expiry)
    terminal at the broker                 -> NO_CANCEL (factual state wins)
    reconciliation UNKNOWN / MISSING       -> HOLD (reconcile; never guess)
    CANCEL_PENDING already                 -> NO_CANCEL (idempotency)
    confirmed live AND >= TTL              -> CANCEL_REMAINING

Cancelling is execution policy and stays ``RECONCILE_THEN_CANCEL_ONLY``: no
replacement, no reprice, no market conversion, no resubmission.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.order.reconciliation import (
    ORDER_PURPOSE_ENTRY,
    RECON_CONFIRMED_CANCELLED,
    RECON_CONFIRMED_FILLED,
    RECON_CONFIRMED_OPEN,
    RECON_CONFIRMED_PARTIALLY_FILLED,
    RECON_CONFIRMED_REJECTED,
    RECON_MISSING,
    RECON_UNKNOWN,
)

#: Business rule: a short-term ENTRY intent lives 60 seconds.
SHORT_TERM_ENTRY_TTL_SECONDS = 60.0

#: Legacy persisted value; the column is a string there, so accept both.
ENTRY_ORDER_TTL_EXPIRED = "ENTRY_ORDER_TTL_EXPIRED"

ACTION_HOLD = "HOLD"
ACTION_NO_CANCEL_TERMINAL = "NO_CANCEL_TERMINAL"
ACTION_NO_CANCEL_ALREADY_PENDING = "NO_CANCEL_ALREADY_PENDING"
ACTION_NO_CANCEL_UNRECONCILED = "NO_CANCEL_UNRECONCILED"
ACTION_CANCEL_REMAINING = "CANCEL_REMAINING"
ACTION_NOT_APPLICABLE = "NOT_APPLICABLE"

#: Statuses that mean a cancel has already been requested.
_CANCEL_IN_FLIGHT_STATUSES = ("CANCEL_PENDING",)

#: Durable statuses eligible for entry liveness at all.
_ENTRY_LIVE_STATUSES = ("ACKNOWLEDGED", "OPEN", "PARTIALLY_FILLED")


@dataclass(frozen=True, slots=True)
class EntryTtlDecision:
    action: str
    reason: str
    order_id: str
    purpose: str
    resting_age_seconds: float | None
    ttl_seconds: float
    filled_quantity: str
    remaining_quantity: str
    cancel_remaining_only: bool

    @property
    def should_cancel(self) -> bool:
        return self.action == ACTION_CANCEL_REMAINING

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "reason": self.reason,
            "order_id": self.order_id,
            "purpose": self.purpose,
            "resting_age_seconds": self.resting_age_seconds,
            "ttl_seconds": self.ttl_seconds,
            "filled_quantity": self.filled_quantity,
            "remaining_quantity": self.remaining_quantity,
            "cancel_remaining_only": self.cancel_remaining_only,
        }


def resting_age_seconds(
    *,
    opened_at: datetime | None,
    acknowledged_at: datetime | None,
    created_at: datetime | None = None,
    now: datetime | None = None,
) -> float | None:
    """Age of the order's CONFIRMED RESTING time, in seconds.

    Only brokered acceptance counts: ``opened_at`` (the factual resting start)
    or ``acknowledged_at`` (the factual acceptance). ``created_at`` is accepted
    as an argument for diagnostic callers but is deliberately NOT a fallback,
    because a locally created object proves nothing about whether a broker ever
    accepted it - and cancelling on local age would expire an intent that may
    still be in submission.

    Returns None when no acceptance instant exists. None means UNKNOWN, and an
    unknown resting age must never be treated as "old enough".
    """
    reference = opened_at or acknowledged_at
    if reference is None:
        return None
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (moment - reference).total_seconds()


#: Statuses that do NOT prove broker acceptance. An order in one of these may be
#: well past 60s by local age and must still not be TTL-cancelled.
NOT_YET_RESTING_STATUSES = ("CREATED", "VALIDATED", "SUBMITTING")


def evaluate_entry_ttl(
    *,
    fact,
    durable_status: str,
    resting_age: float | None,
    ttl_seconds: float = SHORT_TERM_ENTRY_TTL_SECONDS,
) -> EntryTtlDecision:
    """Decide the TTL action for ONE reconciled order.

    ``fact`` is an ``OrderReconciliationFact`` - the only source of truth about
    whether the order is still live. The decision NEVER relies on the durable
    status alone, because the durable row is what may be stale.
    """
    order_id = getattr(fact, "order_id", "") or ""
    purpose = getattr(fact, "purpose", "") or ""
    filled = str(getattr(fact, "filled_quantity", "0"))
    remaining = str(getattr(fact, "remaining_quantity", "0"))
    state = getattr(fact, "state", RECON_UNKNOWN)

    def decide(action: str, reason: str, *, cancel: bool = False) -> EntryTtlDecision:
        return EntryTtlDecision(
            action=action,
            reason=reason,
            order_id=order_id,
            purpose=purpose,
            resting_age_seconds=resting_age,
            ttl_seconds=ttl_seconds,
            filled_quantity=filled,
            remaining_quantity=remaining,
            cancel_remaining_only=cancel,
        )

    # Scope: only ENTRY orders carry this lifetime.
    if purpose != ORDER_PURPOSE_ENTRY:
        return decide(ACTION_NOT_APPLICABLE, "PURPOSE_NOT_ENTRY")

    # Factual terminal outcome always wins, even if a timer already fired.
    if state in (
        RECON_CONFIRMED_FILLED,
        RECON_CONFIRMED_CANCELLED,
        RECON_CONFIRMED_REJECTED,
    ):
        return decide(ACTION_NO_CANCEL_TERMINAL, f"TERMINAL_{state}")

    # Not yet resting at the broker: this is a SUBMISSION diagnostic, not an
    # EXPIRE condition. Local age cannot authorise a cancel.
    if str(durable_status) in NOT_YET_RESTING_STATUSES:
        return decide(ACTION_HOLD, "NOT_YET_RESTING_AT_BROKER")

    # Idempotency: a cancel is already in flight.
    if str(durable_status) in _CANCEL_IN_FLIGHT_STATUSES:
        return decide(ACTION_NO_CANCEL_ALREADY_PENDING, "CANCEL_ALREADY_PENDING")

    # Never act on an unreconciled order. UNKNOWN != FAILED and MISSING !=
    # CANCELLED, so neither may authorise a cancel.
    if state in (RECON_UNKNOWN, RECON_MISSING):
        return decide(ACTION_NO_CANCEL_UNRECONCILED, f"UNRECONCILED_{state}")

    if state not in (RECON_CONFIRMED_OPEN, RECON_CONFIRMED_PARTIALLY_FILLED):
        return decide(ACTION_NO_CANCEL_UNRECONCILED, f"UNEXPECTED_STATE_{state}")

    # Reconciled as live. Now, and only now, the clock decides.
    if resting_age is None:
        return decide(ACTION_HOLD, "RESTING_AGE_UNKNOWN")
    if resting_age < ttl_seconds:
        return decide(ACTION_HOLD, "WITHIN_TTL")

    if Decimal(remaining) <= 0:
        # Nothing left to cancel: the factual fill already accounts for it.
        return decide(ACTION_NO_CANCEL_TERMINAL, "NOTHING_REMAINING")

    return decide(
        ACTION_CANCEL_REMAINING,
        ENTRY_ORDER_TTL_EXPIRED,
        cancel=True,
    )


def entry_liveness_eligible(*, purpose: str, durable_status: str) -> bool:
    """Is this order eligible for entry liveness at all?

    Deliberately includes ``live_llm`` ENTRY orders, which the previous
    ``strategy_id == "live_llm_position"`` filter structurally excluded.
    """
    return purpose == ORDER_PURPOSE_ENTRY and str(durable_status) in _ENTRY_LIVE_STATUSES
