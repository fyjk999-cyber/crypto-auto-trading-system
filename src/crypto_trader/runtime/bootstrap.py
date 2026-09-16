"""The single official runtime bootstrap path.

Test/API/CLI must not each assemble a different core. They should call
`build_system(settings)` and receive a fully initialized `RuntimeBundle`.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text

from crypto_trader.alpha.ensemble import MultiStrategyAlpha
from crypto_trader.alpha.evidence_router import PerSymbolEvidenceRouter
from crypto_trader.api.deps import AppState, LLMRuntimeStatus
from crypto_trader.config import Settings
from crypto_trader.execution.authority import ExecutionAuthority
from crypto_trader.execution.hedge_legs import LegPositionReconciler, PositionLegService
from crypto_trader.factors.expert.engine import ExpertEvidenceEngine
from crypto_trader.governance.scheduler import DailyReviewScheduler
from crypto_trader.governance.trade_episode import TradeEpisodeStore
from crypto_trader.ledger.service import LedgerService
from crypto_trader.llm.tools.alpha import build_canonical_tool_registry
from crypto_trader.llm.tools.context import register_context_tools
from crypto_trader.llm_chief.context_loader import ChiefContextLoader
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.failover import CoreLLMRouter
from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
from crypto_trader.llm_chief.provider import DeepSeekProvider, GLMProvider
from crypto_trader.llm_chief.runtime_strategy import LiveLLMDecisionStrategy
from crypto_trader.llm_chief.tool_orchestrator import ToolDrivenChiefTrader
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.eligibility import EligibilityFilter
from crypto_trader.market_data.opportunity.factors import DEFAULT_FACTORS
from crypto_trader.market_data.opportunity.scanner import FactorScanner
from crypto_trader.market_data.opportunity.service import OpportunityScannerService
from crypto_trader.market_data.opportunity.universe import OkxUniverseManager
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.ml_artifacts import ArtifactResolver
from crypto_trader.ml_registry import ModelRegistry
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
from crypto_trader.sizing.service import LiveEntrySizingService
from crypto_trader.strategy.dummy import DummyStrategy
from crypto_trader.trade_plan.service import TradePlanService


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
    position_manager: LiveLLMPositionManager | None
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

    # Quant is evidence-only.  The official auto-start runtime installs a
    # single Live-LLM adapter as its executable strategy slot so no quant
    # component can bypass ChiefTraderEngine for a new direction.
    alpha = MultiStrategyAlpha(
        symbol="BTCUSDT",
        risk_per_trade="0.0005",
        max_position_notional="5000",
        max_leverage="3",
    )
    if isinstance(adapter, PaperRealMarketAdapter):
        # Quant remains evidence-only. Seed it with bounded, factual, closed
        # OKX candles so a process restart does not erase indicator context.
        # Failure is explicit on the feed and never replaced with fake data.
        await adapter.feed.warmup(alpha.mde, alpha.symbol)

    # MASTER DIRECTIVE §26/§27: per-symbol factual evidence. Every symbol's
    # quant tools run on that symbol's own engine warmed from factual closed
    # OKX candles; BTC history is never reused as another symbol's evidence.
    evidence_router = PerSymbolEvidenceRouter(
        feed=getattr(adapter, "feed", None),
        alpha_params={
            "risk_per_trade": "0.0005",
            "max_position_notional": "5000",
            "max_leverage": "3",
        },
    )
    evidence_router.register_existing(alpha.symbol, alpha)

    # MASTER DIRECTIVE §8-§15: dynamic full-market universe + factor scanner
    # + opportunity board. Evidence-only: none of this can trade, gate, or
    # assign direction; DeepSeek alone holds NEW_DIRECTION_DECISION_AUTHORITY.
    opportunity_board = OpportunityBoard()
    feed_client = getattr(getattr(adapter, "feed", None), "client", None)
    opportunity_service = None
    if feed_client is not None and settings.opportunity_scan_enabled:
        opportunity_service = OpportunityScannerService(
            universe=OkxUniverseManager(feed_client),
            okx_client=feed_client,
            board=opportunity_board,
            scanner=FactorScanner(factors=DEFAULT_FACTORS),
            eligibility=EligibilityFilter(),
            scan_interval_seconds=settings.opportunity_scan_interval_seconds,
            active_set_size=settings.opportunity_active_set_size,
            rotation_size=settings.opportunity_rotation_size,
            state_provider=(
                (lambda sym: adapter.feed.states.get(sym))
                if getattr(adapter, "feed", None) is not None
                else None
            ),
        )
    trade_plans = TradePlanService(database.session_factory)
    trade_episodes = TradeEpisodeStore(database.session_factory)
    llm_decisions = LLMDecisionStore(database.session_factory)
    chief_context = ChiefContextLoader(database.session_factory)
    # Core LLM router: DeepSeek -> GLM (fresh factual state only) -> offline.
    # Until the runtime supplies a fresh-state prompt rebuilder, the backup is
    # deliberately skipped rather than replaying a stale prompt; the router then
    # enters LLM_OFFLINE_MODE and the engine blocks new risk.
    glm_provider = GLMProvider() if os.environ.get("GLM_API_KEY") else None
    llm_provider = CoreLLMRouter(primary=DeepSeekProvider(), backup=glm_provider)
    chief = ChiefTraderEngine(provider=llm_provider)
    # Phase 4A: real fresh-state provider. On DeepSeek failure the router
    # rebuilds a CURRENT ChiefTraderContext from engine facts before GLM; a
    # missing engine/context fails safe to LLM_OFFLINE_MODE.
    runtime_holder: dict = {}

    async def fresh_context_provider(symbol, strategy_ctx):
        engine_ref = runtime_holder.get("engine")
        strategy_ref = runtime_holder.get("strategy")
        if engine_ref is None or strategy_ref is None:
            return None
        fresh_ctx = await engine_ref._strategy_context(symbol)
        if fresh_ctx is None:
            return None
        candidate = (
            strategy_ref.opportunity_board.candidate_for(symbol)
            if strategy_ref.opportunity_board is not None
            else None
        )
        chief_ctx, _ = await strategy_ref.build_chief_context(fresh_ctx, candidate=candidate)
        return chief_ctx

    # Low-Risk V2 Phase 2: 25-model factual evidence layer over the canonical
    # bounded candle/market caches. Evidence only; never an order authority.
    expert_engine = None
    if getattr(adapter, "feed", None) is not None:
        feed = adapter.feed

        async def _expert_timeframes(symbol, _feed=feed):
            bars = ("4h", "1h", "15m", "5m", "1m")
            results = await asyncio.gather(
                *(_feed.get_closed_candles(symbol, bar=bar, limit=300) for bar in bars),
                return_exceptions=True,
            )
            return {
                bar: ([] if isinstance(result, BaseException) else result)
                for bar, result in zip(bars, results, strict=False)
            }

        model_runtime = ArtifactResolver(
            ModelRegistry(os.environ.get("ML_REGISTRY_PATH", "data/ml/registry.json"))
        )
        expert_engine = ExpertEvidenceEngine(
            timeframe_provider=_expert_timeframes,
            state_provider=lambda symbol, _feed=feed: _feed.states.get(symbol),
            model_runtime=model_runtime,
        )
    if opportunity_service is not None and expert_engine is not None:
        # M2: the canonical scanner freezes the same models 01-24 factual evidence
        # contract used by the trading path. Evidence-only; never an order.
        opportunity_service.expert_engine = expert_engine
    tools = build_canonical_tool_registry(evidence_router)
    register_context_tools(tools, chief_context)
    tool_chief = ToolDrivenChiefTrader(chief, tools)
    sizer = LiveEntrySizingService(
        risk_fraction=Decimal(alpha.risk_per_trade),
        max_order_notional=risk.config.max_order_notional,
        max_leverage=risk.config.max_leverage,
    )
    live_llm = LiveLLMDecisionStrategy(
        evidence_engine=alpha,
        chief=chief,
        planner=LiveLLMTradePlanner(
            trade_plans,
            max_holding_time_seconds=settings.max_holding_time_seconds,
        ),
        decisions=llm_decisions,
        audit=audit,
        risk_summary=risk.config.model_dump(mode="json"),
        tool_chief=tool_chief,
        sizer=sizer,
        opportunity_board=opportunity_board,
        evidence_router=evidence_router,
        fresh_context_provider=fresh_context_provider,
        expert_engine=expert_engine,
    )
    strategies = [live_llm] if settings.auto_start_runtime else [DummyStrategy()]
    leg_service = PositionLegService(database.session_factory)
    position_manager = (
        LiveLLMPositionManager(
            chief=chief,
            evidence_engine=evidence_router,
            decisions=llm_decisions,
            plans=trade_plans,
            audit=audit,
            risk_summary=risk.config.model_dump(mode="json"),
            tool_chief=tool_chief,
            expert_engine=expert_engine,
            fresh_context_provider=fresh_context_provider,
            hedge_planner=LiveLLMTradePlanner(
                trade_plans,
                max_holding_time_seconds=settings.max_holding_time_seconds,
            ),
            leg_service=leg_service,
        )
        if settings.auto_start_runtime
        else None
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
        authority=ExecutionAuthority(),
        require_lease=True,
        trade_plans=trade_plans,
        position_manager=position_manager,
        trade_episodes=trade_episodes,
        daily_review_scheduler=(
            DailyReviewScheduler(
                database.session_factory,
                review_time_utc="00:00",
                canonical_only=True,
                use_local_time=True,
            )
            if settings.auto_start_runtime
            else None
        ),
        enforce_llm_entry_authority=settings.auto_start_runtime,
        opportunity_service=opportunity_service,
        llm_router=llm_provider,
        leg_service=leg_service,
        leg_reconciler=LegPositionReconciler(leg_service),
    )
    runtime_holder["engine"] = engine
    runtime_holder["strategy"] = live_llm

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
        llm_runtime=LLMRuntimeStatus(provider_instance=llm_provider),
        opportunity_board=opportunity_board,
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
        position_manager=position_manager,
        app_state=app_state,
    )


async def _verify_migrations(database: Database) -> None:
    async with database.session_factory() as session:
        await session.execute(text("SELECT 1"))
