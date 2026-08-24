import asyncio
from decimal import Decimal

from crypto_trader.config import Settings
from crypto_trader.domain.enums import OrderStatus
from crypto_trader.execution.authority import ExecutionAuthority
from crypto_trader.ledger.service import LedgerService
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.order.manager import OrderManager
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.reconciliation.service import ReconciliationService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.engine import TradingEngine
from crypto_trader.runtime.lease import LeaseManager
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter
from crypto_trader.strategy.dummy import DummyStrategy
from crypto_trader.strategy.test_strategy import TestStrategy


def make_settings(db_url):
    return Settings(
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        database_url=db_url,
        engine_tick_seconds=0.05,
        run_lease_ttl_seconds=30,
        run_lease_renew_interval_seconds=60,
        reconciliation_interval_seconds=3600,
        market_data_max_age_seconds=60,
        orderbook_max_age_seconds=60,
    )


def build_engine(db, simulator, strategy):
    settings = make_settings(db.url)
    order_manager = OrderManager(db.session_factory)
    ledger = LedgerService(db.session_factory)
    portfolio = PortfolioService(db.session_factory)
    risk = RiskEngine()
    market_data = MarketDataService()
    leases = LeaseManager(db.session_factory)
    recon = ReconciliationService(db.session_factory)
    engine = TradingEngine(
        settings=settings,
        database=db,
        adapter=simulator,
        order_manager=order_manager,
        ledger=ledger,
        portfolio=portfolio,
        risk_engine=risk,
        market_data=market_data,
        lease_manager=leases,
        reconciliation=recon,
        strategies=[strategy],
        authority=ExecutionAuthority(),
    )
    return engine


async def test_dummy_strategy_never_trades(database):
    sim = SimulatedExchangeAdapter()
    await sim.connect()
    engine = build_engine(database, sim, DummyStrategy())
    await engine.start()
    decisions = await engine.tick()
    assert decisions == []
    open_orders = await engine.order_manager.list_open()
    assert open_orders == []
    await engine.stop()


async def test_full_paper_automated_chain(database):
    sim = SimulatedExchangeAdapter(initial_balances={"USDT": Decimal("10000")})
    await sim.connect()
    engine = build_engine(database, sim, TestStrategy(quantity="0.1", limit_price="101"))

    run_id = await engine.start()
    assert run_id.startswith("run_")

    # drive one strategy tick and wait for the async exchange events + settlement
    await engine.tick()
    for _ in range(100):
        orders = await engine.order_manager.list_open()
        if not orders:
            break
        await asyncio.sleep(0.01)
    await engine.wait_for_event_queue()

    # list_open excludes FILLED, so find by client order id
    client_id = f"test_{engine.strategies[0].signal_id}"[:60]
    order = await engine.order_manager.get_by_client(client_id)
    assert order is not None
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == Decimal("0.1")

    account = await engine.portfolio.get_account()
    # ask 100.05 * 0.1 = 10.005; fee 0.010005 -> cash = 10000 - 10.015005
    assert account.balances["USDT"].total == Decimal("9989.984995")
    positions = await engine.portfolio.get_positions()
    assert positions["BTCUSDT"].quantity == Decimal("0.1")
    assert positions["BTCUSDT"].avg_entry_price == Decimal("100.05")

    # audit and risk decisions persisted
    audit_rows = await engine.audit.list_recent(limit=50)
    assert any(r.action == "FILL_SETTLED" for r in audit_rows)
    assert any(r.action == "ENGINE_STARTED" for r in audit_rows)

    # second tick: same signal id is an idempotent retry and produces no new order
    before_count = len(await _all_orders(engine))
    await engine.tick()
    after_count = len(await _all_orders(engine))
    assert before_count == after_count

    await engine.stop()
    assert engine.state_machine.state.value == "STOPPED"


async def _all_orders(engine):
    from sqlalchemy import select

    from crypto_trader.persistence.models import OrderORM

    async with engine.database.session_factory() as session:
        rows = (await session.execute(select(OrderORM))).scalars().all()
        return rows
