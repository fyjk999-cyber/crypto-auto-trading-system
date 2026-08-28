"""The single official runtime bootstrap path.

Test/API/CLI must not each assemble a different core. They should call
`build_system(settings)` and receive a fully initialized `RuntimeBundle`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text

from crypto_trader.alpha.ensemble import MultiStrategyAlpha
from crypto_trader.api.deps import AppState
from crypto_trader.config import Settings
from crypto_trader.domain.models import Instrument
from crypto_trader.evolution.gateways.research_gateway import ResearchGateway
from crypto_trader.exchange.okx import OKXAdapter, OKXDiagnosticError
from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.execution.authority import ExecutionAuthority
from crypto_trader.factors.tool_gateway import FactorToolGateway
from crypto_trader.governance.scheduler import DailyReviewScheduler
from crypto_trader.ledger.service import LedgerService
from crypto_trader.llm_chief.memory_retrieval import LiveMemoryProvider
from crypto_trader.llm_runtime.domain_models import DomainModelRuntime
from crypto_trader.llm_runtime.gateway import GatewayProviderAdapter, LLMGateway
from crypto_trader.llm_runtime.provider import OpenAICompatibleProvider
from crypto_trader.llm_runtime.repository import LLMRepository
from crypto_trader.llm_runtime.secrets import EncryptedFileSecretStore
from crypto_trader.market_data.public_feed import OKXPublicMarketFeed
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
from crypto_trader.runtime.engine import TradingEngine
from crypto_trader.runtime.lease import LeaseManager
from crypto_trader.runtime.multi_symbol_chief_trader import MultiSymbolChiefTraderStrategyAdapter
from crypto_trader.runtime.opportunity_scanner import CheapOpportunityScanner
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

    configured_symbols = settings.symbol_universe
    symbols = configured_symbols if settings.scanner_enabled else configured_symbols[:1]
    instruments = [
        Instrument(
            symbol=symbol,
            base_asset=symbol.removesuffix("USDT"),
            quote_asset="USDT",
            exchange="OKX_PUBLIC_PAPER",
        )
        for symbol in symbols
    ]

    # Paper is default. SimulatedExchangeAdapter implements the same contract
    # as a live adapter, so LIVE/PAPER/SHADOW share one core. PAPER_REAL_MARKET
    # uses credential-free OKX SWAP data; execution remains simulated.
    if settings.paper_mode == "PAPER_REAL_MARKET":
        adapter = PaperRealMarketAdapter(
            initial_balances={
                settings.paper_settlement_asset: Decimal(settings.paper_initial_equity)
            },
            instruments=instruments,
            feed_factory=lambda symbol: OKXPublicMarketFeed(
                symbol=symbol,
                client=OKXAdapter(base_url=settings.okx_base_url),
            ),
        )
    else:
        adapter = SimulatedExchangeAdapter(
            initial_balances={
                settings.paper_settlement_asset: Decimal(settings.paper_initial_equity)
            },
            instruments=instruments,
        )

    # MultiStrategyAlpha remains a shadow/benchmark evidence provider. It is no
    # longer the canonical entry strategy in LLM trading mode.
    alpha = MultiStrategyAlpha(
        symbol=symbols[0],
        risk_per_trade="0.0005",
        max_position_notional="5000",
        max_leverage="3",
    )
    from datetime import UTC, datetime

    from crypto_trader.evolution.persistence_backends import SqlEvidenceBackend
    from crypto_trader.runtime.live_decision_context import LiveDecisionContextProvider

    mapper = SymbolMapper()

    async def _live_candle_provider(symbol: str) -> list[dict]:
        """Public OKX SWAP 1m candles, oldest-first, for any configured symbol.

        Real market data only: failures return [] and the entry path fails
        closed. There is never a synthetic fallback in PAPER_REAL_MARKET.
        """
        canonical = mapper.to_canonical(symbol)
        provider_symbol = mapper.to_okx(canonical)
        client = OKXAdapter(base_url=settings.okx_base_url)
        try:
            rows = await client.get_candles(provider_symbol, "1m", 200)
            by_open_time: dict[str, dict] = {}
            for row in rows:
                try:
                    open_time = datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC).isoformat()
                    by_open_time[open_time] = {
                        "symbol": canonical,
                        "interval": "1m",
                        "open_time": open_time,
                        "open": str(row[1]),
                        "high": str(row[2]),
                        "low": str(row[3]),
                        "close": str(row[4]),
                        "volume": str(row[5]),
                        "source": "OKX",
                    }
                except (TypeError, ValueError, IndexError) as exc:
                    raise OKXDiagnosticError(
                        "MALFORMED_RESPONSE", "invalid candle row"
                    ) from exc
            return [by_open_time[key] for key in sorted(by_open_time)]
        except Exception:
            return []
        finally:
            await client.disconnect()

    decision_context_provider = LiveDecisionContextProvider(
        candle_provider=_live_candle_provider,
        symbol=symbols[0],
        candle_cache_seconds=settings.opportunity_candle_cache_seconds,
    )
    opportunity_scanner = CheapOpportunityScanner(
        min_score=settings.opportunity_min_score,
        max_spread_bps=settings.opportunity_max_spread_bps,
    )

    chief_trader = MultiSymbolChiefTraderStrategyAdapter(
        symbols=symbols,
        provider=GatewayProviderAdapter(llm_gateway, domain_runtime=domain_model_runtime),
        evidence_backend=SqlEvidenceBackend(database.session_factory),
        decision_context_provider=decision_context_provider,
        opportunity_scanner=opportunity_scanner,
        opportunity_scanner_enabled=settings.opportunity_scanner_enabled,
        opportunity_top_k=settings.opportunity_top_k,
        min_strategy_fit=settings.live_min_strategy_fit,
        min_trade_confidence=settings.live_min_trade_confidence,
        exploration_mode=settings.exploration_mode_active,
        exploration_min_fit=settings.exploration_min_fit,
        exploration_min_confidence=settings.exploration_min_confidence,
        exploration_probability=settings.exploration_probability,
        exploration_borderline_fit=settings.exploration_borderline_fit,
        exploration_size_fraction=settings.exploration_size_fraction,
        normal_fit_threshold=settings.normal_fit_threshold,
        normal_confidence_threshold=settings.normal_confidence_threshold,
        entry_cooldown_seconds=settings.entry_cooldown_seconds,
        exploration_sampler=random.random,
        memory_provider=LiveMemoryProvider(database.session_factory),
    )
    strategies = [chief_trader] if settings.auto_start_runtime else [DummyStrategy()]

    # The legacy perpetual paper-position engine remains BTC-only. The new
    # 20-symbol universe expands real market observation + SPOT paper entry;
    # it does not silently broaden perpetual execution authority.
    perpetual_contract = PerpetualContract(
        symbol="BTCUSDT_PERP",
        base="BTC",
        quote="USDT",
        settlement_asset="USDT",
        max_leverage=Decimal("6"),
        taker_fee_rate=Decimal("0.0005"),
    )
    perpetual_engine = PerpetualPaperEngine(database.session_factory, perpetual_contract)

    # §10: the duplicate-entry gate must see perpetual state. Wired after the
    # engine exists so the adapter can ask "is BTCUSDT_PERP already open?"
    async def _has_open_perpetual_position() -> bool:
        state = await perpetual_engine.load_state()
        position = state.positions.get(perpetual_contract.symbol)
        return position is not None and not position.is_flat

    chief_trader.perpetual_position_provider = _has_open_perpetual_position

    bridge = AIPositionRuntimeBridge(
        perpetual_engine=perpetual_engine,
        time_stop_seconds=(
            settings.exploration_max_holding_seconds
            if settings.exploration_mode_active
            else None
        ),
    )
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
