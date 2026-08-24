import asyncio

import pytest

from crypto_trader.domain.enums import RuntimeState
from crypto_trader.domain.errors import InvalidStateTransition
from crypto_trader.runtime.event_bus import EventBus
from crypto_trader.runtime.state_machine import RuntimeStateMachine


async def test_event_bus_dispatch():
    bus = EventBus()
    received = []
    bus.subscribe("TICK", lambda e: received.append(e) or asyncio.sleep(0))
    await bus.publish("TICK", {"n": 1})
    await bus.publish("TICK", {"n": 2})
    assert received == [{"n": 1}, {"n": 2}]


async def test_event_bus_wildcard():
    bus = EventBus()
    received = []
    bus.subscribe("*", lambda e: received.append(e) or asyncio.sleep(0))
    await bus.publish("X", "hello")
    assert received == ["hello"]


def test_runtime_state_machine():
    sm = RuntimeStateMachine()
    sm.transition(RuntimeState.STARTING)
    sm.transition(RuntimeState.RECOVERING)
    sm.transition(RuntimeState.RUNNING)
    sm.transition(RuntimeState.HALTED)
    sm.transition(RuntimeState.RUNNING)
    sm.transition(RuntimeState.STOPPING)
    sm.transition(RuntimeState.STOPPED)


def test_runtime_state_machine_invalid():
    sm = RuntimeStateMachine()
    with pytest.raises(InvalidStateTransition):
        sm.transition(RuntimeState.RUNNING)
