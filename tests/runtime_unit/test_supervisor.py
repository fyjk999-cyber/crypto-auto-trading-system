import asyncio

import pytest

from crypto_trader.domain.enums import RuntimeState
from crypto_trader.runtime.lease import LeaseManager
from crypto_trader.runtime.supervisor import TradingRuntimeSupervisor


async def test_runtime_without_frontend_continues(database):
    leases = LeaseManager(database.session_factory)
    supervisor = TradingRuntimeSupervisor(lease_manager=leases, interval_seconds=0.01)
    await supervisor.start()
    # no frontend client ever connects
    await asyncio.sleep(0.12)
    assert supervisor.status.runtime_state == RuntimeState.RUNNING
    assert supervisor.status.scanner_heartbeat > 0
    assert supervisor.status.market_heartbeat > 0
    assert supervisor.status.lease_renew_count > 0
    await supervisor.stop()


async def test_ui_disconnect_does_not_stop_runtime(database):
    leases = LeaseManager(database.session_factory)
    supervisor = TradingRuntimeSupervisor(lease_manager=leases, interval_seconds=0.01)
    await supervisor.start()
    await asyncio.sleep(0.1)
    # simulate all UI/WebSocket clients disconnecting
    await asyncio.sleep(0.1)
    assert supervisor.status.runtime_state == RuntimeState.RUNNING
    assert supervisor.status.scanner_heartbeat > 0
    await supervisor.stop()


async def test_lease_renew_during_scan(database):
    leases = LeaseManager(database.session_factory)
    supervisor = TradingRuntimeSupervisor(lease_manager=leases, interval_seconds=0.01)
    await supervisor.start()
    before = supervisor.status.lease_renew_count
    await asyncio.sleep(0.12)
    assert supervisor.status.lease_renew_count > before
    assert await leases.is_held("crypto_engine_execution", supervisor._lease.token)
    await supervisor.stop()


async def test_zombie_writer_block(database):
    leases = LeaseManager(database.session_factory)
    first = await leases.acquire("exec", "writer-a", ttl_seconds=0.001)
    await asyncio.sleep(0.01)
    second = await leases.acquire("exec", "writer-b", ttl_seconds=30)
    assert second is not None
    assert second.fence_generation > first.fence_generation
    # old writer's fence is stale; it cannot execute
    assert await leases.is_current("exec", first.token, first.fence_generation) is False
    # new writer can execute
    assert await leases.is_current("exec", second.token, second.fence_generation) is True


async def test_scanner_can_run_readonly_without_lease(database):
    leases = LeaseManager(database.session_factory)
    # acquire by another writer so this supervisor cannot trade
    await leases.acquire("crypto_engine_execution", "other", ttl_seconds=30)
    supervisor = TradingRuntimeSupervisor(lease_manager=leases, interval_seconds=0.01)
    with pytest.raises(RuntimeError):
        await supervisor.start()
