import pytest

from crypto_trader.domain.enums import OrderEventType, OrderStatus
from crypto_trader.domain.errors import InvalidStateTransition
from crypto_trader.order.state_machine import OrderStateMachine


def test_full_lifecycle_open_partial_fill_filled():
    sm = OrderStateMachine
    assert sm.transition(OrderStatus.CREATED, OrderEventType.ORDER_VALIDATED).new_status == OrderStatus.VALIDATED
    assert sm.transition(OrderStatus.VALIDATED, OrderEventType.ORDER_SUBMITTING).new_status == OrderStatus.SUBMITTING
    assert sm.transition(OrderStatus.SUBMITTING, OrderEventType.ORDER_SUBMITTED).new_status == OrderStatus.SUBMITTED
    assert sm.transition(OrderStatus.SUBMITTED, OrderEventType.ORDER_ACKNOWLEDGED).new_status == OrderStatus.ACKNOWLEDGED
    assert sm.transition(OrderStatus.ACKNOWLEDGED, OrderEventType.ORDER_OPENED).new_status == OrderStatus.OPEN
    assert sm.transition(OrderStatus.OPEN, OrderEventType.ORDER_PARTIALLY_FILLED).new_status == OrderStatus.PARTIALLY_FILLED
    assert sm.transition(OrderStatus.PARTIALLY_FILLED, OrderEventType.ORDER_FILLED).new_status == OrderStatus.FILLED


def test_cancel_path_from_partially_filled():
    sm = OrderStateMachine
    status = OrderStatus.PARTIALLY_FILLED
    status = sm.transition(status, OrderEventType.ORDER_CANCEL_PENDING).new_status
    assert status == OrderStatus.CANCEL_PENDING
    assert sm.transition(status, OrderEventType.ORDER_CANCELLED).new_status == OrderStatus.CANCELLED


def test_fill_before_ack_is_valid_and_late_ack_is_noop():
    sm = OrderStateMachine
    r = sm.transition(OrderStatus.SUBMITTED, OrderEventType.ORDER_PARTIALLY_FILLED)
    assert r.changed and r.new_status == OrderStatus.PARTIALLY_FILLED
    r = sm.transition(OrderStatus.PARTIALLY_FILLED, OrderEventType.ORDER_ACKNOWLEDGED)
    assert r.changed is False and r.noop is True


def test_duplicate_fill_event_stays_filled():
    sm = OrderStateMachine
    r = sm.transition(OrderStatus.FILLED, OrderEventType.ORDER_FILLED)
    assert r.changed is False and r.noop is True


def test_cancel_fill_race_fill_wins():
    sm = OrderStateMachine
    status = OrderStatus.CANCEL_PENDING
    assert sm.transition(status, OrderEventType.ORDER_FILLED).new_status == OrderStatus.FILLED


def test_recovery_from_unknown():
    sm = OrderStateMachine
    assert sm.transition(OrderStatus.UNKNOWN, OrderEventType.ORDER_OPENED).new_status == OrderStatus.OPEN
    assert sm.transition(OrderStatus.UNKNOWN, OrderEventType.ORDER_FILLED).new_status == OrderStatus.FILLED


def test_invalid_transition_rejected():
    sm = OrderStateMachine
    with pytest.raises(InvalidStateTransition):
        sm.transition(OrderStatus.CANCELLED, OrderEventType.ORDER_OPENED)
    with pytest.raises(InvalidStateTransition):
        sm.transition(OrderStatus.FILLED, OrderEventType.ORDER_CANCELLED)
