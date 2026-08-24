"""The single official runtime bootstrap path.

Test/API/CLI must not each assemble a different core. They should call
`build_system(settings)` and receive a fully initialized `RuntimeBundle`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text

from crypto_trader.alpha.ensemble import MultiStrategyAlpha
from crypto_trader.api.deps import AppState
from crypto_trader.config import Settings
from crypto_trader.execution.authority import ExecutionAuthority
from crypto_trader.ledger.service import LedgerService
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.observability.audit import AuditService
from crypto_trader.order.manager import OrderManager
from crypto_trader.persistence.database import Database
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.reconciliation.service import ReconciliationService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.engine import TradingEngine
from crypto_trader.runtime.lease import LeaseManager
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter
from crypto_trader.simulator.real_market_paper import PaperRealMarketAdapter
from crypto_trader.strategy.dummy import DummyStrategy


@dataclass
class RuntimeBundle:
    settings: Settings
    database: Database
    ledger: LedgerService
    portfolio: PortfolioService
    order_manager: OrderManager
    market_data: MarketDataService
    risk: RiskEngine
    leases: LeaseManager
    reconciliation: ReconciliationService
    audit: AuditService
    adapter: SimulatedExchangeAdapter
    alpha: MultiStrategyAlpha
    engine: TradingEngine
    app_state: AppState


async def build_system(settings: Settings) -> RuntimeBundle:
    database = Database(settings.database_url)
    await database.init_schema()
    await _verify_migrations(database)

    ledger = LedgerService(database.session_factory)
    portfolio = PortfolioService(database.session_factory)
    order_manager = OrderManager(database.session_factory)
    market_data = MarketDataService()
    risk = RiskEngine()
    leases = LeaseManager(database.session_factory)
    reconciliation = ReconciliationService(database.session_factory)
    audit = AuditService(database.session_factory)

    # Paper is default. SimulatedExchangeAdapter implements the same contract
    # as a live adapter, so LIVE/PAPER/SHADOW share one core.
    if settings.paper_mode == "PAPER_REAL_MARKET":
        adapter = PaperRealMarketAdapter(
            initial_balances={
                settings.paper_settlement_asset: Decimal(settings.paper_initial_equity)
            }
        )
    else:
        adapter = SimulatedExchangeAdapter(
            initial_balances={
                settings.paper_settlement_asset: Decimal(settings.paper_initial_equity)
            }
        )

    alpha = MultiStrategyAlpha(
        symbol="BTCUSDT",
        risk_per_trade="0.0005",
        max_position_notional="5000",
        max_leverage="3",
    )
    strategies = [alpha] if settings.auto_start_runtime else [DummyStrategy()]

    engine = TradingEngine(
        settings=settings,
        database=database,
        adapter=adapter,
        order_manager=order_manager,
        ledger=ledger,
        portfolio=portfolio,
        risk_engine=risk,
        market_data=market_data,
        lease_manager=leases,
        reconciliation=reconciliation,
        audit=audit,
        strategies=strategies,
        authority=ExecutionAuthority(),
        require_lease=True,
    )

    app_state = AppState(
        settings=settings,
        database=database,
        order_manager=order_manager,
        ledger=ledger,
        portfolio=portfolio,
        audit=audit,
        risk=risk,
        market_data=market_data,
        leases=leases,
        reconciliation=reconciliation,
        engine=engine,
    )
    return RuntimeBundle(
        settings=settings,
        database=database,
        ledger=ledger,
        portfolio=portfolio,
        order_manager=order_manager,
        market_data=market_data,
        risk=risk,
        leases=leases,
        reconciliation=reconciliation,
        audit=audit,
        adapter=adapter,
        alpha=alpha,
        engine=engine,
        app_state=app_state,
    )


async def _verify_migrations(database: Database) -> None:
    async with database.session_factory() as session:
        await session.execute(text("SELECT 1"))
