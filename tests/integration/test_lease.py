import asyncio

from crypto_trader.runtime.lease import LeaseManager
from tests.conftest import make_paper_engine


async def test_single_engine_acquires_renews_and_releases(database):
    mgr = LeaseManager(database.session_factory)
    lease = await mgr.acquire("exec", "engine_a", ttl_seconds=10)
    assert lease is not None
    assert await mgr.is_held("exec", lease.token) is True
    assert await mgr.renew("exec", lease.token, ttl_seconds=10) is True
    assert await mgr.release("exec", lease.token) is True
    assert await mgr.is_held("exec", lease.token) is False
    restarted = await mgr.acquire("exec", "engine_b", ttl_seconds=10)
    assert restarted is not None
    assert restarted.token != lease.token
    assert restarted.fence_generation == lease.fence_generation + 1
    assert await mgr.is_current(
        "exec", lease.token, lease.fence_generation, owner_id="engine_a"
    ) is False


async def test_dual_engine_lease_blocks_second_writer(database):
    mgr = LeaseManager(database.session_factory)
    first = await mgr.acquire("exec", "engine_a", ttl_seconds=30)
    assert first is not None
    second = await mgr.acquire("exec", "engine_b", ttl_seconds=30)
    assert second is None
    # first is still live
    assert await mgr.is_held("exec", first.token) is True


async def test_expired_lease_can_be_recovered(database):
    mgr = LeaseManager(database.session_factory)
    first = await mgr.acquire("exec", "engine_a", ttl_seconds=0.001)
    assert first is not None
    import asyncio

    await asyncio.sleep(0.01)
    second = await mgr.acquire("exec", "engine_b", ttl_seconds=30)
    assert second is not None
    assert second.owner_id == "engine_b"
    assert second.token != first.token


async def test_same_owner_extends_active_lease(database):
    mgr = LeaseManager(database.session_factory)
    first = await mgr.acquire("exec", "engine_a", ttl_seconds=30)
    extended = await mgr.acquire("exec", "engine_a", ttl_seconds=60)
    assert extended is not None
    assert extended.token == first.token
    assert extended.expires_at > first.expires_at


async def test_owner_and_fence_are_required_when_caller_supplies_them(database):
    mgr = LeaseManager(database.session_factory)
    lease = await mgr.acquire("exec", "engine_a", ttl_seconds=30)
    assert lease is not None
    assert await mgr.renew(
        "exec", lease.token, 30, owner_id="wrong", fence_generation=lease.fence_generation
    ) is False
    assert await mgr.renew(
        "exec", lease.token, 30, owner_id=lease.owner_id, fence_generation=999
    ) is False
    assert await mgr.is_current(
        "exec", lease.token, lease.fence_generation, owner_id="wrong"
    ) is False
    assert await mgr.release(
        "exec", lease.token, owner_id="wrong", fence_generation=lease.fence_generation
    ) is False
    assert await mgr.release(
        "exec", lease.token, owner_id=lease.owner_id, fence_generation=lease.fence_generation
    ) is True


async def test_engine_lease_loss_is_factual_fail_closed_and_restart_recovers(database):
    first = make_paper_engine(
        database,
        run_lease_renew_interval_seconds=1,
        run_lease_ttl_seconds=1,
        engine_tick_seconds=3600,
    )
    first.settings.run_lease_renew_interval_seconds = 0.01
    await first.start("lease-loss-first")
    lease = first.lease
    assert lease is not None
    assert await first.lease_manager.release(
        first.lease_key,
        lease.token,
        owner_id=lease.owner_id,
        fence_generation=lease.fence_generation,
    ) is True
    await asyncio.sleep(0.04)
    assert first.runtime_snapshot()["lease_held"] is False
    assert first.runtime_snapshot()["health"]["components"]["execution_lease"]["ok"] is False
    assert first.risk_engine.kill_switch.enabled is True
    await first.stop()

    recovered = make_paper_engine(
        database,
        run_lease_renew_interval_seconds=3600,
        engine_tick_seconds=3600,
    )
    await recovered.start("lease-loss-recovered")
    snapshot = recovered.runtime_snapshot()
    assert snapshot["lease_held"] is True
    assert snapshot["execution_lease"] == {
        "required": True,
        "held": True,
        "lease_key": recovered.lease_key,
        "owner_id": "engine_lease-loss-recovered",
        "fence_generation": recovered.lease.fence_generation,
        "single_writer": True,
    }
    assert "token" not in str(snapshot["execution_lease"]).lower()
    assert recovered.lease.token not in str(snapshot)
    assert recovered.risk_engine.kill_switch.enabled is False
    await recovered.stop()
