from decimal import Decimal

import pytest

from crypto_trader.config import Settings
from crypto_trader.execution.authority import ExecutionAuthority
from crypto_trader.ledger.service import LedgerService
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.order.manager import OrderManager
from crypto_trader.persistence.database import Database
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.reconciliation.service import ReconciliationService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.engine import TradingEngine
from crypto_trader.runtime.lease import LeaseManager
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter


@pytest.fixture
async def database(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/crypto_test.db")
    await db.init_schema()
    yield db
    await db.close()


@pytest.fixture
async def session(database):
    async with database.session_factory() as s:
        yield s


def make_paper_engine(database, strategy=None, simulator=None, **settings_kwargs):
    """Shared helper for chaos/e2e tests."""
    default_kwargs = dict(
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        database_url=database.url,
        engine_tick_seconds=0.05,
        run_lease_ttl_seconds=30,
        run_lease_renew_interval_seconds=60,
        reconciliation_interval_seconds=3600,
        market_data_max_age_seconds=60,
        orderbook_max_age_seconds=60,
    )
    default_kwargs.update(settings_kwargs)
    settings = Settings(**default_kwargs)
    simulator = simulator or SimulatedExchangeAdapter(initial_balances={"USDT": Decimal("10000")})
    return TradingEngine(
        settings=settings,
        database=database,
        adapter=simulator,
        order_manager=OrderManager(database.session_factory),
        ledger=LedgerService(database.session_factory),
        portfolio=PortfolioService(database.session_factory),
        risk_engine=RiskEngine(),
        market_data=MarketDataService(),
        lease_manager=LeaseManager(database.session_factory),
        reconciliation=ReconciliationService(database.session_factory),
        strategies=[strategy] if strategy else [],
        authority=ExecutionAuthority(),
    )
