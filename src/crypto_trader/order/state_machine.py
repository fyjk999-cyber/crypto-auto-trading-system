"""Async crypto order state machine.

Supports out-of-order ACK/fill delivery, cancel/fill races, duplicate events,
and recovery transitions. Pure function of (current_status, event_type).
"""
from __future__ import annotations

from dataclasses import dataclass

from crypto_trader.domain.enums import OrderEventType, OrderStatus
from crypto_trader.domain.errors import InvalidStateTransition


# canonical transitions. A late event that should not move the state maps to
# the same status with changed=False; an invalid event raises.
_TRANSITIONS: dict[tuple[OrderStatus, OrderEventType], OrderStatus] = {
    (OrderStatus.CREATED, OrderEventType.ORDER_VALIDATED): OrderStatus.VALIDATED,
    (OrderStatus.CREATED, OrderEventType.ORDER_REJECTED): OrderStatus.REJECTED,
    (OrderStatus.VALIDATED, OrderEventType.ORDER_SUBMITTING): OrderStatus.SUBMITTING,
    (OrderStatus.VALIDATED, OrderEventType.ORDER_REJECTED): OrderStatus.REJECTED,
    (OrderStatus.SUBMITTING, OrderEventType.ORDER_SUBMITTED): OrderStatus.SUBMITTED,
    (OrderStatus.SUBMITTING, OrderEventType.ORDER_ACKNOWLEDGED): OrderStatus.ACKNOWLEDGED,
    (OrderStatus.SUBMITTING, OrderEventType.ORDER_OPENED): OrderStatus.OPEN,
    (OrderStatus.SUBMITTING, OrderEventType.ORDER_PARTIALLY_FILLED): OrderStatus.PARTIALLY_FILLED,
    (OrderStatus.SUBMITTING, OrderEventType.ORDER_FILLED): OrderStatus.FILLED,
    (OrderStatus.SUBMITTING, OrderEventType.ORDER_REJECTED): OrderStatus.REJECTED,
    (OrderStatus.SUBMITTING, OrderEventType.ORDER_UNKNOWN): OrderStatus.UNKNOWN,
    (OrderStatus.SUBMITTED, OrderEventType.ORDER_ACKNOWLEDGED): OrderStatus.ACKNOWLEDGED,
    (OrderStatus.SUBMITTED, OrderEventType.ORDER_OPENED): OrderStatus.OPEN,
    (OrderStatus.SUBMITTED, OrderEventType.ORDER_PARTIALLY_FILLED): OrderStatus.PARTIALLY_FILLED,
    (OrderStatus.SUBMITTED, OrderEventType.ORDER_FILLED): OrderStatus.FILLED,
    (OrderStatus.SUBMITTED, OrderEventType.ORDER_REJECTED): OrderStatus.REJECTED,
    (OrderStatus.SUBMITTED, OrderEventType.ORDER_UNKNOWN): OrderStatus.UNKNOWN,
    (OrderStatus.ACKNOWLEDGED, OrderEventType.ORDER_OPENED): OrderStatus.OPEN,
    (OrderStatus.ACKNOWLEDGED, OrderEventType.ORDER_PARTIALLY_FILLED): OrderStatus.PARTIALLY_FILLED,
    (OrderStatus.ACKNOWLEDGED, OrderEventType.ORDER_FILLED): OrderStatus.FILLED,
    (OrderStatus.ACKNOWLEDGED, OrderEventType.ORDER_CANCEL_PENDING): OrderStatus.CANCEL_PENDING,
    (OrderStatus.ACKNOWLEDGED, OrderEventType.ORDER_REJECTED): OrderStatus.REJECTED,
    (OrderStatus.ACKNOWLEDGED, OrderEventType.ORDER_UNKNOWN): OrderStatus.UNKNOWN,
    (OrderStatus.OPEN, OrderEventType.ORDER_PARTIALLY_FILLED): OrderStatus.PARTIALLY_FILLED,
    (OrderStatus.OPEN, OrderEventType.ORDER_FILLED): OrderStatus.FILLED,
    (OrderStatus.OPEN, OrderEventType.ORDER_CANCEL_PENDING): OrderStatus.CANCEL_PENDING,
    (OrderStatus.OPEN, OrderEventType.ORDER_REJECTED): OrderStatus.REJECTED,
    (OrderStatus.OPEN, OrderEventType.ORDER_EXPIRED): OrderStatus.EXPIRED,
    (OrderStatus.OPEN, OrderEventType.ORDER_UNKNOWN): OrderStatus.UNKNOWN,
    (OrderStatus.PARTIALLY_FILLED, OrderEventType.ORDER_PARTIALLY_FILLED): OrderStatus.PARTIALLY_FILLED,
    (OrderStatus.PARTIALLY_FILLED, OrderEventType.ORDER_FILLED): OrderStatus.FILLED,
    (OrderStatus.PARTIALLY_FILLED, OrderEventType.ORDER_CANCEL_PENDING): OrderStatus.CANCEL_PENDING,
    (OrderStatus.PARTIALLY_FILLED, OrderEventType.ORDER_REJECTED): OrderStatus.REJECTED,
    (OrderStatus.PARTIALLY_FILLED, OrderEventType.ORDER_EXPIRED): OrderStatus.EXPIRED,
    (OrderStatus.PARTIALLY_FILLED, OrderEventType.ORDER_UNKNOWN): OrderStatus.UNKNOWN,
    (OrderStatus.CANCEL_PENDING, OrderEventType.ORDER_CANCELLED): OrderStatus.CANCELLED,
    # cancel/fill race: exchange truth wins
    (OrderStatus.CANCEL_PENDING, OrderEventType.ORDER_PARTIALLY_FILLED): OrderStatus.PARTIALLY_FILLED,
    (OrderStatus.CANCEL_PENDING, OrderEventType.ORDER_FILLED): OrderStatus.FILLED,
    (OrderStatus.CANCELLED, OrderEventType.ORDER_PARTIALLY_FILLED): OrderStatus.PARTIALLY_FILLED,
    (OrderStatus.CANCELLED, OrderEventType.ORDER_FILLED): OrderStatus.FILLED,
    (OrderStatus.UNKNOWN, OrderEventType.ORDER_OPENED): OrderStatus.OPEN,
    (OrderStatus.UNKNOWN, OrderEventType.ORDER_PARTIALLY_FILLED): OrderStatus.PARTIALLY_FILLED,
    (OrderStatus.UNKNOWN, OrderEventType.ORDER_FILLED): OrderStatus.FILLED,
    (OrderStatus.UNKNOWN, OrderEventType.ORDER_CANCELLED): OrderStatus.CANCELLED,
    (OrderStatus.UNKNOWN, OrderEventType.ORDER_REJECTED): OrderStatus.REJECTED,
    (OrderStatus.UNKNOWN, OrderEventType.ORDER_EXPIRED): OrderStatus.EXPIRED,
}

