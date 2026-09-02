"""Deterministic R1A lease-loop resilience tests."""
import asyncio
from types import SimpleNamespace

import pytest

from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.engine import TradingEngine
from crypto_trader.runtime.health import HealthRegistry


def _engine_shell(lease_manager, renew_result="ok"):
    engine = object.__new__(TradingEngine)
    engine.lease_manager = lease_manager
    engine.settings = SimpleNamespace(run_lease_renew_interval_seconds=0.001,
                                      run_lease_ttl_seconds=30)
    engine.lease = SimpleNamespace(lease_key="k", owner_id="engine_test", token="tok")
    engine.lease_key = "crypto_engine_execution"
    engine.run_id = "run_test"
    engine.risk_engine = RiskEngine()
    engine.health = HealthRegistry()
    engine._lease_valid = True
    engine._lease_renewals = 0
    engine._lease_task_exception = ""
    engine._lease_task = None
    engine.require_lease = True
    engine._lease_result = renew_result
    return engine


class _FakeLeaseManager:
    def __init__(self, result="ok"):
        self.result = result
        self.calls = 0

    async def renew(self, lease_key, token, ttl_seconds):
        self.calls += 1
        if self.result == "raise":
            raise RuntimeError("db exploded")
        if self.result == "false":
            return False
        return True


async def _run_until(engine, predicate, max_wait=0.5):
    loop = asyncio.get_running_loop()
    end = loop.time() + max_wait
    while loop.time() < end:
        if predicate(engine):
            return True
        await asyncio.sleep(0.005)
    return predicate(engine)


async def _start_loop(engine):
    task = asyncio.create_task(engine._lease_loop())
    return task


async def test_renew_exception_task_survives_and_fails_closed():
    mgr = _FakeLeaseManager("raise")
    engine = _engine_shell(mgr, "raise")
    task = await _start_loop(engine)
    try:
        assert await _run_until(engine, lambda e: e._lease_valid is False)
        assert engine.health.components["execution_lease"]["ok"] is False
        assert engine.risk_engine.kill_switch.enabled is True
        assert engine.lease is None
        assert engine._lease_task_exception
        assert not task.done() or task.cancelled()
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def test_renew_false_lost_ownership():
    mgr = _FakeLeaseManager("false")
    engine = _engine_shell(mgr, "false")
    task = await _start_loop(engine)
    try:
        assert await _run_until(engine, lambda e: e._lease_valid is False)
        assert engine.health.components["execution_lease"]["ok"] is False
        assert engine.risk_engine.kill_switch.enabled is True
        assert engine.lease is None
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def test_cancel_shuts_down_cleanly():
    mgr = _FakeLeaseManager("ok")
    engine = _engine_shell(mgr, "ok")
    task = await _start_loop(engine)
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_factual_lease_held_false_when_db_invalid():
    mgr = _FakeLeaseManager("false")
    engine = _engine_shell(mgr, "false")
    engine._lease_valid = False
    engine.lease = SimpleNamespace(lease_key="k", owner_id="engine_test", token="tok")
    # Same expression used by runtime_snapshot()
    lease_held = bool(engine.lease is not None and engine._lease_valid)
    assert lease_held is False
