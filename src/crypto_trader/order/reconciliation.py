"""Formal ORDER reconciliation — deliberately separate from balances/positions.

Gap this closes
---------------
``ReconciliationService`` compares ledger balances and positions against the
adapter. Unresolved ORDERS had no formal reconciliation visibility at all, so a
resting order could sit for hours with nobody able to state, as a fact, whether
the broker still had it. On the live PAPER runtime a ``live_llm`` entry order
rested OPEN with 0/3000 filled for 278 minutes and appeared in zero
reconciliation records.

Design boundaries
-----------------
* Bounded: it reads only the durable UNRESOLVED orders, never order history.
* Factual: a missing or ambiguous broker view is ``UNKNOWN``/``MISSING``, never
  silently upgraded to CANCELLED/FAILED. ``UNKNOWN != FAILED`` is the whole
  point of a reconciliation layer.
* Read-only: this module observes. Cancelling is execution policy and lives in
  the liveness layer, which must consult a CONFIRMED state first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.enums import OrderStatus

# ---------------------------------------------------------------- purposes

ORDER_PURPOSE_ENTRY = "ENTRY"
ORDER_PURPOSE_POSITION_REDUCE = "POSITION_REDUCE"
ORDER_PURPOSE_POSITION_EXIT = "POSITION_EXIT"
ORDER_PURPOSE_OTHER = "OTHER"
ORDER_PURPOSES = (
    ORDER_PURPOSE_ENTRY,
    ORDER_PURPOSE_POSITION_REDUCE,
    ORDER_PURPOSE_POSITION_EXIT,
    ORDER_PURPOSE_OTHER,
)

# Position-management strategy ids. Purpose is NOT decided by string equality
# alone - these are only one input to :func:`classify_order_purpose`.
POSITION_STRATEGY_IDS = ("live_llm_position",)

# ------------------------------------------------------------------ states

RECON_CONFIRMED_OPEN = "CONFIRMED_OPEN"
RECON_CONFIRMED_PARTIALLY_FILLED = "CONFIRMED_PARTIALLY_FILLED"
RECON_CONFIRMED_FILLED = "CONFIRMED_FILLED"
RECON_CONFIRMED_CANCELLED = "CONFIRMED_CANCELLED"
RECON_CONFIRMED_REJECTED = "CONFIRMED_REJECTED"
RECON_MISSING = "MISSING"
RECON_UNKNOWN = "UNKNOWN"

#: States that prove the order is still live at the broker.
RECON_LIVE_STATES = (RECON_CONFIRMED_OPEN, RECON_CONFIRMED_PARTIALLY_FILLED)
#: States that prove a factual terminal outcome.
RECON_TERMINAL_STATES = (
    RECON_CONFIRMED_FILLED,
    RECON_CONFIRMED_CANCELLED,
    RECON_CONFIRMED_REJECTED,
)

#: Durable statuses that mean "not settled yet".
UNRESOLVED_ORDER_STATUSES: tuple[str, ...] = (
    OrderStatus.CREATED.value,
    OrderStatus.VALIDATED.value,
    OrderStatus.SUBMITTING.value,
    OrderStatus.SUBMITTED.value,
    OrderStatus.ACKNOWLEDGED.value,
    OrderStatus.OPEN.value,
    OrderStatus.PARTIALLY_FILLED.value,
    OrderStatus.CANCEL_PENDING.value,
    OrderStatus.UNKNOWN.value,
)

_BROKER_STATUS_TO_RECON = {
    OrderStatus.OPEN.value: RECON_CONFIRMED_OPEN,
    OrderStatus.ACKNOWLEDGED.value: RECON_CONFIRMED_OPEN,
    OrderStatus.PARTIALLY_FILLED.value: RECON_CONFIRMED_PARTIALLY_FILLED,
    OrderStatus.FILLED.value: RECON_CONFIRMED_FILLED,
    OrderStatus.CANCELLED.value: RECON_CONFIRMED_CANCELLED,
    OrderStatus.EXPIRED.value: RECON_CONFIRMED_CANCELLED,
    OrderStatus.REJECTED.value: RECON_CONFIRMED_REJECTED,
}


def classify_order_purpose(
    *,
    strategy_id: str | None,
    reduce_only: bool | None = None,
    direction: str | None = None,
    trade_plan_state: str | None = None,
) -> str:
    """Canonical purpose for an order, from intent rather than a string check.

    ``strategy_id`` alone was the previous (and only) discriminator, which is
    exactly why ``live_llm`` ENTRY orders fell outside the liveness pipeline.
    Intent signals are consulted first; the strategy id is the last resort.
    """
    if reduce_only is True:
        # A reduce-only order can only shrink an existing position.
        return (
            ORDER_PURPOSE_POSITION_EXIT
            if (direction or "").upper() == "EXIT"
            else ORDER_PURPOSE_POSITION_REDUCE
        )
    if strategy_id in POSITION_STRATEGY_IDS:
        return (
            ORDER_PURPOSE_POSITION_EXIT
            if (direction or "").upper() == "EXIT"
            else ORDER_PURPOSE_POSITION_REDUCE
        )
    if trade_plan_state in ("PLANNED", "APPROVED", "ACTIVE") and not reduce_only:
        return ORDER_PURPOSE_ENTRY
    if strategy_id:
        return ORDER_PURPOSE_ENTRY if "position" not in strategy_id else ORDER_PURPOSE_OTHER
    return ORDER_PURPOSE_OTHER


@dataclass(frozen=True, slots=True)
class OrderReconciliationFact:
    """One order's reconciled truth. ``state`` is the only verdict."""

    order_id: str
    symbol: str
    client_order_id: str | None
    exchange_order_id: str | None
    purpose: str
    state: str
    durable_status: str
    broker_status: str | None
    identity_confirmed: bool
    filled_quantity: str
    remaining_quantity: str
    last_broker_observation_at: str | None
    reason: str
    observed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def is_live(self) -> bool:
        return self.state in RECON_LIVE_STATES

    @property
    def is_terminal(self) -> bool:
        return self.state in RECON_TERMINAL_STATES

    @property
    def is_unknown(self) -> bool:
        return self.state in (RECON_UNKNOWN, RECON_MISSING)

    def as_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "purpose": self.purpose,
            "state": self.state,
            "durable_status": self.durable_status,
            "broker_status": self.broker_status,
            "identity_confirmed": self.identity_confirmed,
            "filled_quantity": self.filled_quantity,
            "remaining_quantity": self.remaining_quantity,
            "last_broker_observation_at": self.last_broker_observation_at,
            "reason": self.reason,
            "observed_at": self.observed_at,
        }


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except Exception:
        return Decimal("0")


