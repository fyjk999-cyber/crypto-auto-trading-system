"""The single official runtime bootstrap path.

Test/API/CLI must not each assemble a different core. They should call
`build_system(settings)` and receive a fully initialized `RuntimeBundle`.
"""

from __future__ import annotations

import logging
import random
import uuid
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
from crypto_trader.factors.service import FactorService
from crypto_trader.factors.tool_gateway import FactorToolGateway
from crypto_trader.governance.runtime_policy import RuntimePolicyManager
from crypto_trader.governance.scheduler import DailyReviewScheduler
from crypto_trader.governance.tool_journal import ToolInvocationJournal
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
from crypto_trader.runtime.execution_symbols import (
    PAPER_PERPETUAL_REFERENCE_SYMBOLS,
    execution_symbol_for,
)
from crypto_trader.runtime.lease import LeaseManager
from crypto_trader.runtime.multi_symbol_chief_trader import MultiSymbolChiefTraderStrategyAdapter
from crypto_trader.runtime.opportunity_scanner import CheapOpportunityScanner
from crypto_trader.runtime.position_lifecycle import PositionLifecycleTracker
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


logger = logging.getLogger("crypto_trader.bootstrap")


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
    # Per-process exchange-order-id namespace: the simulated exchange
    # restarts its sequence every run while orders persist, and
    # UNIQUE(orders.exchange_order_id) would collide without this.
    adapter_order_id_namespace = f"p{uuid.uuid4().hex[:10]}-"

    if settings.paper_mode == "PAPER_REAL_MARKET":
        adapter = PaperRealMarketAdapter(
            order_id_namespace=adapter_order_id_namespace,
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
            order_id_namespace=adapter_order_id_namespace,
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

    factor_service = FactorService(database.session_factory)
    snapshot_health_holder: dict = {}

    async def _persist_factor_snapshot(snapshot) -> None:
        """Persist a decision-time snapshot with DURABLE failure telemetry.

        Success: row in factor_snapshots (fsnap_* ids replayable).
        Failure: SNAPSHOT_PERSIST_FAILED audit event + health flag; the
        failure never gates the decision but is always observable.
        """
        try:
            await factor_service.save_snapshot(snapshot)
            health = snapshot_health_holder.get("health")
            if health is not None:
                health.set("factor_snapshots", True)
        except Exception as exc:
            health = snapshot_health_holder.get("health")
            if health is not None:
                health.set(
                    "factor_snapshots", False, f"{type(exc).__name__} persist failed"
                )
            try:
                await audit.log(
                    "SNAPSHOT_PERSIST_FAILED",
                    target=getattr(snapshot, "snapshot_id", "unknown"),
                    after={"error": type(exc).__name__},
                )
            except Exception:
                pass
            raise

    decision_context_provider = LiveDecisionContextProvider(
        candle_provider=_live_candle_provider,
        symbol=symbols[0],
        candle_cache_seconds=settings.opportunity_candle_cache_seconds,
        # Directive P2: persist every decision-time factor snapshot so the
        # fsnap_* ids referenced by decision evidence resolve after restart.
        snapshot_persister=_persist_factor_snapshot,
    )
    opportunity_scanner = CheapOpportunityScanner(
        min_score=settings.opportunity_min_score,
        max_spread_bps=settings.opportunity_max_spread_bps,
    )

    # P2-1 canonical position lifecycle tracker shared by the engine
    # (writes on fill settlement) and the Chief Trader entry gates (reads).
    # Exits are NEVER gated; the tracker only fences new entries right after
    # a completed exit and versions position state for stale-signal rejects.
    position_lifecycle = PositionLifecycleTracker(
        reversal_cooldown_seconds=settings.reversal_cooldown_seconds
    )

    # Phase 2: canonical hot-reloadable runtime policy (bounded, AI-adjustable
    # decision tempo/budget only; safety params forbidden). Single DB truth
    # source; the engine hot-applies new versions at safe checkpoints.
    policy_manager = RuntimePolicyManager(
        database.session_factory,
        audit=audit,
        check_interval_seconds=5.0,
    )
    await policy_manager.initialize()

    # Phase C/D: dynamic all-market observer over the persisted instrument
    # registry. Layer-1 = one REST batch per product class (throttled);
    # Layer-2 = bounded WS candidate stream with REST fallback + stale
    # marking. ADVISORY evidence only - it never gates trading.
    #
    # P3 CS-20260830-034530-P3-AI-ATTENTION: non-core attention is owned by
    # the Market Observer AI over a bounded compressed all-market digest.
    # There is NO 24h-volume Top-K and NO rank fallback: when the AI is
    # unavailable the dynamic slots stay empty (honest absence, recorded in
    # the market_attention_decisions lineage table).
    market_observer = None
    llm_provider = GatewayProviderAdapter(llm_gateway, domain_runtime=domain_model_runtime)
    if settings.scanner_enabled:
        try:
            from crypto_trader.market_data.attention import LLMMarketAttentionSelector
            from crypto_trader.market_data.observer import (
                HierarchicalMarketObserver,
                OKXTickerWsManager,
            )
            from crypto_trader.market_data.okx_public_data import OKXPublicDataClient
            from crypto_trader.market_data.universe import DynamicMarketUniverse
            from crypto_trader.persistence.models import MarketAttentionDecisionORM

            db_path = settings.database_url.split("///")[-1]
            universe = DynamicMarketUniverse(
                db_path, data_client=OKXPublicDataClient(OKXAdapter())
            )
            ws_manager = OKXTickerWsManager()

            async def _persist_attention_lineage(row: dict) -> None:
                """Fail-safe durable attention lineage sink. Never raises."""
                async with database.session_factory() as session:
                    session.add(MarketAttentionDecisionORM(**row))
                    await session.commit()

            market_observer = HierarchicalMarketObserver(
                universe,
                ws_manager=ws_manager,
                scan_interval_seconds=60.0,
                attention_selector=LLMMarketAttentionSelector(
                    llm_provider.complete_json
                ),
                attention_lineage_sink=_persist_attention_lineage,
            )
            await ws_manager.start()
        except Exception as exc:
            # The observer is advisory: a startup failure must never block
            # the runtime. Trading continues with the configured core list.
            # The failure itself must never be silent (audit trail duty).
            logger.exception("MARKET_OBSERVER_START_FAILED error=%s", exc)
            try:
                await audit.log(
                    "MARKET_OBSERVER_START_FAILED",
                    target="market_observer",
                    before={},
                    after={"error": f"{type(exc).__name__}: {exc}"[:200]},
                )
            except Exception:
                pass
            market_observer = None

    # P3: durable running-build identity (verified running SHA contract).
    try:
        from crypto_trader.runtime.build_info import build_info

        _build = build_info()
        await audit.log(
            "RUNTIME_BUILD_SHA",
            target=str(_build.get("git_sha") or "UNKNOWN")[:64],
            after={
                "git_sha": str(_build.get("git_sha") or "UNKNOWN"),
                "sha_source": str(_build.get("sha_source") or "unresolved"),
            },
        )
    except Exception:
        logger.warning("RUNTIME_BUILD_SHA_AUDIT_FAILED", exc_info=True)

    tool_journal = ToolInvocationJournal(database.session_factory)

    chief_trader = MultiSymbolChiefTraderStrategyAdapter(
        symbols=symbols,
        provider=llm_provider,
        evidence_backend=SqlEvidenceBackend(database.session_factory),
        decision_context_provider=decision_context_provider,
        opportunity_scanner=opportunity_scanner,
        opportunity_scanner_enabled=settings.opportunity_scanner_enabled,
        opportunity_top_k=settings.opportunity_top_k,
        # Per-symbol LLM cooldown bounds token burn across the 20-symbol
        # universe (~4 calls/min at 300s) while EVERY symbol still reaches the
        # AI (the scanner is advisory-only; the AI owns selection).
        min_decision_interval_seconds=300.0,
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
        position_lifecycle=position_lifecycle,
        reversal_cooldown_seconds=settings.reversal_cooldown_seconds,
        policy_manager=policy_manager,
        market_observer=market_observer,
        tool_journal=tool_journal,
    )
    strategies = [chief_trader] if settings.auto_start_runtime else [DummyStrategy()]

    # Generic paper-perpetual registry: one engine instance serves every
    # registered bidirectional contract (BTC + the 2026-08-29 expansion
    # batch). Contract specs come from verified OKX public instruments
    # (SPOT+SWAP live checks, 2026-08-29); PAPER execution only, real OKX
    # reference prices via the canonical reference book. No new engines.
    perpetual_contracts = [
        PerpetualContract(
            symbol="BTCUSDT_PERP",
            base="BTC",
            quote="USDT",
            settlement_asset="USDT",
            quantity_step=Decimal("0.00001"),
            max_leverage=Decimal("6"),
            taker_fee_rate=Decimal("0.0005"),
        )
    ]
    # (base, contract_size=OKX ctVal, tick_size=OKX spot tickSz,
    #  quantity_step=PAPER sizing step). quantity_step is a PAPER-internal
    # sizing granularity (1e-5 base units) so every documented exploration
    # size (25-50% of normal 0.001 -> 0.00025/0.0005) passes the authority
    # precision gate exactly; notional realism comes from contract_size x
    # real OKX reference price. Fail-closed authority checks stay intact.
    _PAPER_PERP_SPECS = {
        "HYPEUSDT": ("HYPE", Decimal("0.1"), Decimal("0.001")),
        "ZECUSDT": ("ZEC", Decimal("0.01"), Decimal("0.01")),
        "ENAUSDT": ("ENA", Decimal("10"), Decimal("0.00001")),
        "WLDUSDT": ("WLD", Decimal("1"), Decimal("0.0001")),
        "ONDOUSDT": ("ONDO", Decimal("10"), Decimal("0.0001")),
        "FILUSDT": ("FIL", Decimal("0.1"), Decimal("0.0001")),
        "TAOUSDT": ("TAO", Decimal("0.01"), Decimal("0.1")),
        "AAVEUSDT": ("AAVE", Decimal("0.1"), Decimal("0.01")),
        "XLMUSDT": ("XLM", Decimal("100"), Decimal("0.00001")),
        "HBARUSDT": ("HBAR", Decimal("100"), Decimal("0.00001")),
    }
    for _ref in PAPER_PERPETUAL_REFERENCE_SYMBOLS:
        if _ref == "BTCUSDT":
            continue
        _base, _ctval, _tick = _PAPER_PERP_SPECS[_ref]
        perpetual_contracts.append(
            PerpetualContract(
                symbol=f"{_ref}_PERP",
                base=_base,
                quote="USDT",
                settlement_asset="USDT",
                contract_size=_ctval,
                tick_size=_tick,
                quantity_step=Decimal("0.00001"),
                max_leverage=Decimal("6"),
                taker_fee_rate=Decimal("0.0005"),
            )
        )
    perpetual_contract = perpetual_contracts[0]
    perpetual_engine = PerpetualPaperEngine(
        database.session_factory, perpetual_contract, contracts=perpetual_contracts
    )

    # §10: the duplicate-entry gate must see perpetual state. Wired after the
    # engine exists so the adapter can ask "is BTCUSDT_PERP already open?"
    async def _has_open_perpetual_position(symbol: str | None = None) -> bool:
        # Symbol-scoped: only the caller's own perpetual contract blocks its
        # entry (a BTC position must not prevent ETH from being considered).
        target = execution_symbol_for(symbol) if symbol else perpetual_contract.symbol
        state = await perpetual_engine.load_state()
        position = state.positions.get(target)
        return position is not None and not position.is_flat

    chief_trader.perpetual_position_provider = _has_open_perpetual_position

    async def _position_opened_at(symbol: str, side: str):
        """Real open time of the current position episode, derived from the
        latest entry-side fill for the symbol. Keeps the bridge time-stop
        age honest across process restarts."""
        from datetime import UTC
        from datetime import datetime as _dt

        from sqlalchemy import text

        entry_side = "SELL" if str(side).upper() == "SHORT" else "BUY"
        async with database.session_factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT MAX(timestamp) FROM fills "
                        "WHERE symbol = :symbol AND side = :side"
                    ),
                    {"symbol": symbol, "side": entry_side},
                )
            ).first()
        if row is None or row[0] is None:
            return None
        ts = _dt.fromisoformat(str(row[0]))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return ts

    bridge = AIPositionRuntimeBridge(
        perpetual_engine=perpetual_engine,
        time_stop_seconds=(
            settings.exploration_max_holding_seconds
            if settings.exploration_mode_active
            else None
        ),
        position_opened_at_provider=_position_opened_at,
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
        position_lifecycle=position_lifecycle,
        policy_manager=policy_manager,
        market_observer=market_observer,
    )
    snapshot_health_holder["health"] = engine.health

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
