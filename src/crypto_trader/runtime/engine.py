"""TradingEngine: the only orchestration path from market event to audit.

Market Event -> StrategyPlugin -> SignalIntent -> PreTrade Risk
-> ExecutionAuthority -> OrderManager -> ExchangeAdapter -> Exchange Events
-> Order State Machine -> Ledger -> Portfolio Projection -> Audit
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from crypto_trader.config import Settings
from crypto_trader.domain.clock import Clock, SystemClock
from crypto_trader.domain.enums import (
    TERMINAL_ORDER_STATUSES,
    ExchangeEventType,
    ExecutionDecision,
    LedgerDirection,
    LedgerEntryType,
    OrderSide,
    OrderStatus,
    RuntimeState,
    TradingMode,
)
from crypto_trader.domain.errors import (
    ExchangeError,
    InvalidStateTransition,
    LeaseNotHeld,
    MarketDataUnhealthy,
    OrderRejected,
    RateLimited,
    TemporaryNetworkError,
    UnknownExecutionState,
)
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import (
    ExchangeEvent,
    Fill,
    OrderIntent,
    RiskDecision,
    SignalIntent,
)
from crypto_trader.domain.money import D
from crypto_trader.exchange.base import ExchangeAdapter
from crypto_trader.execution.authority import AuthorizationContext, ExecutionAuthority
from crypto_trader.execution.contract import derive_execution_terms
from crypto_trader.governance.scheduler import DailyReviewScheduler
from crypto_trader.governance.trade_episode import TradeEpisodeStore
from crypto_trader.ledger.projections import replay_projections
from crypto_trader.ledger.service import (
    LedgerPosting,
    LedgerService,
    build_derivative_trade_entries,
    build_trade_entries,
)
from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
from crypto_trader.llm_chief.reassessment import ReassessmentEvaluator
from crypto_trader.llm_chief.state_version import position_state_version
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.observability.audit import AuditService
from crypto_trader.order.manager import OrderManager
from crypto_trader.persistence.database import Database
from crypto_trader.persistence.models import EngineRunORM, FillORM, RiskDecisionORM
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.reconciliation.service import ReconciliationService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.event_bus import EventBus
from crypto_trader.runtime.exit_controller import DeterministicExitController
from crypto_trader.runtime.health import HealthRegistry
from crypto_trader.runtime.lease import Lease, LeaseManager
from crypto_trader.runtime.lineage import lineage_from_order, validate_lineage
from crypto_trader.runtime.lineage_audit import LineageCoverageAuditor
from crypto_trader.runtime.offline import OfflineMode
from crypto_trader.runtime.recovery import RecoveryService
from crypto_trader.runtime.state_machine import RuntimeStateMachine
from crypto_trader.strategy.base import StrategyContext, StrategyPlugin
from crypto_trader.trade_plan.service import TradePlanService, TradePlanState

logger = logging.getLogger("crypto_trader.engine")


class TradingEngine:
    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        adapter: ExchangeAdapter,
        order_manager: OrderManager,
        ledger: LedgerService,
        portfolio: PortfolioService,
        risk_engine: RiskEngine,
        market_data: MarketDataService,
        lease_manager: LeaseManager,
        reconciliation: ReconciliationService | None = None,
        audit: AuditService | None = None,
        strategies: list[StrategyPlugin] | None = None,
        clock: Clock | None = None,
        authority: ExecutionAuthority | None = None,
        lease_key: str = "crypto_engine_execution",
        require_lease: bool = True,
        trade_plans: TradePlanService | None = None,
        position_manager: LiveLLMPositionManager | None = None,
        trade_episodes: TradeEpisodeStore | None = None,
        daily_review_scheduler: DailyReviewScheduler | None = None,
        enforce_llm_entry_authority: bool = False,
        opportunity_service=None,
        llm_router=None,
        leg_service=None,
        leg_reconciler=None,
        exit_controller=None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.adapter = adapter
        self.order_manager = order_manager
        self.ledger = ledger
        self.portfolio = portfolio
        self.risk_engine = risk_engine
        self.market_data = market_data
        self.lease_manager = lease_manager
        self.reconciliation = reconciliation or ReconciliationService(database.session_factory)
        self.audit = audit or AuditService(database.session_factory)
        self.strategies = strategies or []
        self.clock = clock or SystemClock()
        self.authority = authority or ExecutionAuthority()
        self.lease_key = lease_key
        self.require_lease = require_lease
        self.trade_plans = trade_plans or TradePlanService(database.session_factory)
        # Low-Risk V2 deterministic protection layer (Risk/Base Exit/Fast Profit).
        self.exit_controller = exit_controller or DeterministicExitController()
        self.reassessment_evaluator = ReassessmentEvaluator()
        self._last_reassessment_wake: dict[str, str] = {}
        self.offline_mode = OfflineMode()
        self.llm_router = llm_router
        # Phase 4D: per-leg fill attribution for hedge/reverse legs.
        self.leg_service = leg_service
        self.leg_reconciler = leg_reconciler
        self.lineage_auditor = LineageCoverageAuditor(database.session_factory)
        # Flip only when the portfolio tracks legs (not net) as source of truth.
        self.leg_execution_enabled = False
        self.position_manager = position_manager
        self.trade_episodes = trade_episodes or TradeEpisodeStore(database.session_factory)
        self.daily_review_scheduler = daily_review_scheduler
        self.enforce_llm_entry_authority = enforce_llm_entry_authority
        self.opportunity_service = opportunity_service
        self.event_bus = EventBus()
        self.health = HealthRegistry()
        self.state_machine = RuntimeStateMachine()

        self.run_id: str | None = None
        self.lease: Lease | None = None
        self._lease_valid = not require_lease
        self.reconciliation_halted = False
        self._event_queue: asyncio.Queue[ExchangeEvent] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._initial_balances: dict[str, Decimal] = {}
        self._instruments: dict[str, object] = {}
        self.consecutive_failures = 0

    # ------------------------------------------------------------------ state
    async def start(self, run_id: str | None = None) -> str:
        if self._running:
            return self.run_id
        self.run_id = run_id or new_id("run")
        self.state_machine.transition(RuntimeState.STARTING)
        await self._persist_run(RuntimeState.STARTING)
        await self.adapter.connect()
        self.health.set("adapter_connection", True)

        # NOTE: the execution lease is acquired AFTER recovery, immediately
        # before the trading loops start. Acquiring earlier (right after
        # connect) lets the slow startup path (recovery, warmup, subscribe)
        # outlive the lease TTL, so the first renewal finds expires_at in the
        # past and the engine fails safe without a lease forever.
        self.state_machine.transition(RuntimeState.RECOVERING)
        await self._persist_run(RuntimeState.RECOVERING)
        await self._seed_initial_balances()
        await self._load_instruments()
        await self._restore_paper_adapter_state()
        self.order_manager.settlement_callback = self._settle_fill
        await self._run_recovery(self.run_id)
        await self._sync_terminal_entry_plans()
        self.health.set("recovery", True)

        if self.require_lease:
            self.lease = await self.lease_manager.acquire(
                self.lease_key, f"engine_{self.run_id}", self.settings.run_lease_ttl_seconds
            )
            if self.lease is None:
                await self._persist_run(RuntimeState.STOPPED)
                self.state_machine.transition(RuntimeState.STOPPED)
                raise LeaseNotHeld("another engine instance holds the execution lease")
            self._lease_valid = True
            stale_runs = await self._reconcile_stale_runs()
            if stale_runs:
                await self.audit.log(
                    "STALE_RUNTIME_ROWS_RECONCILED",
                    target=self.run_id,
                    run_id=self.run_id,
                    after={"stale_run_ids": stale_runs},
                )
        self.health.set("execution_lease", self.lease is not None or not self.require_lease)

        self.state_machine.transition(RuntimeState.RUNNING)
        await self._persist_run(RuntimeState.RUNNING)
        await self.adapter.subscribe_order_updates(self._enqueue_event)
        await self.adapter.subscribe_market_data("*", self._enqueue_event)
        await self.adapter.subscribe_account_updates(self._enqueue_event)
        self._running = True
        self._tasks = [
            asyncio.create_task(self._event_loop(), name="engine-events"),
            asyncio.create_task(self._tick_loop(), name="engine-ticks"),
        ]
        if self.require_lease:
            self._tasks.append(asyncio.create_task(self._lease_loop(), name="engine-lease"))
        self._tasks.append(asyncio.create_task(self._reconciliation_loop(), name="engine-recon"))
        if self.daily_review_scheduler is not None:
            self._tasks.append(
                asyncio.create_task(self.daily_review_scheduler.loop(), name="daily-review")
            )
        if self.opportunity_service is not None:
            # Full-market opportunity discovery runs as an independent
            # evidence-only task (MASTER DIRECTIVE §11/§24). It never trades,
            # never gates, and cannot bypass the live-LLM entry authority.
            self._tasks.append(
                asyncio.create_task(
                    self.opportunity_service.run_forever(), name="opportunity-scanner"
                )
            )
        await self.audit.log("ENGINE_STARTED", target=self.run_id, run_id=self.run_id)
        return self.run_id

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self.lease is not None:
            await self.lease_manager.release(
                self.lease_key,
                self.lease.token,
                owner_id=self.lease.owner_id,
                fence_generation=self.lease.fence_generation,
            )
            self.lease = None
        self._lease_valid = not self.require_lease
        await self.adapter.disconnect()
        self.state_machine.transition(RuntimeState.STOPPING)
        self.state_machine.transition(RuntimeState.STOPPED)
        await self._persist_run(RuntimeState.STOPPED)
        await self.audit.log("ENGINE_STOPPED", target=self.run_id or "", run_id=self.run_id)

    async def _persist_run(self, state: RuntimeState) -> None:
        async with self.database.session_factory() as session:
            row = await session.get(EngineRunORM, self.run_id)
            now = datetime.now(UTC)
            if row is None:
                session.add(
                    EngineRunORM(
                        run_id=self.run_id,
                        state=state.value,
                        mode=self.settings.effective_mode().value,
                        strategy_id=",".join(s.name for s in self.strategies) or "none",
                        started_at=now,
                        metadata_json={"lease_key": self.lease_key},
                    )
                )
            else:
                row.state = state.value
                if state == RuntimeState.STOPPED:
                    row.ended_at = now
            await session.commit()

    async def _run_recovery(self, run_id: str | None) -> list[str]:
        """Run crash recovery, including orphan-position restoration."""
        actions = await RecoveryService(
            self.order_manager,
            self.adapter,
            self.audit,
            positions_provider=self.portfolio.get_positions,
            plans=self.trade_plans,
            ledger_state_provider=self._ledger_state,
        ).recover(run_id)
        divergence = await self._factual_exposure_divergences()
        if divergence:
            # Local factual fills imply exposure the portfolio/exchange does not
            # show (e.g. a PAPER simulator restart): halt new risk until a human
            # or reconciliation resolves it. Fail closed, never guess.
            self.reconciliation_halted = True
            self.health.set("recovery_factual_state", False, "FACTUAL_EXPOSURE_DIVERGENCE")
            await self.audit.log(
                "RECOVERY_FACTUAL_DIVERGENCE",
                run_id=run_id,
                after={"divergences": divergence[:5]},
            )
            actions.append("RECOVERY_FACTUAL_DIVERGENCE")
        else:
            self.health.set("recovery_factual_state", True, "MATCHED")
        if self.leg_service is not None and self.leg_reconciler is not None:
            open_legs = await self.leg_service.open_legs_all()
            for symbol in sorted({str(leg["symbol"]) for leg in open_legs}):
                position = await self.portfolio.get_position(symbol)
                quantity = position.quantity if position is not None else Decimal("0")
                leg_report = await self.leg_reconciler.reconcile(
                    symbol,
                    quantity,
                    broker_quantity=quantity,
                    after_restart=True,
                )
                if not leg_report["leg_execution_safe"]:
                    self.reconciliation_halted = True
                    self.health.set("leg_reconciliation", False, str(leg_report["status"]))
                    await self.audit.log(
                        "LEG_RECONCILIATION_HALTED",
                        target=symbol,
                        run_id=run_id,
                        after={
                            "status": leg_report["status"],
                            "legacy_status": leg_report["legacy_status"],
                            "checks": leg_report["checks"],
                            "leg_quantity_issues": leg_report["leg_quantity_issues"][:3],
                            "orphan_fills": leg_report["orphan_fills"][:3],
                            "unknown_orders": leg_report["unknown_orders"][:3],
                        },
                    )
                    actions.append("LEG_RECONCILIATION_HALTED")
                else:
                    self.health.set("leg_reconciliation", True, str(leg_report["status"]))
        report = await self.lineage_auditor.audit()
        self.health.set("factual_fill_lineage", bool(report["ok"]), report.get("flag") or "OK")
        if not report["ok"]:
            await self.audit.log(
                "RECOVERY_LINEAGE_GAPS",
                run_id=run_id,
                after={
                    "untracked_count": report["untracked_count"],
                    "fill_count": report["fill_count"],
                    "samples": report["untracked"][:5],
                },
            )
            actions.append("RECOVERY_LINEAGE_GAPS")
        return actions

    async def _factual_exposure_divergences(self) -> list[dict]:
        """Compare signed DB fill quantities with the live portfolio per symbol."""
        async with self.database.session_factory() as session:
            rows = (
                await session.execute(select(FillORM.symbol, FillORM.side, FillORM.quantity))
            ).all()
        db_net: dict[str, Decimal] = {}
        for symbol, side, quantity in rows:
            sign = Decimal("1") if str(side).upper() == "BUY" else Decimal("-1")
            db_net[symbol] = db_net.get(symbol, Decimal("0")) + sign * Decimal(str(quantity))
        positions = await self.portfolio.get_positions()
        if isinstance(positions, dict):
            positions = list(positions.values())
        portfolio_net: dict[str, Decimal] = {}
        for item in positions:
            if isinstance(item, dict):
                symbol = item.get("symbol")
                quantity = item.get("quantity")
            else:
                symbol = getattr(item, "symbol", None)
                quantity = getattr(item, "quantity", None)
            if symbol is not None and quantity is not None:
                portfolio_net[symbol] = Decimal(str(quantity))
        divergences = []
        for symbol in sorted(set(db_net) | set(portfolio_net)):
            expected = db_net.get(symbol, Decimal("0"))
            actual = portfolio_net.get(symbol, Decimal("0"))
            if abs(expected - actual) > Decimal("0.00000001"):
                divergences.append(
                    {
                        "symbol": symbol,
                        "db_fill_net": str(expected),
                        "portfolio_qty": str(actual),
                    }
                )
        return divergences

    async def _ledger_state(self) -> tuple[dict, dict]:
        account = await self.portfolio.get_account(self.settings.effective_mode())
        positions = await self.portfolio.get_positions()
        return account.balances, positions

    async def _reconcile_stale_runs(self) -> list[str]:
        """Close abandoned rows only after this process owns the fenced lease."""

        if self.lease is None or not self._lease_valid:
            return []
        async with self.database.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(EngineRunORM).where(
                            EngineRunORM.run_id != self.run_id,
                            EngineRunORM.ended_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            now = datetime.now(UTC)
            for row in rows:
                row.state = RuntimeState.STOPPED.value
                row.ended_at = now
                row.metadata_json = {
                    **(row.metadata_json or {}),
                    "shutdown_reason": "STALE_RUN_RECONCILED",
                    "recovered_by": self.run_id,
                    "recovery_fence_generation": self.lease.fence_generation,
                }
            await session.commit()
            return sorted(row.run_id for row in rows)

    # ------------------------------------------------------------ event loop
    async def _enqueue_event(self, event: ExchangeEvent) -> None:
        await self._event_queue.put(event)

    async def _event_loop(self) -> None:
        while True:
            event = await self._event_queue.get()
            try:
                await self.process_exchange_event(event)
            except Exception:
                self.health.set("event_processing", False, "unhandled event error")
            finally:
                self._event_queue.task_done()

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.engine_tick_seconds)
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.consecutive_failures += 1
                self.health.set("engine_loop", False, type(exc).__name__)
                await self.audit.log(
                    "ENGINE_TICK_FAILED",
                    target=self.run_id or "unknown",
                    run_id=self.run_id,
                    after={"error_type": type(exc).__name__},
                )

    async def _lease_loop(self) -> None:
        # Renew immediately (t=0) and then on the configured cadence so the
        # lease is refreshed as soon as the trading loops start.
        while True:
            if self.lease is not None:
                try:
                    ok = await self.lease_manager.renew(
                        self.lease_key,
                        self.lease.token,
                        self.settings.run_lease_ttl_seconds,
                        owner_id=self.lease.owner_id,
                        fence_generation=self.lease.fence_generation,
                    )
                except Exception:
                    ok = False
                self._lease_valid = ok
                self.health.set("execution_lease", ok)
                if not ok:
                    self.risk_engine.kill_switch.engage("execution lease lost")
                    await self.audit.log(
                        "EXECUTION_LEASE_LOST",
                        target=self.lease_key,
                        run_id=self.run_id,
                    )
            await asyncio.sleep(self.settings.run_lease_renew_interval_seconds)

    async def _reconciliation_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.reconciliation_interval_seconds)
            report = await self.reconciliation.reconcile(self.adapter)
            self.reconciliation_halted = report.halt
            self.health.set("reconciliation", not report.halt, "; ".join(report.alerts[:3]))

    # ------------------------------------------------------------- offline
    async def enter_offline_mode(self, reason: str) -> bool:
        """Enter LLM_OFFLINE_MODE: cancel pending new risk, reduce-only only."""
        if not self.offline_mode.enter(reason):
            return False
        await self.audit.log(
            "LLM_OFFLINE_MODE",
            target=self.run_id or "offline",
            run_id=self.run_id,
            after={
                "reason": reason,
                "window_seconds": self.offline_mode.window_seconds,
                "next_probe_at": self.offline_mode.snapshot()["next_probe_at"],
            },
        )
        for order in self.offline_mode.pending_new_risk_orders(
            await self.order_manager.list_open()
        ):
            try:
                await self.order_manager.cancel_pending(
                    order.internal_order_id, reason="LLM_OFFLINE_MODE"
                )
                if order.exchange_order_id:
                    await self.adapter.cancel_order(order.symbol, order.exchange_order_id)
                await self.audit.log(
                    "OFFLINE_CANCEL_PENDING_NEW_RISK",
                    target=order.client_order_id,
                    run_id=self.run_id,
                    client_order_id=order.client_order_id,
                    order_id=order.internal_order_id,
                )
            except Exception:
                logger.exception(
                    "OFFLINE_CANCEL_NEW_RISK_FAILED order_id=%s", order.internal_order_id
                )
        try:
            await self._run_recovery(self.run_id)
        except Exception:
            logger.exception("OFFLINE_RECONCILE_FAILED")
        return True

    async def attempt_offline_recovery(self) -> bool:
        """Provider recovered: reconcile facts first, then return to NORMAL."""
        if not self.offline_mode.is_offline:
            return True
        try:
            await self._run_recovery(self.run_id)
        except Exception:
            self.offline_mode.probe_failed()
            await self.audit.log(
                "OFFLINE_RECOVERY_RECONCILE_FAILED", target=self.run_id or "offline"
            )
            return False
        recovered = self.offline_mode.complete_recovery(reconciled=True)
        if recovered:
            await self.audit.log(
                "LLM_RECOVERED_NORMAL",
                target=self.run_id or "offline",
                run_id=self.run_id,
            )
        return recovered

    async def _sync_offline_mode(self) -> None:
        router = self.llm_router
        if router is None:
            return
        router_offline = bool(getattr(router, "offline", False))
        if router_offline and not self.offline_mode.is_offline:
            await self.enter_offline_mode("CORE_LLM_ROUTER_OFFLINE")
        elif not router_offline and self.offline_mode.is_offline:
            await self.attempt_offline_recovery()

    # ------------------------------------------------------------------ tick
    async def tick(self) -> list[RiskDecision]:
        decisions: list[RiskDecision] = []
        await self._sync_offline_mode()
        if self.offline_mode.is_offline:
            # ok=False means the offline flag is active (unhealthy condition).
            self.health.set("llm_offline_mode", False, "LLM_OFFLINE_MODE")
            strategies = []
        else:
            strategies = list(self.strategies)
            # ok=True means normal online operation; the actual offline state is
            # also exposed verbatim in runtime_snapshot()["llm_offline_mode"].
            self.health.set("llm_offline_mode", True, "NORMAL")
        for strategy in strategies:
            desired_symbol = None
            desired_getter = getattr(strategy, "desired_symbol", None)
            if callable(desired_getter):
                try:
                    desired_symbol = desired_getter()
                except Exception:
                    desired_symbol = None  # scheduling failure never gates trading
            ctx = await self._strategy_context(desired_symbol)
            if ctx is None:
                continue
            try:
                signals = await strategy.on_market_data(ctx)
            except Exception as exc:
                self.consecutive_failures += 1
                self.health.set(f"strategy:{strategy.name}", False, type(exc).__name__)
                continue
            self.consecutive_failures = 0
            self.health.set(f"strategy:{strategy.name}", True)
            for signal in signals:
                decision = await self.process_signal(signal)
                if decision is not None:
                    decisions.append(decision)
        open_legs = await self.leg_service.open_legs_all() if self.leg_service is not None else []
        leg_symbols = sorted({str(leg["symbol"]) for leg in open_legs})
        for symbol in leg_symbols:
            ctx = await self._strategy_context(symbol)
            if ctx is None:
                continue
            # Gross legs get their own deterministic protection regardless of
            # the net aggregate (a LONG+SHORT symbol can net to zero).
            leg_signals, leg_wake = await self._leg_deterministic_exit_signals(symbol, ctx)
            for signal, exit_request_id in leg_signals:
                decision = await self.process_signal(signal)
                if decision is not None:
                    decisions.append(decision)
                if decision is None or decision.decision not in {
                    ExecutionDecision.APPROVE,
                    ExecutionDecision.SCALE_DOWN,
                }:
                    self.exit_controller.cancel(exit_request_id, "DETERMINISTIC_EXIT_NOT_SUBMITTED")
            if leg_wake and self.position_manager is not None:
                position = await self.portfolio.get_position(symbol)
                if position is not None:
                    try:
                        signal = await self.position_manager.review(ctx, position, force=True)
                    except Exception as exc:
                        self.consecutive_failures += 1
                        self.health.set("position_manager", False, type(exc).__name__)
                    else:
                        self.health.set("position_manager", True)
                        if signal is not None:
                            decision = await self.process_signal(signal)
                            if decision is not None:
                                decisions.append(decision)
        positions = await self.portfolio.get_positions()
        for position in positions.values():
            if position.quantity == 0:
                continue
            if position.symbol in leg_symbols:
                # Already handled by the independent leg scan above.
                continue
            ctx = await self._strategy_context(position.symbol)
            if ctx is None:
                continue
            # Low-Risk V2 deterministic protection runs BEFORE any LLM review:
            # Risk hard exit > Fast Profit > Active Base Exit.
            exit_signals, wake_required = await self._deterministic_exit_signals(ctx, position)
            for signal, exit_request_id in exit_signals:
                decision = await self.process_signal(signal)
                if decision is not None:
                    decisions.append(decision)
                if decision is None or decision.decision not in {
                    ExecutionDecision.APPROVE,
                    ExecutionDecision.SCALE_DOWN,
                }:
                    self.exit_controller.cancel(exit_request_id, "DETERMINISTIC_EXIT_NOT_SUBMITTED")
            if self.position_manager is None:
                continue
            plan = await self.trade_plans.get_active_for_symbol(position.symbol)
            horizon_wake = plan is not None and self.position_manager.horizon_wake_due(
                position, plan, ctx.clock_time.astimezone(UTC)
            )
            reassessment_wake = False
            if plan is not None and getattr(plan, "next_reassessment", None):
                indicator_feed = {
                    key: value
                    for key, value in {
                        "atr_pct": getattr(ctx, "realized_volatility", None),
                        "mark_price": ctx.mark_price,
                        "funding": getattr(ctx, "funding", None),
                        "oi": getattr(ctx, "oi", None),
                        "basis": getattr(ctx, "basis", None),
                    }.items()
                    if value is not None
                }
                wake = self.reassessment_evaluator.evaluate(
                    plan.next_reassessment,
                    now=ctx.clock_time.astimezone(UTC),
                    price=ctx.mark_price or ctx.book.mid_price(),
                    indicators=indicator_feed,
                )
                if wake.triggered:
                    fingerprint = "|".join(wake.matched_conditions) + (
                        f"#{getattr(plan, 'plan_version', 1)}"
                    )
                    if self._last_reassessment_wake.get(plan.trade_plan_id) != fingerprint:
                        self._last_reassessment_wake[plan.trade_plan_id] = fingerprint
                        reassessment_wake = True
                        await self.audit.log(
                            "NEXT_REASSESSMENT_WAKE",
                            target=plan.trade_plan_id,
                            run_id=self.run_id,
                            after={
                                **wake.as_dict(),
                                "trade_plan_id": plan.trade_plan_id,
                                "state_version": self._position_state_version(position, plan),
                            },
                        )
            if wake_required or horizon_wake or reassessment_wake:
                await self.audit.log(
                    "LLM_REASSESSMENT_REQUESTED",
                    target=position.symbol,
                    run_id=self.run_id,
                    after={
                        "trade_plan_id": plan.trade_plan_id if plan else None,
                        "risk_wake": wake_required,
                        "expected_holding_horizon_wake": horizon_wake,
                        "next_reassessment_wake": reassessment_wake,
                        "state_version": (
                            self._position_state_version(position, plan)
                            if plan is not None
                            else position_state_version(position, plan)
                        ),
                        "authority": "REASSESSMENT_ONLY",
                        "is_order": False,
                    },
                )
            try:
                signal = await self.position_manager.review(
                    ctx,
                    position,
                    force=wake_required or horizon_wake or reassessment_wake,
                )
            except Exception as exc:
                self.consecutive_failures += 1
                self.health.set("position_manager", False, type(exc).__name__)
                continue
            self.health.set("position_manager", True)
            if signal is not None:
                decision = await self.process_signal(signal)
                if decision is not None:
                    decisions.append(decision)
        self.health.set("engine_loop", True)
        return decisions

    @staticmethod
    def _position_state_version(position, plan) -> str:
        return position_state_version(position, plan)

    async def _deterministic_exit_signals(
        self, ctx, position
    ) -> tuple[list[tuple[SignalIntent, str]], bool]:
        """Build canonical reduce-only signals for deterministic protections."""
        plan = await self.trade_plans.get_active_for_symbol(position.symbol)
        if plan is None or position.quantity == 0:
            return [], False
        side = "LONG" if position.quantity > 0 else "SHORT"
        entry = D(str(position.avg_entry_price or "0"))
        mark = ctx.mark_price or ctx.book.mid_price() or entry
        if mark is None or mark <= 0:
            return [], False
        state_version = self._position_state_version(position, plan)
        equity = ctx.account.equity if ctx.account is not None else Decimal("0")
        notional = (
            abs(position.quantity)
            * mark
            * D(str(position.contract_size))
            * D(str(position.contract_multiplier))
        )
        leg_key = plan.trade_plan_id
        leg_key_mode = "SYNTHETIC"
        if self.leg_service is not None:
            open_legs = await self.leg_service.open_legs_for_symbol(position.symbol)
            matching = [leg for leg in open_legs if leg["side"] == side]
            if len(matching) == 1:
                leg_key = matching[0]["leg_id"]
                leg_key_mode = "PERSISTED_LEG"
            elif len(matching) > 1:
                leg_key_mode = "AMBIGUOUS_MULTI_LEG"
            await self.audit.log(
                "DETERMINISTIC_EXIT_LEG_KEY",
                target=leg_key,
                run_id=self.run_id,
                after={"mode": leg_key_mode, "symbol": position.symbol, "side": side},
            )
        self.exit_controller.ensure_leg(
            leg_id=leg_key,
            symbol=position.symbol,
            side=side,
            quantity=abs(position.quantity),
            entry_price=entry,
            state_version=state_version,
            plan_version=int(getattr(plan, "plan_version", 1) or 1),
            base_exit=plan.base_exit,
            exposure_usd=notional,
            equity_usd=equity if equity > 0 else Decimal("1"),
            leverage=D(str(plan.requested_leverage or "1")),
            notional_usd=notional,
            unrealized_pnl_pct=0.0,
        )
        market_state = None
        get_market_state = getattr(self.adapter, "get_market_state", None)
        if get_market_state is not None:
            try:
                market_state = await get_market_state(position.symbol)
            except Exception:
                market_state = None
        atr_pct = float(ctx.realized_volatility or 0.0)
        intents = self.exit_controller.evaluate(
            leg_key,
            price=mark,
            state=market_state,
            atr_pct=atr_pct,
        )
        signals: list[tuple[SignalIntent, str]] = []
        wake_required = any(item.requires_llm_reassessment for item in intents)
        for intent in intents:
            if intent.reservation_request_id is None:
                continue
            if not intent.quantity or intent.quantity <= 0:
                # Wake-LLM intents are handled by the canonical position review.
                continue
            # Freshness guard: a factual change while building the intent makes
            # the deterministic decision stale; the reservation is released.
            if intent.state_version != self._position_state_version(position, plan):
                self.exit_controller.cancel(
                    intent.reservation_request_id, "STALE_DECISION_BEFORE_SUBMIT"
                )
                await self.audit.log(
                    "DETERMINISTIC_EXIT_STALE",
                    target=intent.reservation_request_id,
                    run_id=self.run_id,
                    after={"reason_code": intent.reason_code},
                )
                continue
            signal = SignalIntent(
                signal_id=new_id("detexit"),
                strategy_id="live_llm_position",
                symbol=position.symbol,
                side=OrderSide.SELL if side == "LONG" else OrderSide.BUY,
                quantity=intent.quantity,
                reason=intent.reason_code,
                metadata={
                    "trade_plan_id": plan.trade_plan_id,
                    **({"leg_id": leg_key} if leg_key_mode == "PERSISTED_LEG" else {}),
                    "decision_id": f"det_{intent.reservation_request_id}",
                    "direction": plan.direction,
                    "lifecycle_action": intent.reason_code,
                    "reduce_only": True,
                    "deterministic_exit": True,
                    "exit_authority": intent.authority,
                    "exit_request_id": intent.reservation_request_id,
                    "state_version": intent.state_version,
                    "instrument_type": position.instrument_type,
                    "contract_size": str(position.contract_size),
                    "contract_multiplier": str(position.contract_multiplier),
                    "requested_leverage": str(plan.requested_leverage or "1"),
                },
            )
            await self.audit.log(
                "DETERMINISTIC_EXIT_INTENT",
                target=signal.signal_id,
                run_id=self.run_id,
                client_order_id=f"{signal.strategy_id}_{signal.signal_id}"[:60],
                after=intent.as_dict(),
            )
            signals.append((signal, intent.reservation_request_id))
        return signals, wake_required

    @staticmethod
    def _leg_state_version(leg: dict) -> str:
        updated = leg.get("updated_at")
        return "|".join(
            [
                str(leg.get("leg_id")),
                str(leg.get("state_version") or ""),
                str(leg.get("remaining_quantity")),
                updated.isoformat() if hasattr(updated, "isoformat") else "none",
            ]
        )

    async def _leg_deterministic_exit_signals(
        self, symbol: str, ctx
    ) -> tuple[list[tuple[SignalIntent, str]], bool]:
        """Evaluate deterministic protections per persisted leg.

        Net position is only a view: a same-symbol LONG+SHORT can net to zero
        while both legs carry real risk, so this scan never keys off the net.
        """
        if self.leg_service is None:
            return [], False
        legs = await self.leg_service.open_legs_for_symbol(symbol)
        if not legs:
            return [], False
        mark = ctx.mark_price or ctx.book.mid_price()
        if mark is None or mark <= 0:
            return [], False
        equity = ctx.account.equity if ctx.account is not None else Decimal("0")
        position = await self.portfolio.get_position(symbol)
        instrument_type = getattr(position, "instrument_type", "LINEAR_PERP")
        contract_size = str(getattr(position, "contract_size", Decimal("1")) or 1)
        contract_multiplier = str(getattr(position, "contract_multiplier", Decimal("1")) or 1)
        market_state = None
        get_market_state = getattr(self.adapter, "get_market_state", None)
        if get_market_state is not None:
            try:
                market_state = await get_market_state(symbol)
            except Exception:
                market_state = None
        atr_pct = float(ctx.realized_volatility or 0.0)
        signals: list[tuple[SignalIntent, str]] = []
        wake_required = False
        for leg in legs:
            leg_id = str(leg["leg_id"])
            side = str(leg["side"])
            remaining = Decimal(str(leg["remaining_quantity"]))
            plan = None
            if leg.get("trade_plan_id"):
                plan = await self.trade_plans.get(str(leg["trade_plan_id"]))
            base_exit = leg.get("base_exit") or (plan.base_exit if plan is not None else None)
            if not base_exit:
                await self.audit.log(
                    "LEG_EXIT_MISSING_BASE_EXIT",
                    target=leg_id,
                    run_id=self.run_id,
                    after={"symbol": symbol, "side": side},
                )
                continue
            entry = D(str(leg.get("average_entry_price") or mark))
            state_version = self._leg_state_version(leg)
            notional = (
                remaining
                * Decimal(str(mark))
                * Decimal(contract_size)
                * Decimal(contract_multiplier)
            )
            self.exit_controller.ensure_leg(
                leg_id=leg_id,
                symbol=symbol,
                side=side,
                quantity=remaining,
                entry_price=entry,
                state_version=state_version,
                plan_version=int(getattr(plan, "plan_version", 1) or 1),
                base_exit=base_exit,
                exposure_usd=notional,
                equity_usd=equity if equity > 0 else Decimal("1"),
                leverage=D(str(getattr(plan, "requested_leverage", 1) or 1)),
                notional_usd=notional,
                unrealized_pnl_pct=0.0,
            )
            intents = self.exit_controller.evaluate(
                leg_id,
                price=mark,
                state=market_state,
                atr_pct=atr_pct,
            )
            wake_required = wake_required or any(item.requires_llm_reassessment for item in intents)
            for intent in intents:
                if intent.reservation_request_id is None:
                    continue
                if not intent.quantity or intent.quantity <= 0:
                    continue
                fresh_legs = await self.leg_service.open_legs_for_symbol(symbol)
                current = next((item for item in fresh_legs if item["leg_id"] == leg_id), None)
                if current is None:
                    self.exit_controller.cancel(
                        intent.reservation_request_id, "LEG_CLOSED_BEFORE_SUBMIT"
                    )
                    await self.audit.log(
                        "LEG_EXIT_LEG_CLOSED_BEFORE_SUBMIT",
                        target=leg_id,
                        run_id=self.run_id,
                    )
                    continue
                if str(intent.state_version) != self._leg_state_version(current):
                    self.exit_controller.cancel(
                        intent.reservation_request_id, "STALE_DECISION_BEFORE_SUBMIT"
                    )
                    await self.audit.log(
                        "DETERMINISTIC_EXIT_STALE",
                        target=intent.reservation_request_id,
                        run_id=self.run_id,
                        after={"leg_id": leg_id, "reason_code": intent.reason_code},
                    )
                    continue
                current_remaining = Decimal(str(current["remaining_quantity"]))
                qty = min(Decimal(str(intent.quantity)), current_remaining)
                if qty <= 0:
                    continue
                signal = SignalIntent(
                    signal_id=new_id("detexit"),
                    strategy_id="live_llm_position",
                    symbol=symbol,
                    side=OrderSide.SELL if side == "LONG" else OrderSide.BUY,
                    quantity=qty,
                    reason=intent.reason_code,
                    metadata={
                        "trade_plan_id": str(leg.get("trade_plan_id") or ""),
                        "leg_id": leg_id,
                        "leg_kind": str(leg.get("kind") or ""),
                        "strategy": str(leg.get("strategy") or ""),
                        "decision_id": f"det_{intent.reservation_request_id}",
                        "direction": side,
                        "lifecycle_action": intent.reason_code,
                        "reduce_only": True,
                        "deterministic_exit": True,
                        "exit_authority": intent.authority,
                        "exit_request_id": intent.reservation_request_id,
                        "state_version": intent.state_version,
                        "instrument_type": instrument_type,
                        "contract_size": contract_size,
                        "contract_multiplier": contract_multiplier,
                        "requested_leverage": str(getattr(plan, "requested_leverage", 1) or 1),
                    },
                )
                await self.audit.log(
                    "DETERMINISTIC_EXIT_INTENT",
                    target=signal.signal_id,
                    run_id=self.run_id,
                    client_order_id=f"{signal.strategy_id}_{signal.signal_id}"[:60],
                    after={**intent.as_dict(), "leg_id": leg_id},
                )
                signals.append((signal, intent.reservation_request_id))
        return signals, wake_required

    async def _strategy_context(self, symbol: str | None = None) -> StrategyContext | None:
        symbol = symbol or (
            getattr(self.strategies[0], "symbol", "BTCUSDT") if self.strategies else "BTCUSDT"
        )
        book = self.market_data.books.get(symbol)
        market_state = None
        get_market_state = getattr(self.adapter, "get_market_state", None)
        try:
            if get_market_state is not None:
                market_state = await get_market_state(symbol)
                if (
                    market_state.health.value != "HEALTHY"
                    or market_state.best_bid <= 0
                    or market_state.best_ask <= 0
                ):
                    raise ValueError("factual market state is not healthy")
                sequence = market_state.generation
                bids = [(market_state.best_bid, Decimal("1"))]
                asks = [(market_state.best_ask, Decimal("1"))]
            else:
                fetched = await self.adapter.get_orderbook(symbol)
                sequence = fetched.sequence
                bids = [(level.price, level.quantity) for level in fetched.bids.values()]
                asks = [(level.price, level.quantity) for level in fetched.asks.values()]
            await self.market_data.ingest_snapshot(
                symbol,
                sequence,
                bids,
                asks,
            )
            book = self.market_data.books[symbol]
            self.health.set("market_data", True)
        except Exception:
            # P0: never let a stale cached orderbook authorize new risk.
            if book is not None:
                book.invalidate()
                self.health.set("market_data", False, f"{symbol} invalidated")
            return None
        account = await self.portfolio.get_account(self.settings.effective_mode())
        positions = await self.portfolio.get_positions()
        return StrategyContext(
            symbol=symbol,
            book=book,
            account=account,
            positions=positions,
            clock_time=self.clock.now(),
            run_id=self.run_id,
            mark_price=market_state.mark_price if market_state else None,
            index_price=market_state.index_price if market_state else None,
            funding=market_state.funding_rate if market_state else None,
            oi=market_state.open_interest if market_state else None,
            basis=market_state.basis if market_state else None,
            realized_volatility=(market_state.realized_volatility if market_state else None),
            instrument=self._instruments.get(symbol),
        )

    # --------------------------------------------------------------- signals
    async def _cancel_unsettled_entry_order(self, entry_order) -> None:
        """Cancel a non-terminal entry order before a later EXIT/REDUCE.

        Uses OrderManager + adapter cancel path. No direct DB mutation and no
        new exit order. If cancellation fails, the runtime stays fail-closed:
        the exception propagates to the caller and the position action is not
        submitted.
        """
        try:
            await self.order_manager.cancel_pending(
                entry_order.internal_order_id,
                reason="POSITION_ACTION_ENTRY_UNSETTLED",
            )
            await self.adapter.cancel_order(entry_order.symbol, entry_order.exchange_order_id)
            await self.audit.log(
                "POSITION_ACTION_CANCEL_ENTRY",
                target=entry_order.client_order_id,
                run_id=self.run_id,
                client_order_id=entry_order.client_order_id,
                order_id=entry_order.internal_order_id,
                after={
                    "status": "CANCEL_PENDING",
                    "reason": "entry order not terminal",
                },
            )
        except Exception:
            logger.exception(
                "POSITION_ACTION_CANCEL_ENTRY_FAILED order_id=%s symbol=%s",
                entry_order.internal_order_id,
                entry_order.symbol,
            )
            raise

    async def process_signal(self, signal: SignalIntent) -> RiskDecision | None:
        run_id = self.run_id
        symbol = signal.symbol
        client_order_id = f"{signal.strategy_id}_{signal.signal_id}"[:60]
        if self.enforce_llm_entry_authority and signal.strategy_id not in {
            "live_llm",
            "live_llm_position",
        }:
            await self.audit.log(
                "NON_LLM_DIRECTIONAL_AUTHORITY_REJECTED",
                target=client_order_id,
                run_id=run_id,
                after={"strategy_id": signal.strategy_id},
            )
            return None
        existing = await self.order_manager.get_by_client(client_order_id)
        if existing is not None:
            await self.audit.log(
                "SIGNAL_IDEMPOTENT_RETRY",
                target=client_order_id,
                run_id=run_id,
                client_order_id=client_order_id,
                order_id=existing.internal_order_id,
            )
            return None

        trade_plan_id = str(signal.metadata.get("trade_plan_id", ""))
        is_entry = signal.strategy_id == "live_llm"
        is_position_action = signal.strategy_id == "live_llm_position"
        hedge_flag = signal.metadata.get("hedge") is True or str(
            signal.metadata.get("lifecycle_action") or ""
        ).upper() in {"HEDGE", "REVERSE"}
        if is_entry and hedge_flag and not self.leg_execution_enabled:
            # The canonical portfolio is currently NET per symbol: executing an
            # opposite leg would silently close the original position while the
            # leg ledger says a new independent leg opened -> accounting
            # divergence / ghost position. Fail closed until leg-level position
            # tracking is the source of truth.
            await self.audit.log(
                "HEDGE_EXECUTION_BLOCKED_NET_MODEL",
                target=client_order_id,
                run_id=run_id,
                client_order_id=client_order_id,
                after={
                    "symbol": signal.symbol,
                    "leg_id": signal.metadata.get("leg_id"),
                    "lifecycle_action": signal.metadata.get("lifecycle_action"),
                    "required": "LEG_LEVEL_POSITION_MODEL",
                },
            )
            return None
        if is_entry and hedge_flag and self.leg_execution_enabled:
            if self.leg_reconciler is None:
                await self.audit.log(
                    "HEDGE_EXECUTION_BLOCKED_NO_RECONCILER",
                    target=client_order_id,
                    run_id=run_id,
                    after={"symbol": signal.symbol},
                )
                return None
            position = await self.portfolio.get_position(signal.symbol)
            reconciliation = await self.leg_reconciler.reconcile(
                signal.symbol, position.quantity if position is not None else Decimal("0")
            )
            if not reconciliation.get("leg_execution_safe"):
                await self.audit.log(
                    "HEDGE_EXECUTION_BLOCKED_LEG_DIVERGENCE",
                    target=client_order_id,
                    run_id=run_id,
                    after={
                        "symbol": signal.symbol,
                        "status": reconciliation.get("status"),
                        "difference": str(reconciliation.get("difference")),
                    },
                )
                return None
        lifecycle_action = str(signal.metadata.get("lifecycle_action") or "").upper()
        if lifecycle_action in {"HEDGE", "REVERSE", "ADD"}:
            target_leg_id = str(signal.metadata.get("leg_id") or "")
            if not target_leg_id:
                await self.audit.log(
                    "LEG_TARGET_REQUIRED",
                    target=client_order_id,
                    run_id=run_id,
                    after={"lifecycle_action": lifecycle_action, "symbol": signal.symbol},
                )
                return None
            if self.leg_service is not None:
                unknowns = await self.leg_service.unresolved_unknowns(target_leg_id)
                if unknowns:
                    await self.audit.log(
                        "LEG_ORDER_UNKNOWN_BLOCKS_REPLACEMENT",
                        target=target_leg_id,
                        run_id=run_id,
                        after={"unknown_orders": unknowns[:5]},
                    )
                    return None
        if (is_entry or is_position_action) and not trade_plan_id:
            await self.audit.log(
                "TRADEPLAN_REQUIRED",
                target=client_order_id,
                run_id=run_id,
                after={"reason": "Live LLM entry has no durable TradePlan"},
            )
            return None
        entry_plan = None
        if is_entry and self.offline_mode.is_offline:
            await self.audit.log(
                "OFFLINE_NEW_RISK_BLOCKED",
                target=client_order_id,
                run_id=run_id,
                client_order_id=client_order_id,
                after={"reason": "LLM_OFFLINE_MODE", "strategy_id": signal.strategy_id},
            )
            return None
        if is_entry:
            plan = await self.trade_plans.get(trade_plan_id)
            entry_plan = plan
            expected_direction = "LONG" if signal.side == OrderSide.BUY else "SHORT"
            valid_plan = (
                plan is not None
                and plan.decision_id == signal.metadata.get("decision_id")
                and plan.symbol == signal.symbol
                and plan.direction == expected_direction
                and plan.state == TradePlanState.PLANNED
            )
            if not valid_plan:
                await self.audit.log(
                    "TRADEPLAN_INVALID",
                    target=client_order_id,
                    run_id=run_id,
                    after={"trade_plan_id": trade_plan_id},
                )
                return None

        positions = await self.portfolio.get_positions()
        if is_position_action:
            plan = await self.trade_plans.get(trade_plan_id)
            position = positions.get(signal.symbol)
            action = signal.metadata.get("lifecycle_action")
            entry_order = (
                await self.order_manager.get(plan.order_id)
                if plan is not None and plan.order_id is not None
                else None
            )
            if entry_order is None or entry_order.status not in TERMINAL_ORDER_STATUSES:
                await self.audit.log(
                    "POSITION_ACTION_BLOCKED_ENTRY_UNSETTLED",
                    target=client_order_id,
                    run_id=run_id,
                    after={
                        "trade_plan_id": trade_plan_id,
                        "order_id": entry_order.internal_order_id
                        if entry_order is not None
                        else None,
                        "entry_order_status": entry_order.status.value
                        if entry_order is not None
                        else None,
                    },
                )
                # P0/P1 lifecycle race: do NOT submit the EXIT/REDUCE while the
                # original entry order is still non-terminal. First cancel the
                # remaining entry quantity through the canonical adapter so the
                # order reaches a factual terminal state. A later review can
                # act on the settled position.
                if entry_order is not None and entry_order.status not in TERMINAL_ORDER_STATUSES:
                    await self._cancel_unsettled_entry_order(entry_order)
                return None
            expected_side = (
                OrderSide.SELL if plan is not None and plan.direction == "LONG" else OrderSide.BUY
            )
            deterministic_authority = signal.metadata.get("exit_authority")
            deterministic_exit = (
                signal.metadata.get("deterministic_exit") is True
                and bool(signal.metadata.get("exit_request_id"))
                and deterministic_authority
                in {
                    "RISK_HARD_EXIT",
                    "OFFLINE_HARD_EXIT",
                    "FAST_PROFIT_PROTECTION",
                    "ACTIVE_BASE_EXIT",
                }
            )
            decision_authorized = (
                plan.latest_position_decision_id == signal.metadata.get("decision_id")
                or deterministic_exit
            )
            valid_reduction = (
                plan is not None
                and plan.symbol == signal.symbol
                and plan.state == TradePlanState.ACTIVE
                and decision_authorized
                and action
                in {
                    "REDUCE",
                    "EXIT",
                    "TIME_STOP_SAFETY_FALLBACK",
                    "BASE_EXIT",
                    "FAST_PROFIT_PROTECTION",
                    "RISK_HARD_EXIT",
                    "OFFLINE_HARD_EXIT",
                }
                and signal.metadata.get("reduce_only") is True
                and position is not None
                and position.quantity != 0
                and signal.side == expected_side
                and signal.quantity <= abs(position.quantity)
                and (
                    (plan.direction == "LONG" and position.quantity > 0)
                    or (plan.direction == "SHORT" and position.quantity < 0)
                )
            )
            if not valid_reduction:
                await self.audit.log(
                    "POSITION_REDUCTION_INVALID",
                    target=client_order_id,
                    run_id=run_id,
                    after={"trade_plan_id": trade_plan_id},
                )
                return None
            if await self.order_manager.has_pending_position_action(trade_plan_id):
                await self.audit.log(
                    "POSITION_ACTION_ALREADY_PENDING",
                    target=client_order_id,
                    run_id=run_id,
                    after={"trade_plan_id": trade_plan_id},
                )
                return None

        # Refresh the factual per-symbol book immediately before authorization.
        # The multi-second LLM review can outlive the freshness windows, and a
        # stale cached book must never authorize new risk (P0). Refresh uses
        # the same real per-symbol OKX source as the review context; a refresh
        # failure leaves the existing book untouched so the execution
        # authority still decides on the real (possibly stale) state.
        get_fresh_market_state = getattr(self.adapter, "get_market_state", None)
        if get_fresh_market_state is not None:
            try:
                refreshed_state = await get_fresh_market_state(symbol)
                if (
                    refreshed_state.health.value == "HEALTHY"
                    and refreshed_state.best_bid > 0
                    and refreshed_state.best_ask > 0
                ):
                    await self.market_data.ingest_snapshot(
                        symbol,
                        refreshed_state.generation,
                        [(refreshed_state.best_bid, Decimal("1"))],
                        [(refreshed_state.best_ask, Decimal("1"))],
                    )
                    self.health.set("market_data", True)
            except Exception:
                self.health.set("market_data", False, f"{symbol} pre-submit refresh failed")

        account = await self.portfolio.get_account(self.settings.effective_mode())
        book = self.market_data.books.get(symbol)
        market_price = D("0")
        if book is not None:
            mid = book.mid_price()
            if mid is not None:
                market_price = mid
        market_prices: dict[str, Decimal] = {}
        for position_symbol in positions:
            position_book = self.market_data.books.get(position_symbol)
            if position_book is None:
                continue
            position_mid = position_book.mid_price()
            if position_mid is not None and position_mid > 0:
                market_prices[position_symbol] = position_mid
        if market_price > 0:
            market_prices[symbol] = market_price
        open_orders = await self.order_manager.count_open()
        risk_decision = self.risk_engine.check(
            signal,
            account=account,
            positions=positions,
            market_price=market_price,
            market_prices=market_prices,
            open_order_count=open_orders,
            consecutive_failures=self.consecutive_failures,
            run_id=run_id,
        )
        await self._persist_risk(risk_decision)
        if trade_plan_id and is_entry:
            await self.trade_plans.link(
                trade_plan_id, risk_decision_id=risk_decision.risk_decision_id
            )
        if risk_decision.decision not in {ExecutionDecision.APPROVE, ExecutionDecision.SCALE_DOWN}:
            if trade_plan_id and is_entry:
                await self.trade_plans.transition(
                    trade_plan_id, TradePlanState.REJECTED, reason=risk_decision.reason
                )
            await self.audit.log(
                "RISK_REJECT",
                target=client_order_id,
                run_id=run_id,
                client_order_id=client_order_id,
                before={"signal": signal.model_dump(mode="json")},
                after={"reason": risk_decision.reason},
            )
            self.health.set("risk", True)
            return risk_decision

        terms = derive_execution_terms(
            is_entry=is_entry,
            signal=signal,
            plan=entry_plan,
            risk_decision=risk_decision,
        )
        approved_metadata = {
            **signal.metadata,
            "risk_decision_id": risk_decision.risk_decision_id,
            "approved_leverage": terms.leverage,
            "risk_observation": terms.risk_observation,
        }
        executable_signal = signal.model_copy(
            update={"metadata": approved_metadata, "quantity": terms.quantity}
        )
        if (
            terms.order_contract is not None
            and risk_decision.decision == ExecutionDecision.SCALE_DOWN
        ):
            await self.audit.log(
                "RISK_OBSERVATION_V2_NO_RESIZE",
                target=client_order_id,
                run_id=run_id,
                client_order_id=client_order_id,
                after=terms.risk_observation,
            )

        instrument = self._instruments.get(symbol)
        lease_held = not self.require_lease
        if self.require_lease and self.lease is not None and self._lease_valid:
            lease_held = await self.lease_manager.is_current(
                self.lease_key,
                self.lease.token,
                self.lease.fence_generation,
                owner_id=self.lease.owner_id,
            )
            self._lease_valid = lease_held
        intent = OrderIntent(
            client_order_id=client_order_id,
            symbol=symbol,
            side=executable_signal.side,
            order_type=executable_signal.order_type,
            time_in_force=executable_signal.time_in_force,
            price=executable_signal.limit_price,
            quantity=executable_signal.quantity,
            strategy_id=executable_signal.strategy_id,
            run_id=run_id,
            expires_at=executable_signal.expires_at,
            metadata={
                **executable_signal.metadata,
                "signal_id": signal.signal_id,
                "trade_plan_id": trade_plan_id or None,
            },
        )
        auth_ctx = AuthorizationContext(
            now=self.clock.now(),
            trading_mode=self.settings.effective_mode(),
            live_enabled=self.settings.live_trading_enabled,
            lease_held=lease_held,
            kill_switch=self.risk_engine.kill_switch,
            order_status=OrderStatus.CREATED,
            expires_at=intent.expires_at,
            market_data_fresh=self.market_data.is_fresh(
                symbol, self.settings.market_data_max_age_seconds
            ),
            orderbook_fresh=self.market_data.is_fresh(
                symbol, self.settings.orderbook_max_age_seconds
            ),
            orderbook_healthy=self.market_data.is_healthy(symbol),
            symbol_tradeable=instrument is not None and instrument.status == "TRADING",
            exchange_connected=self.adapter.connected,
            balance_fresh=self.portfolio is not None,
            risk_decision=risk_decision,
            order_contract=terms.order_contract,
            instrument=instrument,
            duplicate_client_order=existing is not None,
            reconciliation_halted=self.reconciliation_halted,
        )
        decision, notes = await self.authority.authorize(intent, auth_ctx)
        if decision != ExecutionDecision.APPROVE:
            if trade_plan_id and is_entry:
                target_state = (
                    TradePlanState.EXPIRED
                    if "ORDER_EXPIRED" in notes
                    else TradePlanState.INVALIDATED
                )
                await self.trade_plans.transition(
                    trade_plan_id,
                    target_state,
                    reason=notes[0] if notes else "EXECUTION_AUTHORITY_DENIED",
                )
            await self.audit.log(
                f"AUTHORITY_{decision.value}",
                target=client_order_id,
                run_id=run_id,
                client_order_id=client_order_id,
                after={"notes": notes},
            )
            return risk_decision

        # Core order lifecycle: create -> validate -> submit
        order = await self.order_manager.create_from_intent(
            intent, trading_mode=self.settings.effective_mode()
        )
        if trade_plan_id and is_entry:
            await self.trade_plans.link(trade_plan_id, order_id=order.internal_order_id)
            await self.trade_plans.transition(trade_plan_id, TradePlanState.APPROVED)
        await self.order_manager.validate(order.internal_order_id)
        await self.order_manager.submitting(order.internal_order_id)
        await self.order_manager.submitted(order.internal_order_id)
        try:
            exchange_order = await self.adapter.submit_order(order)
        except UnknownExecutionState as exc:
            await self.order_manager.mark_unknown(order.internal_order_id, str(exc))
            await self.audit.log(
                "SUBMIT_TIMEOUT_UNKNOWN",
                target=client_order_id,
                run_id=run_id,
                client_order_id=client_order_id,
                order_id=order.internal_order_id,
                after={"error": str(exc)},
            )
            await self._run_recovery(run_id)
            return risk_decision
        except (TemporaryNetworkError, RateLimited, ExchangeError) as exc:
            await self.order_manager.mark_unknown(order.internal_order_id, str(exc))
            await self.audit.log(
                "SUBMIT_TRANSIENT_FAILURE",
                target=client_order_id,
                run_id=run_id,
                client_order_id=client_order_id,
                order_id=order.internal_order_id,
                after={"error": type(exc).__name__},
            )
            return risk_decision
        except OrderRejected as exc:
            await self.order_manager.reject(
                order.internal_order_id, str(exc), event_id=new_id("evt")
            )
            await self._sync_terminal_entry_plan(
                order, TradePlanState.INVALIDATED, "ORDER_REJECTED"
            )
            await self.audit.log(
                "ORDER_REJECTED",
                target=client_order_id,
                run_id=run_id,
                client_order_id=client_order_id,
                order_id=order.internal_order_id,
                after={"reason": str(exc)},
            )
            return risk_decision

        # The event stream may already have applied ack/open/fills while
        # submit_order was in flight (the simulator emits inline). State
        # synchronization here is therefore best-effort: the event stream is
        # the authoritative applier, and duplicate transitions must not kill
        # the tick after the exchange has already mutated its book.
        try:
            await self.order_manager.ack(
                order.internal_order_id,
                exchange_order.exchange_order_id,
                event_id=new_id("evt"),
            )
            if exchange_order.status == OrderStatus.OPEN:
                await self.order_manager.opened(order.internal_order_id, event_id=new_id("evt"))
            elif exchange_order.status == OrderStatus.CANCELLED:
                await self.order_manager.cancel_confirm(
                    order.internal_order_id, event_id=new_id("evt")
                )
                await self._sync_terminal_entry_plan(
                    order, TradePlanState.CANCELLED, "ORDER_CANCELLED"
                )
            elif exchange_order.status == OrderStatus.REJECTED:
                await self.order_manager.reject(
                    order.internal_order_id,
                    exchange_order.rejection_reason or "rejected on exchange",
                    event_id=new_id("evt"),
                )
                await self._sync_terminal_entry_plan(
                    order, TradePlanState.INVALIDATED, "ORDER_REJECTED"
                )
        except (InvalidStateTransition, IntegrityError) as exc:
            await self.audit.log(
                "ORDER_STATE_SYNC_SKIPPED",
                target=client_order_id,
                run_id=run_id,
                order_id=order.internal_order_id,
                exchange_order_id=exchange_order.exchange_order_id,
                after={"reason": str(exc), "exchange_status": exchange_order.status.value},
            )
        # FILLED/PARTIALLY_FILLED are applied exclusively through the event
        # stream to guarantee fill_id uniqueness; recovery reconciles later.
        await self.audit.log(
            "ORDER_SUBMITTED",
            target=client_order_id,
            run_id=run_id,
            client_order_id=client_order_id,
            order_id=order.internal_order_id,
            exchange_order_id=exchange_order.exchange_order_id,
            before={"status": OrderStatus.SUBMITTED.value},
            after={"status": exchange_order.status.value},
        )
        if order.metadata.get("leg_id") and self.leg_service is not None:
            await self.leg_service.record_leg_order(
                leg_id=str(order.metadata["leg_id"]),
                client_order_id=order.client_order_id,
                side=order.side.value,
                intended_quantity=order.quantity,
                trade_plan_id=order.metadata.get("trade_plan_id"),
                decision_id=order.metadata.get("decision_id"),
                reduce_only=bool(order.metadata.get("reduce_only")),
                source_action=str(order.metadata.get("lifecycle_action") or ""),
                internal_order_id=order.internal_order_id,
            )
        self.health.set("submission", True)
        return risk_decision

    async def _apply_exchange_order_fill(self, local: object, exchange_order: object) -> None:
        if exchange_order.filled_quantity <= local.filled_quantity:
            return
        fill = Fill(
            fill_id=f"submit_{exchange_order.exchange_order_id}_filled",
            trade_id=new_id("trade"),
            order_id=local.internal_order_id,
            client_order_id=local.client_order_id,
            exchange_order_id=exchange_order.exchange_order_id,
            symbol=local.symbol,
            side=local.side,
            price=exchange_order.avg_fill_price or exchange_order.price or Decimal("0"),
            quantity=exchange_order.filled_quantity - local.filled_quantity,
            fee=Decimal("0"),
            timestamp=datetime.now(UTC),
        )
        await self.order_manager.apply_fill(fill)

    async def _persist_risk(self, decision: RiskDecision) -> None:
        async with self.database.session_factory() as session:
            session.add(
                RiskDecisionORM(
                    risk_decision_id=decision.risk_decision_id,
                    order_id=decision.order_id,
                    client_order_id=decision.client_order_id,
                    symbol=decision.symbol,
                    side=decision.side.value,
                    decision=decision.decision.value,
                    reason=decision.reason,
                    checks_json=decision.checks,
                    timestamp=decision.timestamp,
                    run_id=decision.run_id,
                )
            )
            await session.commit()

    # --------------------------------------------------------- exchange events
    async def process_exchange_event(self, event: ExchangeEvent) -> None:
        payload = event.payload or {}
        if event.event_type in (ExchangeEventType.MARKET_DELTA, ExchangeEventType.MARKET_SNAPSHOT):
            await self._process_market_event(event, payload)
            return
        exchange_order_id = payload.get("exchange_order_id")
        if not exchange_order_id:
            return
        local = await self.order_manager.get_by_exchange(str(exchange_order_id))
        if local is None:
            # ack may arrive before submit() returns; order was persisted before submit
            return
        event_id = event.event_id
        if event.event_type == ExchangeEventType.ORDER_ACK:
            await self.order_manager.ack(
                local.internal_order_id, str(exchange_order_id), event_id=event_id
            )
        elif event.event_type == ExchangeEventType.ORDER_OPENED:
            await self.order_manager.opened(local.internal_order_id, event_id=event_id)
        elif event.event_type in (
            ExchangeEventType.ORDER_PARTIALLY_FILLED,
            ExchangeEventType.ORDER_FILLED,
        ):
            fill = self._fill_from_payload(local, payload)
            await self.order_manager.apply_fill(fill)
        elif event.event_type == ExchangeEventType.ORDER_CANCELLED:
            await self.order_manager.cancel_confirm(local.internal_order_id, event_id=event_id)
            await self._sync_terminal_entry_plan(local, TradePlanState.CANCELLED, "ORDER_CANCELLED")
        elif event.event_type == ExchangeEventType.ORDER_REJECTED:
            await self.order_manager.reject(
                local.internal_order_id,
                payload.get("reason", "exchange rejection"),
                event_id=event_id,
            )
            await self._sync_terminal_entry_plan(
                local, TradePlanState.INVALIDATED, "ORDER_REJECTED"
            )
        elif event.event_type == ExchangeEventType.BALANCE_UPDATE:
            await self.portfolio.refresh(initial_balances=self._initial_balances)

    async def _process_market_event(self, event: ExchangeEvent, payload: dict) -> None:
        symbol = event.symbol or payload.get("symbol")
        if not symbol:
            return
        try:
            if event.event_type == ExchangeEventType.MARKET_SNAPSHOT:
                await self.market_data.ingest_snapshot(
                    symbol,
                    int(payload["sequence"]),
                    payload.get("bids", []),
                    payload.get("asks", []),
                )
            else:
                await self.market_data.ingest_delta(
                    symbol,
                    int(payload["sequence"]),
                    payload.get("bids", []),
                    payload.get("asks", []),
                )
            self.health.set("market_data", True)
        except MarketDataUnhealthy:
            self.health.set("market_data", False, f"{symbol} unhealthy")
            await self.audit.log("MARKET_DATA_UNHEALTHY", target=symbol, run_id=self.run_id)

    def _fill_from_payload(self, order, payload: dict) -> Fill:
        return Fill(
            fill_id=str(payload.get("fill_id") or new_id("fill")),
            trade_id=payload.get("trade_id"),
            order_id=order.internal_order_id,
            client_order_id=order.client_order_id,
            exchange_order_id=payload.get("exchange_order_id") or order.exchange_order_id,
            symbol=order.symbol,
            side=order.side,
            price=D(payload.get("fill_price") or order.price or "0"),
            quantity=D(payload.get("fill_quantity") or "0"),
            fee=D(payload.get("fee") or "0"),
            fee_currency=payload.get("fee_currency"),
            timestamp=datetime.now(UTC),
        )

    # ----------------------------------------------------------------- ledger
    async def _settle_fill(self, fill: Fill) -> None:
        order = await self.order_manager.get(fill.order_id)
        if order is None:
            return
        exit_request_id = order.metadata.get("exit_request_id")
        if exit_request_id:
            # Deterministic reduce/close reservation is consumed by the factual fill.
            self.exit_controller.confirm_fill(str(exit_request_id), fill.quantity)
        lineage = lineage_from_order(
            metadata=order.metadata,
            client_order_id=order.client_order_id,
            exchange_order_id=order.exchange_order_id,
            fill_id=fill.fill_id,
        )
        await self.audit.log(
            "FILL_LINEAGE",
            target=fill.fill_id,
            run_id=self.run_id,
            order_id=order.internal_order_id,
            after=validate_lineage(lineage),
        )
        leg_id = order.metadata.get("leg_id")
        if leg_id and self.leg_service is not None:
            # Every leg fill is allocated to exactly one leg and is idempotent
            # by fill_id; duplicate WS/REST delivery cannot double-apply.
            try:
                allocation = await self.leg_service.allocate_fill(
                    fill_id=str(fill.fill_id),
                    leg_id=str(leg_id),
                    side=order.side,
                    price=fill.price,
                    quantity=fill.quantity,
                    fee=getattr(fill, "fee", None),
                    client_order_id=order.client_order_id,
                    order_id=order.internal_order_id,
                    terminal_reason=("EXIT" if order.metadata.get("reduce_only") is True else None),
                )
                await self.audit.log(
                    "LEG_FILL_APPLIED",
                    target=str(leg_id),
                    run_id=self.run_id,
                    order_id=order.internal_order_id,
                    after={
                        "side": order.side.value,
                        "fill_id": str(fill.fill_id),
                        "fill_quantity": str(fill.quantity),
                        "price": str(fill.price),
                        "duplicate": allocation.get("duplicate"),
                        "remaining_quantity": str(allocation.get("remaining_quantity")),
                    },
                )
                if allocation.get("duplicate"):
                    await self.audit.log(
                        "LEG_FILL_DUPLICATE_IGNORED",
                        target=str(leg_id),
                        run_id=self.run_id,
                        after={"fill_id": str(fill.fill_id)},
                    )
            except Exception:
                logger.exception("LEG_FILL_APPLY_FAILED leg_id=%s", leg_id)
        position = await self.portfolio.get_position(fill.symbol)
        if order.metadata.get("instrument_type") == "LINEAR_PERP":
            postings, metadata = build_derivative_trade_entries(
                side=order.side,
                symbol=order.symbol,
                quote_currency=fill.fee_currency or "USDT",
                price=fill.price,
                quantity=fill.quantity,
                fee=fill.fee,
                position_quantity_before=position.quantity if position else Decimal("0"),
                average_entry_price=position.avg_entry_price if position else None,
                contract_size=D(order.metadata.get("contract_size", "1")),
                contract_multiplier=D(order.metadata.get("contract_multiplier", "1")),
                reduce_only=order.metadata.get("reduce_only") is True,
            )
        else:
            cost_released = None
            if order.side == OrderSide.SELL:
                if position is None or position.quantity < fill.quantity:
                    cost_released = (
                        position.avg_entry_price if position else Decimal("0")
                    ) * fill.quantity
                else:
                    cost_released = (position.avg_entry_price or Decimal("0")) * fill.quantity
            postings, metadata = build_trade_entries(
                side=order.side,
                symbol=order.symbol,
                quote_currency=fill.fee_currency or "USDT",
                price=fill.price,
                quantity=fill.quantity,
                fee=fill.fee,
                cost_released=cost_released,
            )
        metadata["base_asset"] = order.symbol.replace("USDT", "")
        metadata["approved_leverage"] = str(order.metadata.get("approved_leverage", "1"))
        await self.ledger.record(
            LedgerEntryType.TRADE,
            postings,
            order_id=order.internal_order_id,
            fill_id=fill.fill_id,
            event_id=new_id("evt"),
            metadata=metadata,
        )
        await self.portfolio.refresh(initial_balances=self._initial_balances)
        # A submitted order is not evidence of an active plan.  Promote only
        # after this factual fill has been projected into a non-zero position.
        trade_plan_id = str(order.metadata.get("trade_plan_id") or "")
        plan = (
            await self.trade_plans.get(trade_plan_id)
            if trade_plan_id
            else await self.trade_plans.get_by_order(order.internal_order_id)
        )
        position = await self.portfolio.get_position(fill.symbol)
        if plan is not None and plan.state == TradePlanState.APPROVED and position is not None:
            expected_sign = 1 if plan.direction == "LONG" else -1
            if position.quantity * expected_sign > 0:
                await self.trade_plans.transition(plan.trade_plan_id, TradePlanState.ACTIVE)
        elif (
            plan is not None
            and plan.state == TradePlanState.ACTIVE
            and order.metadata.get("reduce_only") is True
            and (position is None or position.quantity == 0)
        ):
            exit_decision_id = str(order.metadata.get("decision_id") or "")
            if not exit_decision_id:
                self.health.set("trade_episode", False, "close lacks exit decision lineage")
                await self.audit.log(
                    "TRADEPLAN_CLOSE_LINEAGE_MISSING",
                    target=plan.trade_plan_id,
                    run_id=self.run_id,
                    order_id=order.internal_order_id,
                )
            else:
                closed_plan = await self.trade_plans.close_from_factual_position(
                    plan.trade_plan_id,
                    exit_decision_id=exit_decision_id,
                    reason=str(order.metadata.get("lifecycle_action") or "POSITION_CLOSED"),
                )
                episode = await self.trade_episodes.build_for_closed_plan(closed_plan.trade_plan_id)
                if episode is None:
                    self.health.set(
                        "trade_episode", False, "closed lifecycle lacks factual lineage"
                    )
                    await self.audit.log(
                        "TRADE_EPISODE_INCOMPLETE",
                        target=closed_plan.trade_plan_id,
                        run_id=self.run_id,
                        order_id=order.internal_order_id,
                    )
                else:
                    self.health.set("trade_episode", True)
                    await self.audit.log(
                        "TRADE_EPISODE_CREATED",
                        target=episode.episode_id,
                        run_id=self.run_id,
                        order_id=order.internal_order_id,
                        after={"trade_plan_id": closed_plan.trade_plan_id},
                    )
        await self.audit.log(
            "FILL_SETTLED",
            target=fill.fill_id,
            run_id=self.run_id,
            order_id=order.internal_order_id,
            client_order_id=order.client_order_id,
            exchange_order_id=order.exchange_order_id,
            before={"fill_quantity": str(fill.quantity), "fill_price": str(fill.price)},
            after={"transaction_id": fill.fill_id},
        )

    async def _sync_terminal_entry_plan(self, order, state: TradePlanState, reason: str) -> None:
        if order.strategy_id != "live_llm":
            return
        plan = await self.trade_plans.get_by_order(order.internal_order_id)
        if plan is None or plan.state not in {
            TradePlanState.PLANNED,
            TradePlanState.APPROVED,
        }:
            return
        await self.trade_plans.transition(plan.trade_plan_id, state, reason=reason)

    async def _sync_terminal_entry_plans(self) -> None:
        terminal_states = {
            OrderStatus.CANCELLED: (TradePlanState.CANCELLED, "ORDER_CANCELLED"),
            OrderStatus.EXPIRED: (TradePlanState.EXPIRED, "ORDER_EXPIRED"),
            OrderStatus.REJECTED: (TradePlanState.INVALIDATED, "ORDER_REJECTED"),
        }
        for order in await self.order_manager.list_all():
            target = terminal_states.get(order.status)
            if target is not None:
                await self._sync_terminal_entry_plan(order, *target)

    async def _seed_initial_balances(self) -> None:
        async with self.database.session_factory() as session:
            snap = await replay_projections(session)
            if snap.balances:
                self._initial_balances = {c: row["total"] for c, row in snap.balances.items()}
                return
        self._initial_balances = {}
        if self.settings.effective_mode() == TradingMode.PAPER:
            balances = await self.adapter.get_balances()
            self._initial_balances = {b.currency: b.total for b in balances}
            for balance in balances:
                await self.ledger.record(
                    LedgerEntryType.DEPOSIT,
                    [
                        LedgerPosting(
                            "CASH", LedgerDirection.DEBIT, balance.total, balance.currency
                        ),
                        LedgerPosting(
                            "EQUITY", LedgerDirection.CREDIT, balance.total, balance.currency
                        ),
                    ],
                    metadata={"amount": str(balance.total), "currency": balance.currency},
                )
            await self.portfolio.refresh(initial_balances=self._initial_balances)

    async def _load_instruments(self) -> None:
        try:
            instruments = await self.adapter.get_exchange_info()
            self._instruments = {i.symbol: i for i in instruments}
        except Exception:
            self._instruments = {}

    async def _restore_paper_adapter_state(self) -> None:
        """Restore the process-local PAPER simulator from durable projections."""

        restore = getattr(self.adapter, "restore_from_canonical_state", None)
        if restore is None or self.settings.effective_mode() != TradingMode.PAPER:
            return
        account = await self.portfolio.get_account(self.settings.effective_mode())
        positions = await self.portfolio.get_positions()
        await restore(
            balances={currency: balance.total for currency, balance in account.balances.items()},
            positions=positions,
        )
        self.health.set("paper_restart_recovery", True)

    # ---------------------------------------------------------------- helpers
    def kill_switch_snapshot(self) -> dict:
        return self.risk_engine.kill_switch.snapshot()

    def runtime_snapshot(self) -> dict:
        lease = self.lease
        return {
            "run_id": self.run_id,
            "state": self.state_machine.state.value,
            "mode": self.settings.effective_mode().value,
            "lease_held": self._lease_valid,
            "execution_lease": {
                "required": self.require_lease,
                "held": self._lease_valid,
                "lease_key": self.lease_key if self.require_lease else None,
                "owner_id": lease.owner_id if lease is not None else None,
                "fence_generation": (lease.fence_generation if lease is not None else None),
                "single_writer": self._lease_valid if self.require_lease else True,
            },
            "reconciliation_halted": self.reconciliation_halted,
            "health": self.health.snapshot(),
            "kill_switch": self.kill_switch_snapshot(),
            # Low-Risk V2 soak observability: provider latency percentiles,
            # failover/offline windows and the engine's offline guard state.
            "llm_router": self._llm_router_diagnostics(),
            "llm_offline_mode": self.offline_mode.snapshot(),
        }

    def _llm_router_diagnostics(self) -> dict | None:
        router = self.llm_router
        if router is None:
            return None
        diagnostics = getattr(router, "diagnostics", None)
        if not callable(diagnostics):
            return None
        try:
            return diagnostics()
        except Exception:
            return {"error": "DIAGNOSTICS_UNAVAILABLE"}

    async def wait_for_event_queue(self) -> None:
        await self._event_queue.join()