def reconcile_order(
    *,
    order,
    purpose: str,
    broker_order=None,
    broker_error: Exception | None = None,
) -> OrderReconciliationFact:
    """Reconcile ONE durable order against an optional broker observation.

    The broker view is treated as the more authoritative statement about what
    the exchange holds, but only after IDENTITY is confirmed. If identity cannot
    be confirmed the result is UNKNOWN - never a terminal guess.
    """
    durable_status = str(getattr(order, "status", "") or "")
    if hasattr(durable_status, "value"):
        durable_status = order.status.value
    symbol = str(getattr(order, "symbol", "") or "")
    order_id = str(getattr(order, "internal_order_id", "") or "")
    client_id = getattr(order, "client_order_id", None)
    exchange_id = getattr(order, "exchange_order_id", None)
    filled = _decimal(getattr(order, "filled_quantity", 0))
    requested = _decimal(getattr(order, "quantity", 0))

    if broker_error is not None:
        # A provider fault is NOT a terminal outcome.
        return OrderReconciliationFact(
            order_id=order_id,
            symbol=symbol,
            client_order_id=client_id,
            exchange_order_id=exchange_id,
            purpose=purpose,
            state=RECON_UNKNOWN,
            durable_status=durable_status,
            broker_status=None,
            identity_confirmed=False,
            filled_quantity=str(filled),
            remaining_quantity=str(max(Decimal("0"), requested - filled)),
            last_broker_observation_at=None,
            reason=f"BROKER_OBSERVATION_FAILED:{type(broker_error).__name__}",
        )

    if broker_order is None:
        # PAPER keeps part of the open-order state in process memory, so an
        # absent record proves nothing at all.
        return OrderReconciliationFact(
            order_id=order_id,
            symbol=symbol,
            client_order_id=client_id,
            exchange_order_id=exchange_id,
            purpose=purpose,
            state=RECON_MISSING,
            durable_status=durable_status,
            broker_status=None,
            identity_confirmed=False,
            filled_quantity=str(filled),
            remaining_quantity=str(max(Decimal("0"), requested - filled)),
            last_broker_observation_at=None,
            reason="BROKER_RECORD_ABSENT",
        )

    broker_status = str(getattr(getattr(broker_order, "status", None), "value", None) or "")
    broker_exchange_id = getattr(broker_order, "exchange_order_id", None)
    broker_symbol = str(getattr(broker_order, "symbol", "") or "")

    identity_ok = bool(
        broker_exchange_id
        and exchange_id
        and str(broker_exchange_id) == str(exchange_id)
        and broker_symbol == symbol
        and str(getattr(order, "side", "")) == str(getattr(broker_order, "side", ""))
    )
    if not identity_ok:
        return OrderReconciliationFact(
            order_id=order_id,
            symbol=symbol,
            client_order_id=client_id,
            exchange_order_id=exchange_id,
            purpose=purpose,
            state=RECON_UNKNOWN,
            durable_status=durable_status,
            broker_status=broker_status or None,
            identity_confirmed=False,
            filled_quantity=str(filled),
            remaining_quantity=str(max(Decimal("0"), requested - filled)),
            last_broker_observation_at=datetime.now(UTC).isoformat(),
            reason="ORDER_IDENTITY_UNCONFIRMED",
        )

    state = _BROKER_STATUS_TO_RECON.get(
        broker_status, RECON_UNKNOWN if not broker_status else RECON_UNKNOWN
    )
    broker_filled = _decimal(getattr(broker_order, "filled_quantity", 0))
    # Factual fills are never rolled back: take the larger observation.
    effective_filled = max(filled, broker_filled)
    return OrderReconciliationFact(
        order_id=order_id,
        symbol=symbol,
        client_order_id=client_id,
        exchange_order_id=exchange_id,
        purpose=purpose,
        state=state,
        durable_status=durable_status,
        broker_status=broker_status or None,
        identity_confirmed=True,
        filled_quantity=str(effective_filled),
        remaining_quantity=str(max(Decimal("0"), requested - effective_filled)),
        last_broker_observation_at=datetime.now(UTC).isoformat(),
        reason="IDENTITY_CONFIRMED" if state != RECON_UNKNOWN else "BROKER_STATUS_UNMAPPED",
    )
