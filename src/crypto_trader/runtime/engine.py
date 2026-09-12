"""TradingEngine: the only orchestration path from market event to audit.

Market Event -> StrategyPlugin -> SignalIntent -> PreTrade Risk
-> ExecutionAuthority -> OrderManager -> ExchangeAdapter -> Exchange Events
-> Order State Machine -> Ledger -> Portfolio Projection -> Audit
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
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
from crypto_trader.governance.scheduler import DailyReviewScheduler
from crypto_trader.governance.trade_episode import TradeEpisodeStore
from crypto_trader.ledger.projections import replay_projections
from crypto_trader.ledger.service import (
    FundingScope,
    LedgerPosting,
    LedgerService,
    build_derivative_trade_entries,
    build_trade_entries,
)
from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.observability.audit import AuditService
from crypto_trader.order.manager import (
    POSITION_ACTION_STALE,
    OrderManager,
)
from crypto_trader.perpetual.funding_coverage import FundingCoverageService
from crypto_trader.persistence.database import Database
from crypto_trader.persistence.models import EngineRunORM, RiskDecisionORM
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.reconciliation.service import ReconciliationService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.event_bus import EventBus
from crypto_trader.runtime.health import HealthRegistry
from crypto_trader.runtime.lease import Lease, LeaseManager
from crypto_trader.runtime.recovery import RecoveryService
from crypto_trader.runtime.state_machine import RuntimeStateMachine
from crypto_trader.strategy.base import StrategyContext, StrategyPlugin
from crypto_trader.trade_plan.service import TradePlanService, TradePlanState
from crypto_trader.valuation.domain import (
    VALUATION_QUALITY_HEALTHY,
    ValuationBatch,
)
from crypto_trader.valuation.service import ValuationService

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
        funding_coverage: FundingCoverageService | None = None,
        valuation_service: ValuationService | None = None,
        funding_supervisor=None,
        evidence_router=None,
        market_intelligence=None,
        market_selection_service=None,
        market_selection_interval_seconds: float = 30.0,
    ) -> None:
        self.settings = settings
        # Market-Intelligence observability sink (counters only, no authority).
        self.market_intelligence = market_intelligence
        # ChiefTrader active market selection runs as its OWN independent loop
        # so slow scans / slow selection / slow research can never block
        # position review (§3.4 priority order).
        self.market_selection_service = market_selection_service
        self.market_selection_interval_seconds = float(market_selection_interval_seconds)
        self.database = database
        self.adapter = adapter
        self.order_manager = order_manager
        self.ledger = ledger
        self.portfolio = portfolio
        self.funding_coverage = funding_coverage or FundingCoverageService(
            database.session_factory
        )
        self.valuations = valuation_service or ValuationService(
            portfolio=portfolio, ledger=ledger
        )
        self.funding_supervisor = funding_supervisor
        self.evidence_router = evidence_router
        # Candidate valuation batches are computed for strategy context
        # (Sizing) and persisted only when a factual signal reaches Risk, so
        # Sizing and Risk reference the exact same valuation_id.
        self._pending_valuations: dict[str, ValuationBatch] = {}
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
        self.position_review_timeout_seconds = 30.0
        self.position_review_interval_seconds = max(
            0.5, min(30.0, float(settings.engine_tick_seconds))
        )
        # Ceiling on position-review REPEAT RATE for an unchanged position.
        #
        # The safety cadence above still applies: a material change (fill, size,
        # price move, order state) re-arms a review immediately, and PnL
        # deterioration keeps its 5s cadence. What this floor removes is the
        # blind "nothing changed, ask the LLM again" storm that saturated the
        # rolling budget and starved active-position management.
        self.position_review_min_interval_seconds = float(
            settings.position_review_min_interval_seconds
        )
        self._position_review_state: dict[str, dict] = {}

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
        await RecoveryService(self.order_manager, self.adapter, self.audit).recover(self.run_id)
        await self._sync_terminal_entry_plans()
        self.health.set("recovery", True)
        # Daily review recovery is not an execution mutation and must not
        # consume the execution lease lifetime.
        await self._recover_missed_daily_reviews()

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
        await self._ensure_orphan_recovery_plans()

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
        if self.evidence_router is not None:
            self._tasks.append(asyncio.create_task(
                self.evidence_router.run_forever(), name="closed-candle-evidence"
            ))
        if self.position_manager is not None:
            self._tasks.append(asyncio.create_task(
                self._position_loop(), name="llm-position-reviews"
            ))
        if self.require_lease:
            self._tasks.append(asyncio.create_task(self._lease_loop(), name="engine-lease"))
        if self.funding_supervisor is not None:
            # Formal public funding history -> coverage -> PAPER settlement
            # -> ledger chain. Runs under the execution lease; ledger
            # idempotency makes a restart/retry a no-op.
            self._tasks.append(
                asyncio.create_task(self._funding_loop(), name="funding-accounting")
            )
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
        if self.market_selection_service is not None:
            # ChiefTrader research-attention selection: its own task, its own
            # cooldown/duplicate guards, zero directional authority.
            self._tasks.append(
                asyncio.create_task(
                    self._market_selection_loop(), name="market-selection"
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

    async def _ensure_orphan_recovery_plans(self) -> list[str]:
        """Create explicit RECOVERY plans for factual positions without one.

        This does not create fills or orders and never bypasses the normal
        reduce-only signal -> Risk -> ExecutionAuthority -> OrderManager path.
        """
        if not hasattr(self.adapter, "get_positions"):
            return []
        try:
            positions = await self.adapter.get_positions()
        except Exception as exc:
            await self.audit.log(
                "ORPHAN_RECOVERY_SCAN_FAILED",
                target=self.run_id or "unknown",
                run_id=self.run_id,
                after={"error_type": type(exc).__name__},
            )
            return []
        created: list[str] = []
        for position in positions:
            if position.quantity == 0:
                continue
            active = await self.trade_plans.get_active_for_symbol(position.symbol)
            if active is not None:
                continue
            plan = await self.trade_plans.ensure_recovery_plan(
                symbol=position.symbol,
                direction="LONG" if position.quantity > 0 else "SHORT",
                quantity=abs(position.quantity),
                entry_price=getattr(position, "avg_entry_price", None),
            )
            created.append(plan.trade_plan_id)
            await self.audit.log(
                "ORPHAN_POSITION_RECOVERY_PLANNED",
                target=position.symbol,
                run_id=self.run_id,
                after={
                    "trade_plan_id": plan.trade_plan_id,
                    "state": plan.state.value,
                    "quantity": str(abs(position.quantity)),
                },
            )
        return created

    async def _reconcile_stale_runs(self) -> list[str]:
        """Close abandoned rows only after this process owns the fenced lease."""

        if self.lease is None or not self._lease_valid:
            return []
        async with self.database.session_factory() as session:
            rows = (
                await session.execute(
                    select(EngineRunORM).where(
                        EngineRunORM.run_id != self.run_id,
                        EngineRunORM.ended_at.is_(None),
                    )
                )
            ).scalars().all()
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
                await self.tick(include_position_reviews=False)
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

    async def _position_loop(self) -> None:
        """Review positions on deadline; never sleep a drifted fixed period."""
        while True:
            try:
                await self._review_positions_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.health.set("position_manager", False, type(exc).__name__)
            now_epoch = self.clock.now().timestamp()
            due_times = [
                state.get("next_due_at", now_epoch + self.position_review_interval_seconds)
                for state in self._position_review_state.values()
            ]
            next_due = (
                min(due_times)
                if due_times
                else now_epoch + self.position_review_interval_seconds
            )
            sleep_for = max(
                0.05,
                min(next_due - now_epoch, self.position_review_interval_seconds),
            )
            await asyncio.sleep(sleep_for)

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

    async def _market_selection_loop(self) -> None:
        """Independent selection loop (§14).

        Observes the latest immutable snapshot, honours cooldown / duplicate /
        freshness guards, and never raises into the runtime: any failure
        degrades to a recorded selection status while positions keep running.
        """
        while True:
            try:
                positions = await self.portfolio.get_positions()
                symbols = [
                    symbol
                    for symbol, position in positions.items()
                    if Decimal(str(position.quantity)) != 0
                ]
                await self.market_selection_service.maybe_select(
                    existing_positions=symbols
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("market selection loop iteration failed", exc_info=True)
            await asyncio.sleep(max(1.0, self.market_selection_interval_seconds))

    async def _funding_loop(self) -> None:
        while True:
            try:
                report = await self.funding_supervisor.run_once()
                ok = not report.errors
                detail = "; ".join(report.errors[:3]) if report.errors else ""
                self.health.set("funding_accounting", ok, detail)
                if report.settled > 0 and ok:
                    # The settlement is now COMMITTED to the durable ledger,
                    # which is the authoritative cash truth; the process-local
                    # PAPER cache has not seen it. Post-commit ordering: re-read
                    # the committed projection and COPY it (no independent
                    # arithmetic), so a retry cannot double-apply it.
                    await self._resync_paper_balance_from_projection()
            except Exception as exc:
                # A failed resync must NOT roll back the committed funding fact;
                # reconciliation stays fail-closed and the next pass retries.
                self.health.set("funding_accounting", False, type(exc).__name__)
            await asyncio.sleep(max(1, self.settings.funding_refresh_interval_seconds))

    async def _resync_paper_balance_from_projection(self) -> None:
        """Refresh the PAPER account cache from committed ledger projections.

        Narrow by design: only the account balance is adopted. Orders, positions
        and execution state keep their own lifecycle, so a pending partial order
        cannot be rewound, duplicated or marked terminal here.
        """
        sync = getattr(self.adapter, "sync_balances_from_projection", None)
        if sync is None:
            return
        async with self.database.session_factory() as session:
            snapshot = await replay_projections(session)
        if not snapshot.balances:
            return
        balances = {currency: row["total"] for currency, row in snapshot.balances.items()}
        sync(balances)
        self._initial_balances = balances

    async def _reconciliation_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.reconciliation_interval_seconds)
            report = await self.reconciliation.reconcile(self.adapter)
            self.reconciliation_halted = report.halt
            self.health.set("reconciliation", not report.halt, "; ".join(report.alerts[:3]))

    # ------------------------------------------------------------------ tick
    async def tick(self, *, include_position_reviews: bool = True) -> list[RiskDecision]:
        decisions: list[RiskDecision] = []
        for strategy in self.strategies:
            # Scheduling authority (MASTER DIRECTIVE / Market Intelligence V1):
            # a strategy that implements desired_symbol() owns its own
            # new-research attention. ``None`` means "no new autonomous research
            # this tick" and MUST NOT be turned into a default-symbol review; a
            # scheduler failure fails closed for that strategy's new-entry path.
            desired_getter = getattr(strategy, "desired_symbol", None)
            if callable(desired_getter):
                try:
                    desired_symbol = desired_getter()
                except Exception as exc:
                    self.health.set(
                        f"strategy:{strategy.name}",
                        False,
                        f"DESIRED_SYMBOL_FAILED:{type(exc).__name__}",
                    )
                    continue
                if desired_symbol is None:
                    # explicit NO_RESEARCH / no-new-entry signal: skip this
                    # strategy for this tick (existing positions are reviewed
                    # independently below and are unaffected).
                    continue
                ctx = await self._strategy_context(desired_symbol)
            else:
                # legacy strategy without a scheduler keeps its previous
                # default-symbol context behavior
                ctx = await self._strategy_context()
            if ctx is None:
                continue
            try:
                signals = await strategy.on_market_data(ctx)
            except Exception as exc:
                self.consecutive_failures += 1
                self.health.set(
                    f"strategy:{strategy.name}", False, type(exc).__name__
                )
                continue
            self.consecutive_failures = 0
            self.health.set(f"strategy:{strategy.name}", True)
            for signal in signals:
                decision = await self.process_signal(signal)
                if decision is not None:
                    decisions.append(decision)
        if include_position_reviews:
            decisions.extend(await self._review_positions_once())
        self.health.set("engine_loop", True)
        return decisions

    async def _position_change_signature(self, symbol: str, position) -> tuple:
        """Factual state a position review may legitimately need to react to.

        Built from observed facts only — position size / entry / leverage /
        realised PnL, the live book, and the lifecycle state of the entry order
        — so "materially unchanged" is a factual statement rather than a
        heuristic guess. Order-state changes are explicit material events: an
        entry order becoming terminal is exactly what unblocks a pending
        REDUCE/EXIT, so it must re-arm a review immediately.
        """
        book = self.market_data.books.get(symbol)
        bid = book.best_bid() if book is not None else None
        ask = book.best_ask() if book is not None else None
        plan_state = None
        entry_order_status = None
        plan = (
            await self.trade_plans.get_active_for_symbol(symbol)
            if self.trade_plans is not None
            else None
        )
        if plan is not None:
            plan_state = str(getattr(plan, "state", None))
            order_id = getattr(plan, "order_id", None)
            if order_id:
                entry_order = await self.order_manager.get(order_id)
                if entry_order is not None:
                    entry_order_status = str(entry_order.status.value)
        return (
            str(getattr(position, "quantity", None)),
            str(getattr(position, "avg_entry_price", None)),
            str(getattr(position, "cost_basis", None)),
            str(getattr(position, "leverage", None)),
            str(getattr(position, "realized_pnl", None)),
            str(bid.price if bid else None),
            str(ask.price if ask else None),
            plan_state,
            entry_order_status,
        )

    async def _is_due_for_review(
        self, symbol: str, position, state: dict, now_epoch: float
    ) -> bool:
        """Due AND worth an LLM call.

        A material change re-arms the review immediately. Otherwise the review
        is coalesced to ``position_review_min_interval_seconds`` so an unchanged
        position cannot burn budget in a blind polling loop.
        """
        if state["next_due_at"] > now_epoch:
            return False
        signature = await self._position_change_signature(symbol, position)
        last_signature = state.get("last_review_signature")
        last_started = state.get("last_started_at")
        if signature != last_signature:
            return True
        if last_started is None:
            return True
        unchanged_for = now_epoch - float(last_started)
        return unchanged_for >= self.position_review_min_interval_seconds

    async def _review_positions_once(self) -> list[RiskDecision]:
        if self.position_manager is None:
            return []
        now_wall = self.clock.now()
        now_epoch = now_wall.timestamp()
        positions = await self.portfolio.get_positions()
        due = []
        for symbol, position in positions.items():
            if position.quantity == 0:
                continue
            state = self._position_review_state.setdefault(
                symbol,
                {"next_due_at": 0.0, "failures": 0, "last_started_at": None},
            )
            if await self._is_due_for_review(symbol, position, state, now_epoch):
                score = await self._position_review_priority(
                    position, state, now_wall, now_epoch
                )
                due.append((score, symbol, position))
        if not due:
            return []
        due.sort(key=lambda row: row[0], reverse=True)

        semaphore = asyncio.Semaphore(4)

        async def review_one(_, symbol, position):
            async with semaphore:
                state = self._position_review_state[symbol]
                state["last_started_at"] = now_epoch
                try:
                    signal = await asyncio.wait_for(
                        self._review_one_position(symbol, position, now_wall),
                        timeout=max(0.05, self.position_review_timeout_seconds),
                    )
                except TimeoutError:
                    state["failures"] = state.get("failures", 0) + 1
                    state["next_due_at"] = (
                        self.clock.now().timestamp() + self._review_backoff(state)
                    )
                    self.health.set("position_manager", False, "POSITION_REVIEW_TIMEOUT")
                    await self.audit.log(
                        "POSITION_REVIEW_TIMEOUT",
                        target=symbol,
                        run_id=self.run_id,
                        after={"timeout_seconds": self.position_review_timeout_seconds},
                    )
                    return None
                except Exception as exc:
                    state["failures"] = state.get("failures", 0) + 1
                    state["next_due_at"] = (
                        self.clock.now().timestamp() + self._review_backoff(state)
                    )
                    self.consecutive_failures += 1
                    self.health.set(
                        "position_manager", False, type(exc).__name__
                    )
                    return None
                state["failures"] = 0
                state["next_due_at"] = self.clock.now().timestamp() + self._next_review_delay(
                    position, now_wall
                )
                self.health.set("position_manager", True)
                # Remember WHAT was reviewed so an unchanged position can be
                # coalesced instead of re-asked every tick.
                state["last_review_signature"] = (
                    await self._position_change_signature(symbol, position)
                )
                return signal

        reviewed = await asyncio.gather(
            *(review_one(score, symbol, position) for score, symbol, position in due)
        )
        return [decision for decision in reviewed if decision is not None]

    async def _review_one_position(
        self, symbol: str, position, now_wall: datetime
    ) -> RiskDecision | None:
        ctx = await self._strategy_context(symbol)
        if ctx is None:
            return None
        signal = await self.position_manager.review(ctx, position)
        if signal is None:
            return None
        return await self.process_signal(signal)

    async def _position_review_priority(
        self, position, state: dict, now_wall: datetime, now_epoch: float
    ) -> tuple[int, float]:
        overdue = max(0.0, now_epoch - state.get("next_due_at", 0.0))
        hold_bonus = 0.0
        risk_bonus = 0.0
        try:
            plan = await self.trade_plans.get_active_for_symbol(position.symbol)
        except Exception:
            plan = None
        if plan is not None and plan.opened_at is not None:
            opened_at = plan.opened_at
            if opened_at.tzinfo is None:
                opened_at = opened_at.replace(tzinfo=UTC)
            elapsed = max(0.0, (now_wall - opened_at).total_seconds())
            remaining = float(plan.max_holding_time_seconds) - elapsed
            if remaining <= 600:
                hold_bonus = 10000.0 - max(0.0, remaining)
        entry = getattr(position, "avg_entry_price", None)
        unrealized = getattr(position, "unrealized_pnl", Decimal("0")) or Decimal("0")
        if entry and entry > 0:
            spec = (
                getattr(position, "contract_size", Decimal("1"))
                * getattr(position, "contract_multiplier", Decimal("1"))
            )
            notional = abs(position.quantity) * entry * spec
            if notional > 0 and unrealized < 0:
                risk_bonus = float(abs(unrealized) / notional) * 1000.0
        return (1 if overdue > 0 else 0, overdue + hold_bonus + risk_bonus)

    def _review_backoff(self, state: dict) -> float:
        failures = max(1, int(state.get("failures", 0)))
        return min(
            self.position_review_interval_seconds,
            0.5 * (2 ** (failures - 1)),
        )

    def _next_review_delay(self, position, now_wall: datetime) -> float:
        base = self.position_review_interval_seconds
        # Deteriorating PnL and near-time-stop positions get a shorter cadence.
        entry = getattr(position, "avg_entry_price", None)
        unrealized = getattr(position, "unrealized_pnl", Decimal("0")) or Decimal("0")
        if entry and entry > 0 and unrealized < 0:
            base = min(base, 5.0)
        return base

    def _remember_pending_valuation(self, batch: ValuationBatch) -> None:
        self._pending_valuations[batch.valuation_id] = batch
        while len(self._pending_valuations) > 64:
            oldest = next(iter(self._pending_valuations))
            self._pending_valuations.pop(oldest, None)

    async def _collect_refreshed_valuation_inputs(
        self, positions: dict[str, object], *, symbol: str | None = None
    ) -> tuple[dict[str, Decimal], dict[str, datetime | None], list[str]]:
        """P2: refresh all required marks, then build an immutable fresh map.

        Refresh happens first and the map is read only after every required
        same-symbol refresh. The old pre-refresh map is never reused, so a
        refreshed timestamp can never be paired with a stale price.
        """
        required = sorted(
            {
                position_symbol
                for position_symbol, position in positions.items()
                if position.quantity != 0
            }
            | ({symbol} if symbol and symbol in positions else set())
        )
        reasons: list[str] = []
        for position_symbol in required:
            if not self.market_data.is_fresh(
                position_symbol, self.settings.orderbook_max_age_seconds
            ):
                refreshed = False
                try:
                    refreshed = await self._refresh_execution_market(position_symbol)
                except Exception:
                    refreshed = False
                if not refreshed:
                    reasons.append(f"MARK_REFRESH_FAILED:{position_symbol}")
        prices: dict[str, Decimal] = {}
        mark_timestamps: dict[str, datetime | None] = {}
        for position_symbol in required:
            book = self.market_data.books.get(position_symbol)
            if book is None or not self.market_data.is_healthy(position_symbol):
                reasons.append(f"MARK_BOOK_UNHEALTHY:{position_symbol}")
                continue
            mid = book.mid_price()
            if mid is None or mid <= 0:
                reasons.append(f"MARK_INVALID:{position_symbol}")
                continue
            prices[position_symbol] = mid
            mark_timestamps[position_symbol] = book.updated_at
        return prices, mark_timestamps, reasons

    def _prices_from_batch(
        self, batch: ValuationBatch, *, symbol: str | None, market_price: Decimal
    ) -> dict[str, Decimal]:
        """Risk exposure uses the exact marks recorded in the shared batch."""
        prices: dict[str, Decimal] = {}
        for component in batch.components:
            instrument_id = component.get("instrument_id")
            mark = component.get("mark_price")
            if instrument_id and mark:
                prices[str(instrument_id)] = D(mark)
        if symbol is not None and market_price > 0:
            prices[symbol] = market_price
        return prices

    async def _build_valuation_candidate(
        self,
        *,
        account,
        positions: dict[str, object],
        symbol: str | None = None,
    ) -> ValuationBatch:
        """Compute one candidate batch from fully refreshed immutable marks."""
        prices, mark_timestamps, refresh_reasons = (
            await self._collect_refreshed_valuation_inputs(positions, symbol=symbol)
        )
        market_as_of = max(
            (
                timestamp
                for timestamp in mark_timestamps.values()
                if isinstance(timestamp, datetime)
            ),
            default=None,
        )
        batch = await self.valuations.build(
            account=account,
            positions=positions,
            market_prices=prices,
            instruments=self._instruments,
            is_fresh=lambda symbol_key: self.market_data.is_fresh(
                symbol_key, self.settings.orderbook_max_age_seconds
            ),
            require_mark_healthy=self.market_data.is_healthy,
            mark_timestamps=mark_timestamps,
            allowed_future_skew_seconds=0,
            market_as_of=market_as_of,
            reason_codes=refresh_reasons,
        )
        self._remember_pending_valuation(batch)
        return batch

    async def _resolve_signal_valuation(
        self, signal: SignalIntent, *, account, positions: dict[str, object]
    ) -> ValuationBatch:
        """Return the exact batch Sizing used, persisted as the factual fact."""
        valuation_id = str(signal.metadata.get("valuation_id") or "")
        if valuation_id:
            candidate = self._pending_valuations.pop(valuation_id, None)
            if candidate is not None:
                return await self.valuations.persist(
                    candidate, fallback_equity=account.equity
                )
            existing = await self.valuations.get(valuation_id)
            if existing is not None:
                return existing
        candidate = await self._build_valuation_candidate(
            account=account, positions=positions, symbol=signal.symbol
        )
        return await self.valuations.persist(candidate, fallback_equity=account.equity)

    async def _strategy_context(self, symbol: str | None = None) -> StrategyContext | None:
        symbol = symbol or (
            getattr(self.strategies[0], "symbol", "BTCUSDT")
            if self.strategies
            else "BTCUSDT"
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
                bid_size = getattr(market_state, "best_bid_size", Decimal("0")) or Decimal("0")
                ask_size = getattr(market_state, "best_ask_size", Decimal("0")) or Decimal("0")
                if bid_size <= 0 or ask_size <= 0:
                    raise ValueError("factual market depth is unavailable")
                sequence = market_state.generation
                bids = [(market_state.best_bid, bid_size)]
                asks = [(market_state.best_ask, ask_size)]
            else:
                fetched = await self.adapter.get_orderbook(symbol)
                sequence = fetched.sequence
                bids = [
                    (level.price, level.quantity) for level in fetched.bids.values()
                ]
                asks = [
                    (level.price, level.quantity) for level in fetched.asks.values()
                ]
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
        valuation = await self._build_valuation_candidate(
            account=account, positions=positions, symbol=symbol
        )
        return StrategyContext(
            symbol=symbol,
            book=book,
            account=account,
            positions=positions,
            clock_time=self.clock.now(),
            market_timestamp=(
                market_state.exchange_timestamp or market_state.timestamp
                if market_state else book.updated_at
            ),
            run_id=self.run_id,
            mark_price=market_state.mark_price if market_state else None,
            index_price=market_state.index_price if market_state else None,
            funding=market_state.funding_rate if market_state else None,
            oi=market_state.open_interest if market_state else None,
            basis=market_state.basis if market_state else None,
            realized_volatility=(
                market_state.realized_volatility if market_state else None
            ),
            instrument=self._instruments.get(symbol),
            valuation=valuation,
        )

    async def _refresh_execution_market(self, symbol: str) -> bool:
        """Refresh the same-symbol market book immediately before Risk/Execution.

        A long LLM decision can make the book captured before the decision
        stale. Re-fetching from the factual adapter prevents AUTHORITY_HOLD
        caused by MARKET_DATA_STALE when current data is actually available.
        """
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
                bid_size = getattr(market_state, "best_bid_size", Decimal("0")) or Decimal("0")
                ask_size = getattr(market_state, "best_ask_size", Decimal("0")) or Decimal("0")
                if bid_size <= 0 or ask_size <= 0:
                    raise ValueError("factual market depth is unavailable")
                bids = [(market_state.best_bid, bid_size)]
                asks = [(market_state.best_ask, ask_size)]
                await self.market_data.ingest_snapshot(
                    symbol,
                    market_state.generation,
                    bids,
                    asks,
                )
                self.health.set("market_data", True)
                return True
            fetched = await self.adapter.get_orderbook(symbol)
            await self.market_data.ingest_snapshot(
                symbol,
                fetched.sequence,
                [(level.price, level.quantity) for level in fetched.bids.values()],
                [(level.price, level.quantity) for level in fetched.asks.values()],
            )
            self.health.set("market_data", True)
            return True
        except Exception:
            self.health.set("market_data", False, f"{symbol} refresh failed")
            return False

    # --------------------------------------------------------------- signals
    async def _current_lease_valid(self) -> bool:
        """Return whether the current runtime still owns the execution lease."""
        if not self.require_lease:
            return True
        if self.lease is None or self.lease_manager is None:
            return False
        valid = await self.lease_manager.is_current(
            self.lease_key,
            self.lease.token,
            self.lease.fence_generation,
            owner_id=self.lease.owner_id,
        )
        self._lease_valid = valid
        return valid


    async def _recover_missed_daily_reviews(self) -> None:
        scheduler = self.daily_review_scheduler
        if scheduler is None:
            return
        latest = await scheduler.persistence.latest_succeeded_review_date()
        if latest is not None:
            start = datetime.strptime(latest, "%Y-%m-%d").date() + timedelta(days=1)
        else:
            earliest = await scheduler.episodes.earliest_factual_closed_date()
            if earliest is None:
                # No factual history: do not invent dates.
                return
            start = datetime.strptime(earliest, "%Y-%m-%d").date()
        end = (datetime.now(UTC) - timedelta(days=1)).date()
        if start > end:
            return
        results = await scheduler.run_missed_days(start.isoformat(), end.isoformat())
        await self.audit.log(
            "DAILY_REVIEW_BACKFILL",
            target=self.run_id,
            run_id=self.run_id,
            after={
                "from": start.isoformat(),
                "to": end.isoformat(),
                "results": results,
            },
        )


    async def _position_management_capacity_available(self) -> bool:
        """Resource-readiness gate for admitting one more position.

        NOT direction authority: this never chooses or rewrites a direction; it
        only answers whether the position-management capacity a new position
        would consume is actually guaranteed. ChiefTrader stays the sole LONG /
        SHORT authority and this gate can only ever make an entry wait.

        Fail closed: if capacity cannot be computed, no new position is admitted.
        A safe result of "zero new positions" is acceptable — trading frequency
        must never be bought with unmanageable positions.
        """
        probe = getattr(self.adapter, "position_management_capacity", None)
        if probe is None:
            return True
        try:
            open_positions = len(
                [
                    p
                    for p in (await self.portfolio.get_positions()).values()
                    if p.quantity != 0
                ]
            )
            facts = probe(open_positions=open_positions)
        except Exception:
            logger.warning("position management capacity check failed", exc_info=True)
            return False
        if facts.get("position_management_capacity_available"):
            return True
        await self.audit.log(
            "POSITION_MANAGEMENT_CAPACITY_UNAVAILABLE",
            target=f"open={open_positions}",
            run_id=self.run_id,
            after=facts,
        )
        return False

    async def _resolve_stale_position_action(
        self, order_id: str, *, trade_plan_id: str | None = None
    ) -> None:
        """RECONCILE_THEN_CANCEL_ONLY for a stale position-reducing order.

        A resting order genuinely is pending, so the duplicate guard stays. But
        a partially filled order must not lock position management forever. The
        authorised policy is cancel-ONLY:

          1. reconcile against authoritative state FIRST, so a fill that lands
             at the last moment is consumed instead of being cancelled away;
          2. only cancel when the refreshed class is still STALE;
          3. never cancel an ambiguous (UNKNOWN / CANCEL_PENDING) state — that
             stays fail-closed and keeps reconciling.

        No replacement, no repricing, no market conversion, no resubmission. The
        duplicate guard keeps blocking until a terminal state is acknowledged,
        and the newest position intent is replayed through a fresh ChiefTrader
        review rather than being re-submitted mechanically.
        """
        try:
            facts = await self.order_manager.reconcile_pending_position_action(order_id)
            if facts is None:
                return
            classification = facts.get("classification")
            await self.audit.log(
                "POSITION_ACTION_STALE_RECONCILED",
                target=order_id,
                run_id=self.run_id,
                order_id=order_id,
                after={
                    "trade_plan_id": trade_plan_id,
                    "status": facts["status"],
                    "filled_quantity": facts["filled_quantity"],
                    "remaining_quantity": facts["remaining_quantity"],
                    "age_seconds": facts["age_seconds"],
                    "classification": classification,
                },
            )
            if classification != POSITION_ACTION_STALE:
                # Ambiguous or already resolved: never act on top of it.
                return
            if not await self._current_lease_valid():
                await self.audit.log(
                    "POSITION_ACTION_STALE_CANCEL_BLOCKED",
                    target=order_id,
                    run_id=self.run_id,
                    order_id=order_id,
                    after={"reason": "EXECUTION_LEASE_NOT_HELD"},
                )
                return
            order = await self.order_manager.get(order_id)
            if order is None:
                return
            await self.order_manager.cancel_pending(
                order_id, reason="STALE_POSITION_REDUCING_ORDER"
            )
            # Re-check immediately before the exchange mutation.
            if not await self._current_lease_valid():
                await self.audit.log(
                    "POSITION_ACTION_STALE_CANCEL_BLOCKED",
                    target=order_id,
                    run_id=self.run_id,
                    order_id=order_id,
                    after={"reason": "EXECUTION_LEASE_LOST_BEFORE_CANCEL"},
                )
                return
            await self.adapter.cancel_order(order.symbol, order.exchange_order_id)
            await self.audit.log(
                "POSITION_ACTION_STALE_CANCEL_REQUESTED",
                target=order_id,
                run_id=self.run_id,
                order_id=order_id,
                after={
                    "trade_plan_id": trade_plan_id,
                    "status": "CANCEL_PENDING",
                    "policy": "RECONCILE_THEN_CANCEL_ONLY",
                    "remaining_quantity": facts["remaining_quantity"],
                },
            )
            # Once the cancel is acknowledged the blocking action is gone, so
            # re-arm a fresh review instead of replaying an old intent: the
            # newest HOLD/REDUCE/EXIT must come from ChiefTrader against current
            # evidence, not from a mechanically re-submitted historical signal.
            symbol = order.symbol
            state = self._position_review_state.get(symbol)
            if state is not None:
                state["next_due_at"] = 0.0
                state.pop("last_review_signature", None)
            await self.audit.log(
                "POSITION_REVIEW_REARMED_AFTER_STALE_CANCEL",
                target=symbol,
                run_id=self.run_id,
                after={"trade_plan_id": trade_plan_id, "order_id": order_id},
            )
        except Exception:
            # Fail closed: an ambiguous cancel must never become a new order.
            logger.exception(
                "POSITION_ACTION_STALE_CANCEL_FAILED order_id=%s", order_id
            )
            await self.audit.log(
                "POSITION_ACTION_STALE_CANCEL_UNKNOWN",
                target=order_id,
                run_id=self.run_id,
                order_id=order_id,
                after={"reason": "CANCEL_RESULT_AMBIGUOUS", "fail_closed": True},
            )

    async def _cancel_unsettled_entry_order(self, entry_order) -> None:
        """Cancel a non-terminal entry order before a later EXIT/REDUCE.

        Cancellation is an execution mutation and therefore must be fenced by
        the current lease. Uses OrderManager + adapter cancel path. No direct
        DB mutation and no new exit order. If cancellation fails, the runtime
        stays fail-closed.
        """
        try:
            if not await self._current_lease_valid():
                await self.audit.log(
                    "POSITION_ACTION_CANCEL_ENTRY_BLOCKED",
                    target=entry_order.client_order_id,
                    run_id=self.run_id,
                    client_order_id=entry_order.client_order_id,
                    order_id=entry_order.internal_order_id,
                    after={"reason": "EXECUTION_LEASE_NOT_HELD"},
                )
                return
            await self.order_manager.cancel_pending(
                entry_order.internal_order_id,
                reason="POSITION_ACTION_ENTRY_UNSETTLED",
            )
            # Re-check immediately before the exchange mutation; lease can be
            # lost during local persistence.
            if not await self._current_lease_valid():
                await self.audit.log(
                    "POSITION_ACTION_CANCEL_ENTRY_BLOCKED",
                    target=entry_order.client_order_id,
                    run_id=self.run_id,
                    client_order_id=entry_order.client_order_id,
                    order_id=entry_order.internal_order_id,
                    after={"reason": "EXECUTION_LEASE_LOST_BEFORE_CANCEL"},
                )
                return
            await self.adapter.cancel_order(
                entry_order.symbol, entry_order.exchange_order_id
            )
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
        # Resource readiness for a NEW entry only: a position-reducing action
        # must never be gated by management capacity, or an unmanageable
        # position could never be reduced. Authority-neutral: this can only make
        # an entry wait, never pick or change a direction.
        if (
            signal.strategy_id == "live_llm"
            and self.settings.enforce_position_management_capacity
        ):
            if not await self._position_management_capacity_available():
                return None
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
        if (is_entry or is_position_action) and not trade_plan_id:
            await self.audit.log(
                "TRADEPLAN_REQUIRED",
                target=client_order_id,
                run_id=run_id,
                after={"reason": "Live LLM entry has no durable TradePlan"},
            )
            return None
        if is_entry:
            plan = await self.trade_plans.get(trade_plan_id)
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
            expected_side = (
                OrderSide.SELL if plan is not None and plan.direction == "LONG" else OrderSide.BUY
            )
            valid_reduction = (
                plan is not None
                and plan.symbol == signal.symbol
                and plan.state
                in {TradePlanState.ACTIVE, TradePlanState.RECOVERY}
                and plan.latest_position_decision_id == signal.metadata.get("decision_id")
                and action in {"REDUCE", "EXIT", "TIME_STOP_SAFETY_FALLBACK"}
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
            if plan.state == TradePlanState.RECOVERY:
                # Orphan recovery has no entry order to wait for; the factual
                # position is the lifecycle anchor and the plan closes at zero.
                entry_order = None
            else:
                entry_order = (
                    await self.order_manager.get(plan.order_id)
                    if plan is not None and plan.order_id is not None
                    else None
                )
            if (
                plan.state == TradePlanState.ACTIVE
                and (entry_order is None or entry_order.status not in TERMINAL_ORDER_STATUSES)
            ):
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
            if await self.order_manager.has_pending_position_action(trade_plan_id):
                # The duplicate guard MUST stay (a resting order is genuinely
                # pending, and a second independent REDUCE/EXIT could over-reduce
                # or flip the position). What must not happen is the resulting
                # management gap staying invisible: report the pending action's
                # factual remaining quantity and age, and escalate to an explicit
                # PARTIAL_ORDER_REVIEW_REQUIRED state once it outlives the stale
                # window. This never cancels/amends/replaces anything — that is
                # execution policy — and it never drops the newest intent, which
                # remains the plan's latest position decision and is re-evaluated
                # on every subsequent review once the order settles.
                facts = await self.order_manager.pending_position_action_facts(
                    trade_plan_id
                )
                await self.audit.log(
                    "POSITION_ACTION_ALREADY_PENDING",
                    target=client_order_id,
                    run_id=run_id,
                    after={
                        "trade_plan_id": trade_plan_id,
                        "pending_action": facts,
                        "requested_action": signal.metadata.get("lifecycle_action"),
                        "requested_decision_id": signal.metadata.get("decision_id"),
                        "latest_intent_preserved": True,
                    },
                )
                if facts is not None and facts.get("stale"):
                    await self.audit.log(
                        "PARTIAL_ORDER_REVIEW_REQUIRED",
                        target=client_order_id,
                        run_id=run_id,
                        after={
                            "trade_plan_id": trade_plan_id,
                            "order_id": facts["order_id"],
                            "status": facts["status"],
                            "remaining_quantity": facts["remaining_quantity"],
                            "age_seconds": facts["age_seconds"],
                            "stale_after_seconds": facts["stale_after_seconds"],
                            "classification": facts.get("classification"),
                            "blocked_action": signal.metadata.get("lifecycle_action"),
                        },
                    )
                    await self._resolve_stale_position_action(
                        facts["order_id"], trade_plan_id=trade_plan_id
                    )
                return None

        await self._refresh_execution_market(symbol)
        account = await self.portfolio.get_account(self.settings.effective_mode())
        book = self.market_data.books.get(symbol)
        market_price = D("0")
        if book is not None:
            mid = book.mid_price()
            if mid is not None:
                market_price = mid
        batch = await self._resolve_signal_valuation(
            signal, account=account, positions=positions
        )
        valuation_available = (
            batch.quality == VALUATION_QUALITY_HEALTHY
            and batch.raw_mtm_equity is not None
        )
        market_prices = self._prices_from_batch(
            batch, symbol=symbol, market_price=market_price
        )
        mtm_equity = batch.raw_mtm_equity if valuation_available else account.equity
        drawdown = batch.drawdown_amount
        peak_equity = batch.peak_adjusted_equity
        valuation_as_of = batch.market_as_of or batch.valuation_as_of
        drawdown_source = (
            "MARK_TO_MARKET_EQUITY" if valuation_available else "VALUATION_UNAVAILABLE"
        )
        open_orders = await self.order_manager.count_open()
        daily_end = datetime.now(UTC)
        daily_start = daily_end.replace(hour=0, minute=0, second=0, microsecond=0)
        account_id = getattr(account, "account_id", None) or "default"
        # Every factual lifecycle independently proves funding coverage; a
        # symbol may have several sequential or concurrent lifecycles in one
        # day and none may be collapsed into a single latest window.
        def _utc(value):
            if value is None:
                return None
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)

        lifecycle_plans = await self.trade_plans.lifecycles_overlapping(
            daily_start, daily_end
        )
        funding_scopes: list[FundingScope] = []
        covered_instruments: set[str] = set()
        for plan in lifecycle_plans:
            opened_at = _utc(getattr(plan, "opened_at", None))
            if opened_at is None:
                continue
            scope_start = max(daily_start, opened_at)
            closed_at = _utc(getattr(plan, "closed_at", None))
            if closed_at is None:
                scope_end = daily_end
            else:
                # Include a funding event exactly at the factual close.
                scope_end = min(daily_end, closed_at + timedelta(microseconds=1))
            if scope_start >= scope_end:
                continue
            funding_scopes.append(
                FundingScope(
                    account_id=account_id,
                    currency="USDT",
                    instrument_id=str(plan.symbol),
                    window_start=scope_start,
                    window_end=scope_end,
                    lifecycle_id=plan.trade_plan_id,
                )
            )
            covered_instruments.add(str(plan.symbol))
        # Verified ledger activity without a lifecycle plan still needs a
        # conservative instrument-wide scope; it cannot be attributed to a
        # fabricated lifecycle window.
        activity_instrument_ids = await self.ledger.activity_instruments(
            daily_start,
            account_id=account_id,
            currency="USDT",
            end=daily_end,
        )
        for instrument_id in sorted(activity_instrument_ids - covered_instruments):
            funding_scopes.append(
                FundingScope(
                    account_id=account_id,
                    currency="USDT",
                    instrument_id=instrument_id,
                    window_start=daily_start,
                    window_end=daily_end,
                    lifecycle_id=None,
                )
            )
        coverage_by_scope: dict[str, tuple[str, tuple[dict, ...] | None]] = {}
        for scope in funding_scopes:
            coverage = await self.funding_coverage.coverage_for(
                instrument_id=scope.instrument_id,
                start=scope.window_start,
                end=scope.window_end,
            )
            key = scope.lifecycle_id or scope.instrument_id
            coverage_by_scope[key] = (
                coverage.coverage_status if coverage is not None else "UNKNOWN",
                coverage.window_events if coverage is not None else None,
            )
        pnl_provenance = await self.ledger.net_pnl_provenance_since(
            daily_start,
            account_id=account_id,
            currency="USDT",
            instrument_ids=[],
            end=daily_end,
            funding_scopes=funding_scopes,
            coverage_by_scope=coverage_by_scope,
        )
        if pnl_provenance.complete:
            daily_pnl = (
                pnl_provenance.realized_pnl
                - pnl_provenance.fees
                + (pnl_provenance.funding_amount or Decimal("0"))
            )
            daily_pnl_source = "LEDGER:REALIZED-FEE+FUNDING"
        else:
            # Unknown must not masquerade as factual zero; risk-reducing
            # actions remain allowed by the RiskEngine contract.
            daily_pnl = None
            daily_pnl_source = (
                "ACCOUNTING_INCOMPLETE:"
                + ",".join(pnl_provenance.unknown_reasons or ("UNSPECIFIED",))
            )
        risk_decision = self.risk_engine.check(
            signal,
            account=account,
            positions=positions,
            market_price=market_price,
            market_prices=market_prices,
            open_order_count=open_orders,
            daily_pnl=daily_pnl,
            daily_pnl_source=daily_pnl_source,
            drawdown=drawdown,
            drawdown_source=drawdown_source,
            current_equity=mtm_equity if valuation_available else account.equity,
            peak_equity=peak_equity,
            valuation_as_of=(
                valuation_as_of.isoformat() if valuation_as_of is not None else None
            ),
            valuation_currency=batch.currency,
            valuation_source=drawdown_source,
            valuation_id=batch.valuation_id,
            valuation_quality=batch.quality,
            available_margin=batch.available_margin,
            funding_status=pnl_provenance.funding_status,
            pnl_provenance={
                "valuation_id": batch.valuation_id,
                "valuation_quality": batch.quality,
                "valuation_position_snapshot_ref": batch.position_snapshot_ref,
                "valuation_ledger_watermark": batch.ledger_watermark,
                "account_id": pnl_provenance.account_id,
                "currency": pnl_provenance.currency,
                "window_start": pnl_provenance.window_start.isoformat(),
                "window_end": pnl_provenance.window_end.isoformat(),
                "ledger_watermark": pnl_provenance.ledger_watermark,
                "realized_pnl": str(pnl_provenance.realized_pnl),
                "fees": str(pnl_provenance.fees),
                "funding_amount": (
                    str(pnl_provenance.funding_amount)
                    if pnl_provenance.funding_amount is not None
                    else None
                ),
                "known_funding_subtotal": (
                    str(pnl_provenance.known_funding_subtotal)
                    if pnl_provenance.known_funding_subtotal is not None
                    else None
                ),
                "required_instruments": list(pnl_provenance.required_instruments),
                "funding_status": pnl_provenance.funding_status,
                "complete": pnl_provenance.complete,
                "unknown_reasons": list(pnl_provenance.unknown_reasons),
            },
            risk_equity=mtm_equity if valuation_available else account.equity,
            consecutive_failures=self.consecutive_failures,
            run_id=run_id,
        )
        await self._persist_risk(risk_decision)
        if (
            self.market_intelligence is not None
            and risk_decision.decision
            in {ExecutionDecision.APPROVE, ExecutionDecision.SCALE_DOWN}
        ):
            try:
                self.market_intelligence.record_risk_approval()
            except Exception:  # observability must never affect risk authority
                logger.warning("market_intelligence.record_risk_approval failed", exc_info=True)
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

        approved_metadata = {
            **signal.metadata,
            "risk_decision_id": risk_decision.risk_decision_id,
            "approved_leverage": str(
                risk_decision.checks.get(
                    "approved_leverage", signal.metadata.get("requested_leverage", "1")
                )
            ),
        }
        executable_signal = signal.model_copy(update={"metadata": approved_metadata})
        if risk_decision.decision == ExecutionDecision.SCALE_DOWN:
            approved_quantity = D(str(risk_decision.checks["approved_quantity"]))
            executable_signal = executable_signal.model_copy(
                update={"quantity": approved_quantity}
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
        # Risk persistence and plan linkage can take non-trivial DB time; refresh
        # again immediately before authority so a slow SQLite commit cannot make
        # the 2s orderbook freshness check fail on an otherwise healthy feed.
        await self._refresh_execution_market(symbol)
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
            await RecoveryService(self.order_manager, self.adapter, self.audit).recover(run_id)
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

        await self._sync_submitted_order_state(
            order,
            exchange_order,
            client_order_id=client_order_id,
            run_id=run_id,
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
        self.health.set("submission", True)
        return risk_decision

    async def _sync_submitted_order_state(
        self, order, exchange_order, *, client_order_id: str, run_id: str | None
    ) -> None:
        """Best-effort post-submit sync; the event stream is authoritative.

        The simulator emits ack/open/fill inline while submit_order is in
        flight, so the event task may already have applied the transition.
        Duplicate transitions must not abort the tick after the exchange has
        already mutated its book.
        """
        try:
            await self.order_manager.ack(
                order.internal_order_id,
                exchange_order.exchange_order_id,
                event_id=new_id("evt"),
            )
            if exchange_order.status == OrderStatus.OPEN:
                await self.order_manager.opened(
                    order.internal_order_id, event_id=new_id("evt")
                )
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
                after={
                    "reason": str(exc),
                    "exchange_status": exchange_order.status.value,
                },
            )

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
            await self._sync_terminal_entry_plan(
                local, TradePlanState.CANCELLED, "ORDER_CANCELLED"
            )
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
        if self.market_intelligence is not None:
            try:
                self.market_intelligence.record_execution()
            except Exception:  # observability must never affect execution
                logger.warning("market_intelligence.record_execution failed", exc_info=True)
        position = await self.portfolio.get_position(fill.symbol)
        account = await self.portfolio.get_account(self.settings.effective_mode())
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
                contract_size=D(
                    order.metadata.get("contract_size")
                    if order.metadata.get("contract_size") is not None
                    else _raise_missing_contract_spec(order.symbol)
                ),
                contract_multiplier=D(
                    order.metadata.get("contract_multiplier")
                    if order.metadata.get("contract_multiplier") is not None
                    else _raise_missing_contract_spec(order.symbol)
                ),
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
            account_id=account.account_id,
            instrument_id=order.symbol,
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
            and plan.state in {TradePlanState.ACTIVE, TradePlanState.RECOVERY}
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
                episode = await self.trade_episodes.build_for_closed_plan(
                    closed_plan.trade_plan_id
                )
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

    async def _sync_terminal_entry_plan(
        self, order, state: TradePlanState, reason: str
    ) -> None:
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
                    account_id="default",
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
                "fence_generation": (
                    lease.fence_generation if lease is not None else None
                ),
                "single_writer": self._lease_valid if self.require_lease else True,
            },
            "reconciliation_halted": self.reconciliation_halted,
            "health": self.health.snapshot(),
            "kill_switch": self.kill_switch_snapshot(),
        }

    async def wait_for_event_queue(self) -> None:
        await self._event_queue.join()


def _raise_missing_contract_spec(symbol: str):
    raise ValueError(
        f"LINEAR_PERP fill missing proven contract spec for {symbol}"
    )
