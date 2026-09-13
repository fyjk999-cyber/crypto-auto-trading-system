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
async def test_engine_lease_renew_failure_modes_fail_closed(
    database, monkeypatch, failure_mode
):
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

    monkeypatch.setattr(engine.lease_manager, "renew", failed_renew)
    await engine.start(f"lease-renew-{failure_mode}")
    await asyncio.sleep(0.04)

    snapshot = engine.runtime_snapshot()
    assert snapshot["lease_held"] is False
    assert snapshot["health"]["components"]["execution_lease"]["ok"] is False
    assert snapshot["kill_switch"]["enabled"] is True
    assert snapshot["kill_switch"]["reason"] == "execution lease lost"
    audit = await engine.audit.list_recent(limit=20)
    assert any(row.action == "EXECUTION_LEASE_LOST" for row in audit)
    await engine.stop()


async def test_runtime_source_sha_identity_and_run_metadata(database, monkeypatch):

    from crypto_trader.persistence.models import EngineRunORM
    from crypto_trader.runtime.source_identity import resolve_source_sha

    monkeypatch.setenv("RUNNING_SHA", "c1-exact-checkout-sha")
    assert resolve_source_sha() == "c1-exact-checkout-sha"

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    run_id = await engine.start("source-sha-run")
    snapshot = engine.runtime_snapshot()
    assert snapshot["source_sha"] == "c1-exact-checkout-sha"
    assert snapshot["started_at"]
    assert snapshot["single_writer"] is True
    assert snapshot["llm_provider"] == {
        "name": "none", "model": "none", "healthy": False,
    }
    assert "market_data" in snapshot
    assert snapshot["adapter"] == "SimulatedExchangeAdapter"

    async with database.session_factory() as session:
        row = await session.get(EngineRunORM, run_id)
    assert row is not None
    assert row.metadata_json["source_sha"] == "c1-exact-checkout-sha"
    await engine.stop()


async def test_clean_restart_single_writer_and_no_duplicate_tasks(database):
    from sqlalchemy import select

    from crypto_trader.persistence.models import EngineRunORM

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("restart-one")
    first_lease = engine.lease
    first_names = sorted(task.get_name() for task in engine._tasks)
    assert len(first_names) == len(set(first_names))

    await engine.stop()
    assert engine._tasks == []

    await engine.start("restart-two")
    second_lease = engine.lease
    second_names = sorted(task.get_name() for task in engine._tasks)
    assert second_names == first_names
    assert second_lease is not None and first_lease is not None
    assert second_lease.owner_id == "engine_restart-two"
    assert second_lease.fence_generation > first_lease.fence_generation
    assert engine.runtime_snapshot()["single_writer"] is True

    async with database.session_factory() as session:
        rows = (
            await session.execute(select(EngineRunORM).order_by(EngineRunORM.run_id))
        ).scalars().all()
    active = [row for row in rows if row.ended_at is None]
    assert [row.run_id for row in active] == ["restart-two"]
    await engine.stop()


async def test_second_engine_instance_is_rejected_without_duplicate_writer(database):
    from sqlalchemy import select

    from crypto_trader.domain.errors import LeaseNotHeld
    from crypto_trader.persistence.models import EngineRunORM

    first = make_paper_engine(database, engine_tick_seconds=3600)
    second = make_paper_engine(database, engine_tick_seconds=3600)
    await first.start("first-writer")
    with pytest.raises(LeaseNotHeld):
        await second.start("second-writer")
    assert second.lease is None
    assert second.runtime_snapshot()["single_writer"] is False

    async with database.session_factory() as session:
        rows = (
            await session.execute(select(EngineRunORM).order_by(EngineRunORM.run_id))
        ).scalars().all()
    active = [row.run_id for row in rows if row.ended_at is None]
    denied = next(row for row in rows if row.run_id == "second-writer")
    assert active == ["first-writer"]
    assert denied.state == "STOPPED"
    await first.stop()


async def test_engine_prefers_refresh_market_state_for_paper_execution(database):
    from decimal import Decimal

    from crypto_trader.market_data.state import DataHealth, MarketState

    engine = make_paper_engine(database)

    class FakeAdapter:
        def __init__(self):
            self.calls: list[str] = []

        async def refresh_market_state(self, symbol):
            self.calls.append("refresh")
            return MarketState(
                symbol=symbol,
                health=DataHealth.HEALTHY,
                best_bid=Decimal("100"),
                best_ask=Decimal("101"),
                best_bid_size=Decimal("2"),
                best_ask_size=Decimal("2"),
            )

        async def get_market_state(self, symbol):
            self.calls.append("get")
            return MarketState(symbol=symbol)

    fake = FakeAdapter()
    engine.adapter = fake
    state = await engine._adapter_market_state("BTCUSDT")
    assert fake.calls == ["refresh"]
    assert state is not None and state.best_bid == Decimal("100")


async def test_paper_real_market_refresh_populates_execution_book():
    from decimal import Decimal

    from crypto_trader.market_data.state import DataHealth, MarketState
    from crypto_trader.simulator.real_market_paper import PaperRealMarketAdapter

    class FakeFeed:
        async def refresh(self, symbol):
            return MarketState(
                symbol=symbol,
                provider="OKX_PUBLIC",
                data_source="REAL",
                health=DataHealth.HEALTHY,
                best_bid=Decimal("100"),
                best_ask=Decimal("101"),
                best_bid_size=Decimal("2"),
                best_ask_size=Decimal("3"),
            )

    adapter = PaperRealMarketAdapter(
        initial_balances={"USDT": Decimal("10000")},
        feed=FakeFeed(),
    )
    state = await adapter.refresh_market_state("BTCUSDT")
    assert state.health.value == "HEALTHY"
    book = adapter.books["BTCUSDT"]
    assert book.best_bid().price == Decimal("100")
    assert book.best_ask().price == Decimal("101")