# Events that are valid but do not move state (recorded for audit).
_NOOP_EVENTS = {
    (OrderStatus.ACKNOWLEDGED, OrderEventType.ORDER_ACKNOWLEDGED),
    (OrderStatus.OPEN, OrderEventType.ORDER_ACKNOWLEDGED),
    (OrderStatus.OPEN, OrderEventType.ORDER_OPENED),
    (OrderStatus.PARTIALLY_FILLED, OrderEventType.ORDER_ACKNOWLEDGED),
    (OrderStatus.PARTIALLY_FILLED, OrderEventType.ORDER_OPENED),
    (OrderStatus.FILLED, OrderEventType.ORDER_ACKNOWLEDGED),
    (OrderStatus.FILLED, OrderEventType.ORDER_OPENED),
    (OrderStatus.CANCELLED, OrderEventType.ORDER_CANCELLED),
    (OrderStatus.FILLED, OrderEventType.ORDER_FILLED),
    (OrderStatus.REJECTED, OrderEventType.ORDER_REJECTED),
    (OrderStatus.EXPIRED, OrderEventType.ORDER_EXPIRED),
}


@dataclass(frozen=True)
class TransitionResult:
    new_status: OrderStatus
    changed: bool
    noop: bool = False


class OrderStateMachine:
    @staticmethod
    def transition(current: OrderStatus, event_type: OrderEventType) -> TransitionResult:
        key = (current, event_type)
        if key in _TRANSITIONS:
            return TransitionResult(_TRANSITIONS[key], _TRANSITIONS[key] != current)
        if key in _NOOP_EVENTS:
            return TransitionResult(current, changed=False, noop=True)
        raise InvalidStateTransition(f"invalid order transition {current.value} -> {event_type.value}")
