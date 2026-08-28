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
from crypto_trader.evolution.gateways.research_gateway import ResearchGateway
from crypto_trader.execution.authority import ExecutionAuthority
from crypto_trader.factors.tool_gateway import FactorToolGateway
from crypto_trader.governance.scheduler import DailyReviewScheduler
from crypto_trader.ledger.service import LedgerService
from crypto_trader.llm_runtime.domain_models import DomainModelRuntime
from crypto_trader.llm_runtime.gateway import GatewayProviderAdapter, LLMGateway
from crypto_trader.llm_runtime.provider import OpenAICompatibleProvider
from crypto_trader.llm_runtime.repository import LLMRepository
from crypto_trader.llm_runtime.secrets import EncryptedFileSecretStore
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.observability.audit import AuditService
from crypto_trader.order.manager import OrderManager
from crypto_trader.perpetual.domain import PerpetualContract
from crypto_trader.perpetual.engine import PerpetualPaperEngine
from crypto_trader.persistence.database import Database
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.reconciliation.service import ReconciliationService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.ai_position_bridge import AIPositionRuntimeBridge
from crypto_trader.runtime.chief_trader_strategy import ChiefTraderStrategyAdapter
from crypto_trader.runtime.engine import TradingEngine
from crypto_trader.runtime.lease import LeaseManager
from crypto_trader.runtime.supervisor import TradingRuntimeSupervisor
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
    supervisor: TradingRuntimeSupervisor
    ai_bridge: AIPositionRuntimeBridge
    factor_gateway: FactorToolGateway
    llm_gateway: LLMGateway
    domain_model_runtime: DomainModelRuntime
    llm_repository: LLMRepository
    daily_review_scheduler: DailyReviewScheduler
    research_gateway: ResearchGateway
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
    llm_repository = LLMRepository(database.session_factory)
    llm_gateway = LLMGateway(
        llm_repository,
        EncryptedFileSecretStore(settings.llm_secret_store_path, settings.llm_master_key_path),
        provider_factory=lambda _config: OpenAICompatibleProvider(
            doh_endpoint=settings.llm_doh_resolver or None
        ),
    )
    await llm_gateway.reload()
    domain_model_runtime = DomainModelRuntime(llm_gateway)

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

    # MultiStrategyAlpha remains a shadow/benchmark evidence provider. It is no
    # longer the canonical entry strategy in LLM trading mode.
    alpha = MultiStrategyAlpha(
        symbol="BTCUSDT",
        risk_per_trade="0.0005",
        max_position_notional="5000",
        max_leverage="3",
    )
    chief_trader = ChiefTraderStrategyAdapter(
        provider=GatewayProviderAdapter(llm_gateway, domain_runtime=domain_model_runtime)
    )
    strategies = [chief_trader] if settings.auto_start_runtime else [DummyStrategy()]

    perpetual_contract = PerpetualContract(
        symbol="BTCUSDT_PERP",
        base="BTC",
        quote="USDT",
        settlement_asset="USDT",
        max_leverage=Decimal("6"),
        taker_fee_rate=Decimal("0.0005"),
    )
    perpetual_engine = PerpetualPaperEngine(database.session_factory, perpetual_contract)

    bridge = AIPositionRuntimeBridge(perpetual_engine=perpetual_engine)
    factor_gateway = FactorToolGateway()
    daily_review_scheduler = DailyReviewScheduler(
        database.session_factory,
        review_time_utc=settings.daily_review_time_utc,
        llm_gateway=llm_gateway,
        domain_model_runtime=domain_model_runtime,
    )
    research_gateway = ResearchGateway(
        llm_gateway=llm_gateway, domain_model_runtime=domain_model_runtime
    )
    supervisor = TradingRuntimeSupervisor(
        lease_manager=leases,
        ai_position_callback=lambda: bridge.evaluate_active_positions(engine, portfolio),
        ai_position_interval_seconds=5.0,
    )

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
        ai_position_bridge=bridge,
        authority=ExecutionAuthority(),
        perpetual_engine=perpetual_engine,
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
        supervisor=supervisor,
        ai_bridge=bridge,
        factor_gateway=factor_gateway,
        llm_gateway=llm_gateway,
        domain_model_runtime=domain_model_runtime,
        llm_repository=llm_repository,
        daily_review_scheduler=daily_review_scheduler,
        research_gateway=research_gateway,
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
        supervisor=supervisor,
        ai_bridge=bridge,
        factor_gateway=factor_gateway,
        llm_gateway=llm_gateway,
        domain_model_runtime=domain_model_runtime,
        llm_repository=llm_repository,
        daily_review_scheduler=daily_review_scheduler,
        research_gateway=research_gateway,
        app_state=app_state,
    )


async def _verify_migrations(database: Database) -> None:
    async with database.session_factory() as session:
        await session.execute(text("SELECT 1"))
