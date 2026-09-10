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
    LedgerPosting,
    LedgerService,
    build_derivative_trade_entries,
    build_trade_entries,
)
from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.observability.audit import AuditService
from crypto_trader.order.manager import OrderManager
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
    ) -> None:
        self.settings = settings
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

    async def _funding_loop(self) -> None:
        while True:
            try:
                report = await self.funding_supervisor.run_once()
                ok = not report.errors
                detail = "; ".join(report.errors[:3]) if report.errors else ""
                self.health.set("funding_accounting", ok, detail)
            except Exception as exc:
                self.health.set("funding_accounting", False, type(exc).__name__)
            await asyncio.sleep(max(1, self.settings.funding_refresh_interval_seconds))

    async def _reconciliation_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.reconciliation_interval_seconds)
            report = await self.reconciliation.reconcile(self.adapter)
            self.reconciliation_halted = report.halt
            self.health.set("reconciliation", not report.halt, "; ".join(report.alerts[:3]))

    # ------------------------------------------------------------------ tick
    async def tick(self) -> list[RiskDecision]:
        decisions: list[RiskDecision] = []
        for strategy in self.strategies:
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
        if self.position_manager is not None:
            positions = await self.portfolio.get_positions()
            for position in positions.values():
                if position.quantity == 0:
                    continue
                ctx = await self._strategy_context(position.symbol)
                if ctx is None:
                    continue
                try:
                    signal = await self.position_manager.review(ctx, position)
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
                and plan.state == TradePlanState.ACTIVE
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
            if await self.order_manager.has_pending_position_action(trade_plan_id):
                await self.audit.log(
                    "POSITION_ACTION_ALREADY_PENDING",
                    target=client_order_id,
                    run_id=run_id,
                    after={"trade_plan_id": trade_plan_id},
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
        # Every open USDT linear swap must independently prove funding coverage.
        # The ledger read below adds any instrument with factual PnL/funding
        # postings, so an unattributed or wrong-instrument posting can never be
        # silently dropped from the daily total.
        open_instrument_ids = sorted(
            {
                position_symbol
                for position_symbol, position in positions.items()
                if position.quantity != 0
                and getattr(position, "instrument_type", "SPOT") == "LINEAR_PERP"
            }
        )
        activity_instrument_ids = await self.ledger.activity_instruments(
            daily_start,
            account_id=account_id,
            currency="USDT",
            end=daily_end,
        )
        funding_instrument_ids = sorted(
            set(open_instrument_ids) | activity_instrument_ids
        )

        def _utc(value):
            if value is None:
                return None
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)

        # Funding only accrues while the factual position is open. Open
        # positions use the active plan; closed instruments use their latest
        # plan's factual close so post-close funding events cannot be charged.
        instrument_window_starts: dict[str, datetime] = {}
        instrument_window_ends: dict[str, datetime] = {}
        for instrument_id in funding_instrument_ids:
            if instrument_id in open_instrument_ids:
                plan = await self.trade_plans.get_active_for_symbol(instrument_id)
            else:
                plan = await self.trade_plans.latest_for_symbol(instrument_id)
            opened_at = _utc(getattr(plan, "opened_at", None) if plan is not None else None)
            closed_at = _utc(getattr(plan, "closed_at", None) if plan is not None else None)
            if opened_at is not None:
                instrument_window_starts[instrument_id] = max(daily_start, opened_at)
            if closed_at is not None:
                instrument_window_ends[instrument_id] = min(daily_end, closed_at)
        coverage_status_by_instrument = {
            instrument_id: await self.funding_coverage.status_for(
                instrument_id=instrument_id,
                start=instrument_window_starts.get(instrument_id, daily_start),
                end=instrument_window_ends.get(instrument_id, daily_end),
            )
            for instrument_id in funding_instrument_ids
        }
        pnl_provenance = await self.ledger.net_pnl_provenance_since(
            daily_start,
            account_id=account_id,
            currency="USDT",
            instrument_ids=funding_instrument_ids,
            end=daily_end,
            coverage_status_by_instrument=coverage_status_by_instrument,
            instrument_window_starts=instrument_window_starts,
            instrument_window_ends=instrument_window_ends,
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

        await self.order_manager.ack(
            order.internal_order_id, exchange_order.exchange_order_id, event_id=new_id("evt")
        )
        if exchange_order.status == OrderStatus.OPEN:
            await self.order_manager.opened(order.internal_order_id, event_id=new_id("evt"))
        elif exchange_order.status == OrderStatus.CANCELLED:
            await self.order_manager.cancel_confirm(order.internal_order_id, event_id=new_id("evt"))
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
