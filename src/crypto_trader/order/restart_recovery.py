"""F6: reconstruct durable PAPER unresolved-order state after a restart.

The gap
-------
``_restore_paper_adapter_state`` hydrated balances and positions but NOT orders.
The PAPER broker keeps unresolved orders in process memory (``self.orders``), so
after a restart every resting order looked MISSING to F4 reconciliation and a
stale ENTRY could not be expired by the F3 TTL - the order facts existed
durably but were invisible to the thing that had to act on them.

Restore, never resubmit
-----------------------
This module COPYIES durable facts into the broker's in-memory representation.
It never calls submit/create/place, never invents a fill, never mutates the
durable ledger, and never generates a new identity. If a durable fact is
insufficient to prove what the broker held, the order is reported as
NOT_RECOVERABLE rather than guessed at - ``UNKNOWN != OPEN`` and
``MISSING != CANCELLED`` apply to recovery just as they do to reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce

# ---------------------------------------------------------------- verdicts

RECOVERED_CONFIRMED = "RECOVERABLE_CONFIRMED"
RECOVERED_PARTIAL = "RECOVERABLE_PARTIAL"
NOT_RECOVERABLE_INSUFFICIENT_FACTS = "NOT_RECOVERABLE_INSUFFICIENT_FACTS"
IDENTITY_CONTRADICTION = "IDENTITY_CONTRADICTION"
TERMINAL_NO_RECOVERY = "TERMINAL_NO_RECOVERY"

#: Durable states that may be rebuilt as a live broker order.
RESTORABLE_STATUSES = (
    OrderStatus.OPEN.value,
    OrderStatus.ACKNOWLEDGED.value,
    OrderStatus.PARTIALLY_FILLED.value,
    OrderStatus.CANCEL_PENDING.value,
)

#: Durable states that must NEVER become an open broker order.
TERMINAL_STATUSES = (
    OrderStatus.FILLED.value,
    OrderStatus.CANCELLED.value,
    OrderStatus.REJECTED.value,
    OrderStatus.EXPIRED.value,
)

#: States we deliberately do not resurrect: they are ambiguous by definition.
UNRESOLVED_AMBIGUOUS_STATUSES = (OrderStatus.UNKNOWN.value,)


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    order_id: str
    verdict: str
    reason: str
    restored: bool
    exchange_order_id: str | None = None
    filled_quantity: str = "0"
    remaining_quantity: str = "0"

    def as_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "verdict": self.verdict,
            "reason": self.reason,
            "restored": self.restored,
            "exchange_order_id": self.exchange_order_id,
            "filled_quantity": self.filled_quantity,
            "remaining_quantity": self.remaining_quantity,
        }


@dataclass
class RecoveryReport:
    outcomes: list[RecoveryOutcome] = field(default_factory=list)
    fatal: bool = False

    @property
    def restored(self) -> list[RecoveryOutcome]:
        return [o for o in self.outcomes if o.restored]

    @property
    def contradictions(self) -> list[RecoveryOutcome]:
        return [o for o in self.outcomes if o.verdict == IDENTITY_CONTRADICTION]

    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for outcome in self.outcomes:
            tally[outcome.verdict] = tally.get(outcome.verdict, 0) + 1
        return tally


def _decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _as_aware(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return None


def classify_recoverability(*, order, broker_hint=None) -> RecoveryOutcome:
    """Decide whether ONE durable order can be safely rebuilt in the broker.

    ``broker_hint`` is any surviving record of what the broker held (for PAPER,
    the same process normally has none after a restart). It is used ONLY to
    detect contradictions; its absence is not evidence of anything.
    """
    order_id = str(getattr(order, "internal_order_id", "") or "")
    raw_status = getattr(order, "status", "")
    status = str(getattr(raw_status, "value", raw_status) or "")

    if status in TERMINAL_STATUSES:
        return RecoveryOutcome(
            order_id=order_id,
            verdict=TERMINAL_NO_RECOVERY,
            reason=f"TERMINAL_{status}",
            restored=False,
        )

    if status in UNRESOLVED_AMBIGUOUS_STATUSES:
        # UNKNOWN must not be upgraded to OPEN by a restart.
        return RecoveryOutcome(
            order_id=order_id,
            verdict=NOT_RECOVERABLE_INSUFFICIENT_FACTS,
            reason="AMBIGUOUS_STATUS_UNKNOWN",
            restored=False,
        )

    if status not in RESTORABLE_STATUSES:
        return RecoveryOutcome(
            order_id=order_id,
            verdict=NOT_RECOVERABLE_INSUFFICIENT_FACTS,
            reason=f"UNSUPPORTED_STATUS_{status}",
            restored=False,
        )

    # Identity: without a broker id there is nothing to restore the order AS.
    exchange_id = getattr(order, "exchange_order_id", None)
    client_id = getattr(order, "client_order_id", None)
    symbol = getattr(order, "symbol", None)
    side = getattr(order, "side", None)
    if not exchange_id or not client_id or not symbol or side is None:
        return RecoveryOutcome(
            order_id=order_id,
            verdict=NOT_RECOVERABLE_INSUFFICIENT_FACTS,
            reason="MISSING_BROKER_IDENTITY",
            restored=False,
        )

    requested = _decimal(getattr(order, "quantity", None))
    filled = _decimal(getattr(order, "filled_quantity", 0)) or Decimal("0")
    if requested is None or requested <= 0:
        return RecoveryOutcome(
            order_id=order_id,
            verdict=NOT_RECOVERABLE_INSUFFICIENT_FACTS,
            reason="MALFORMED_REQUESTED_QUANTITY",
            restored=False,
        )
    if filled < 0 or filled > requested:
        # A quantity contradiction is never silently clamped.
        return RecoveryOutcome(
            order_id=order_id,
            verdict=IDENTITY_CONTRADICTION,
            reason="QUANTITY_CONTRADICTION",
            restored=False,
        )

    # Contradiction checks against any surviving broker record.
    if broker_hint is not None:
        hint_symbol = getattr(broker_hint, "symbol", None)
        hint_side = getattr(broker_hint, "side", None)
        hint_exchange = getattr(broker_hint, "exchange_order_id", None)
        hint_filled = _decimal(getattr(broker_hint, "filled_quantity", 0)) or Decimal("0")
        if hint_symbol and hint_symbol != symbol:
            return RecoveryOutcome(
                order_id=order_id,
                verdict=IDENTITY_CONTRADICTION,
                reason="SYMBOL_MISMATCH",
                restored=False,
            )
        if hint_side is not None and str(getattr(hint_side, "value", hint_side)) != str(
            getattr(side, "value", side)
        ):
            return RecoveryOutcome(
                order_id=order_id,
                verdict=IDENTITY_CONTRADICTION,
                reason="SIDE_MISMATCH",
                restored=False,
            )
        if hint_exchange and str(hint_exchange) != str(exchange_id):
            return RecoveryOutcome(
                order_id=order_id,
                verdict=IDENTITY_CONTRADICTION,
                reason="EXCHANGE_ID_MISMATCH",
                restored=False,
            )
        if hint_filled > filled:
            # The broker knows about a fill the durable row does not.
            return RecoveryOutcome(
                order_id=order_id,
                verdict=IDENTITY_CONTRADICTION,
                reason="FILLED_QUANTITY_CONTRADICTION",
                restored=False,
            )

    remaining = requested - filled
    verdict = (
        RECOVERED_PARTIAL if filled > 0 else RECOVERED_CONFIRMED
    )
    return RecoveryOutcome(
        order_id=order_id,
        verdict=verdict,
        reason="FACTS_SUFFICIENT",
        restored=True,
        exchange_order_id=str(exchange_id),
        filled_quantity=str(filled),
        remaining_quantity=str(remaining),
    )


def rebuild_broker_order(order):
    """Build the broker-side representation from durable facts, or return None.

    The returned object keeps the ORIGINAL identities and timestamps. In
    particular ``created_at`` is preserved so a restart cannot reset the resting
    clock - which would otherwise let an already-stale order live another full
    TTL window.
    """
    exchange_id = getattr(order, "exchange_order_id", None)
    if not exchange_id:
        return None
    status = getattr(order, "status", OrderStatus.OPEN)
    status_value = getattr(status, "value", status)
    side = getattr(order, "side", OrderSide.BUY)
    if not isinstance(side, OrderSide):
        side = OrderSide(str(getattr(side, "value", side)))
    order_type = getattr(order, "order_type", OrderType.LIMIT)
    if not isinstance(order_type, OrderType):
        order_type = OrderType(str(getattr(order_type, "value", order_type)))
    tif = getattr(order, "time_in_force", TimeInForce.GTC)
    if not isinstance(tif, TimeInForce):
        tif = TimeInForce(str(getattr(tif, "value", tif)))

    from crypto_trader.domain.models import Order

    requested = _decimal(getattr(order, "quantity", None)) or Decimal("0")
    filled = _decimal(getattr(order, "filled_quantity", 0)) or Decimal("0")
    return Order(
        internal_order_id=str(order.internal_order_id),
        client_order_id=str(getattr(order, "client_order_id", "") or ""),
        exchange_order_id=str(exchange_id),
        symbol=str(order.symbol),
        side=side,
        order_type=order_type,
        time_in_force=tif,
        price=getattr(order, "price", None),
        quantity=requested,
        filled_quantity=filled,
        avg_fill_price=getattr(order, "avg_fill_price", None),
        # CANCEL_PENDING is preserved verbatim so a restart cannot make a second
        # cancel possible for an order whose cancellation is already in flight.
        status=(
            OrderStatus(status_value)
            if status_value in OrderStatus._value2member_map_
            else OrderStatus.OPEN
        ),
        trading_mode=getattr(order, "trading_mode", None),
        strategy_id=getattr(order, "strategy_id", None),
        run_id=getattr(order, "run_id", None),
        created_at=_as_aware(getattr(order, "created_at", None)) or datetime.now(UTC),
        updated_at=_as_aware(getattr(order, "updated_at", None)) or datetime.now(UTC),
        expires_at=getattr(order, "expires_at", None),
        rejection_reason=getattr(order, "rejection_reason", None),
        last_event_id=getattr(order, "last_event_id", None),
        metadata=dict(getattr(order, "metadata", None) or {}),
    )


def recover_unresolved_orders(*, durable_orders, broker_orders, apply_restore) -> RecoveryReport:
    """Classify and (optionally) restore every durable unresolved order.

    ``apply_restore`` is injected so the caller owns the actual mutation; this
    function never touches the broker directly. It is idempotent: writing the
    same order twice cannot duplicate a fill, because only the order RECORD is
    restored - fills are never replayed.
    """
    report = RecoveryReport()
    for durable in durable_orders:
        hint = (broker_orders or {}).get(getattr(durable, "exchange_order_id", ""))
        outcome = classify_recoverability(order=durable, broker_hint=hint)
        report.outcomes.append(outcome)
        if outcome.verdict == IDENTITY_CONTRADICTION:
            report.fatal = True
        if not outcome.restored:
            continue
        rebuilt = rebuild_broker_order(durable)
        if rebuilt is None:
            continue
        apply_restore(rebuilt)
    return report
