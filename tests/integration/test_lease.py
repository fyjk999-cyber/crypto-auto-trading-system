import asyncio

import pytest

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


async def test_expired_same_owner_cannot_renew_old_authority(database, monkeypatch):
    """Expiry requires a new fenced acquire, even with matching old identity."""
    now = [1_000.0]
    monkeypatch.setattr("crypto_trader.runtime.lease._epoch", lambda: now[0])
    mgr = LeaseManager(database.session_factory)
    first = await mgr.acquire("exec", "engine_a", ttl_seconds=10)
    now[0] = 1_011.0

    assert await mgr.is_current(
        "exec", first.token, first.fence_generation, owner_id=first.owner_id
    ) is False
    assert await mgr.renew(
        "exec", first.token, 10,
        owner_id=first.owner_id, fence_generation=first.fence_generation,
    ) is False

    successor = await mgr.acquire("exec", "engine_b", ttl_seconds=10)
    assert successor.token != first.token
    assert successor.fence_generation == first.fence_generation + 1
    assert await mgr.renew(
        "exec", first.token, 10,
        owner_id=first.owner_id, fence_generation=first.fence_generation,
    ) is False
    assert await mgr.is_current(
        "exec", successor.token, successor.fence_generation, owner_id=successor.owner_id
    ) is True


async def test_central_safety_rejects_authoritative_expiry_before_heartbeat(database, monkeypatch):
    engine = make_paper_engine(
        database, run_lease_ttl_seconds=10, run_lease_renew_interval_seconds=3,
        engine_tick_seconds=3600,
    )
    await engine.start("central-expiry-default-policy")
    try:
        assert engine.trading_safety_failures() == ()
        status = await engine.lease_manager.status(engine.lease_key)
        monkeypatch.setattr("crypto_trader.runtime.lease._epoch", lambda: status["expires_at"] + 1)
        assert engine.runtime_snapshot()["execution_lease"]["held"] is False
        assert "EXECUTION_LEASE_NOT_HELD" in engine.trading_safety_failures()
    finally:
        await engine.stop()


async def test_exact_default_lease_survives_long_startup_before_workers(database, record_property):
    from crypto_trader.simulator.exchange import SimulatedExchangeAdapter

    samples = []

    class SlowSubscriptionAdapter(SimulatedExchangeAdapter):
        async def subscribe_order_updates(self, callback):
            for _ in range(4):
                await asyncio.sleep(3)
                status = await engine.lease_manager.status(engine.lease_key)
                samples.append({k: status[k] for k in ("expires_at", "version", "expired")})
                assert status["expired"] is False
                assert engine.trading_safety_failures()  # Startup is not trading authority.
            await super().subscribe_order_updates(callback)

    engine = make_paper_engine(
        database, simulator=SlowSubscriptionAdapter(),
        run_lease_ttl_seconds=10, run_lease_renew_interval_seconds=3,
        engine_tick_seconds=3600,
    )
    try:
        await engine.start("long-startup-exact-defaults")
        assert samples[-1]["version"] >= samples[0]["version"] + 2
        assert engine.trading_safety_failures() == ()
        assert await engine.lease_manager.is_current(
            engine.lease_key, engine.lease.token, engine.lease.fence_generation,
            owner_id=engine.lease.owner_id,
        ) is True
    finally:
        record_property("authoritative_startup_lease_samples", str(samples))
        await engine.stop()


async def test_authority_query_outage_is_sticky_not_last_true_fallback(database, monkeypatch):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("authority-query-outage")
    try:
        assert engine.trading_safety_failures() == ()

        def unavailable():
            raise RuntimeError("isolated database unavailable")

        with monkeypatch.context() as outage:
            outage.setattr(engine.lease_manager._authority_reader, "connect", unavailable)
            assert "EXECUTION_LEASE_NOT_HELD" in engine.trading_safety_failures()
        # Current ownership returning is insufficient to revalidate runtime.
        assert engine.lease_manager.is_current_now(engine.lease) is True
        assert "EXECUTION_LEASE_NOT_HELD" in engine.trading_safety_failures()
    finally:
        await engine.stop()


async def test_new_holder_fences_old_engine_central_authority(database, monkeypatch):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("old-holder")
    try:
        assert engine.trading_safety_failures() == ()
        status = await engine.lease_manager.status(engine.lease_key)
        monkeypatch.setattr("crypto_trader.runtime.lease._epoch", lambda: status["expires_at"] + 1)
        successor = await engine.lease_manager.acquire(engine.lease_key, "engine_new", 10)
        assert successor.fence_generation == engine.lease.fence_generation + 1
        assert engine.lease_manager.is_current_now(successor) is True
        assert "EXECUTION_LEASE_NOT_HELD" in engine.trading_safety_failures()
        assert await engine.lease_manager.renew(
            engine.lease_key, engine.lease.token, 10,
            owner_id=engine.lease.owner_id, fence_generation=engine.lease.fence_generation,
        ) is False
    finally:
        await engine.stop()


async def test_failed_startup_releases_lease_and_cancels_heartbeat(database):
    from crypto_trader.simulator.exchange import SimulatedExchangeAdapter

    class ConnectionFailure(SimulatedExchangeAdapter):
        async def connect(self):
            raise RuntimeError("isolated connection unavailable")

    engine = make_paper_engine(database, simulator=ConnectionFailure())
    with pytest.raises(RuntimeError, match="isolated connection unavailable"):
        await engine.start("failed-startup")
    assert engine.runtime_snapshot()["state"] == "STOPPED"
    assert engine.lease is None
    assert not any(t.get_name() == "engine-lease" and not t.done() for t in asyncio.all_tasks())
    assert await engine.order_manager.list_all() == []
    successor = await engine.lease_manager.acquire(engine.lease_key, "after_failed_startup", 10)
    assert successor is not None


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


@pytest.mark.parametrize("failure_mode", ["false", "exception"])
@pytest.mark.parametrize("failure_stage", ["startup", "runtime"])
async def test_engine_lease_renew_failure_modes_fail_closed(
    database, monkeypatch, failure_mode, failure_stage
):
    from crypto_trader.domain.errors import LeaseNotHeld

    engine = make_paper_engine(
        database,
        run_lease_renew_interval_seconds=1,
        run_lease_ttl_seconds=30,
        engine_tick_seconds=3600,
    )
    engine.settings.run_lease_renew_interval_seconds = 0.01

    async def failed_renew(*_args, **_kwargs):
        if failure_mode == "exception":
            raise RuntimeError("simulated storage outage")
        return False

    if failure_stage == "runtime":
        await engine.start(f"lease-renew-{failure_mode}")
    monkeypatch.setattr(engine.lease_manager, "renew", failed_renew)
    if failure_stage == "startup":
        with pytest.raises(LeaseNotHeld):
            await engine.start(f"lease-renew-{failure_mode}")
        assert engine.runtime_snapshot()["state"] == "STOPPED"
        assert await engine.order_manager.list_all() == []
        assert engine.lease is None
    else:
        await asyncio.sleep(0.04)

    snapshot = engine.runtime_snapshot()
    assert snapshot["lease_held"] is False
    assert snapshot["health"]["components"]["execution_lease"]["ok"] is False
    assert snapshot["kill_switch"]["enabled"] is True
    assert snapshot["kill_switch"]["reason"] == "execution lease lost"
    audit = await engine.audit.list_recent(limit=20)
    assert any(row.action == "EXECUTION_LEASE_LOST" for row in audit)
    await engine.stop()
