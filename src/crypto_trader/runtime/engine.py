"""TradingEngine: the only orchestration path from market event to audit.

Market Event -> StrategyPlugin -> SignalIntent -> PreTrade Risk
-> ExecutionAuthority -> OrderManager -> ExchangeAdapter -> Exchange Events
-> Order State Machine -> Ledger -> Portfolio Projection -> Audit
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.config import Settings
from crypto_trader.domain.clock import Clock, SystemClock
from crypto_trader.domain.enums import (
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
from crypto_trader.governance.memory import TradeMemoryRecord
from crypto_trader.governance.memory_persistence import MemoryPersistence
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
        self.position_manager = position_manager
        self.event_bus = EventBus()
        self.health = HealthRegistry()
        self.state_machine = RuntimeStateMachine()

        self.run_id: str | None = None
        self.lease: Lease | None = None
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

        if self.require_lease:
            self.lease = await self.lease_manager.acquire(
                self.lease_key, f"engine_{self.run_id}", self.settings.run_lease_ttl_seconds
            )
            if self.lease is None:
                await self._persist_run(RuntimeState.STOPPED)
                self.state_machine.transition(RuntimeState.STOPPED)
                raise LeaseNotHeld("another engine instance holds the execution lease")
        self.health.set("execution_lease", self.lease is not None or not self.require_lease)

        self.state_machine.transition(RuntimeState.RECOVERING)
        await self._persist_run(RuntimeState.RECOVERING)
        await self._seed_initial_balances()
        await self._load_instruments()
        self.order_manager.settlement_callback = self._settle_fill
        await RecoveryService(self.order_manager, self.adapter, self.audit).recover(self.run_id)
        self.health.set("recovery", True)

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
            await self.lease_manager.release(self.lease_key, self.lease.token)
            self.lease = None
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
            await self.tick()

    async def _lease_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.run_lease_renew_interval_seconds)
            if self.lease is not None:
                ok = await self.lease_manager.renew(
                    self.lease_key, self.lease.token, self.settings.run_lease_ttl_seconds
                )
                self.health.set("execution_lease", ok)
                if not ok:
                    self.risk_engine.kill_switch.engage("execution lease lost")

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
            ctx = await self._strategy_context()
            if ctx is None:
                continue
            try:
                signals = await strategy.on_market_data(ctx)
            except Exception:
                self.consecutive_failures += 1
                self.health.set(f"strategy:{strategy.name}", False)
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
                except Exception:
                    self.consecutive_failures += 1
                    self.health.set("position_manager", False)
                    continue
                self.health.set("position_manager", True)
                if signal is not None:
                    decision = await self.process_signal(signal)
                    if decision is not None:
                        decisions.append(decision)
        self.health.set("engine_loop", True)
        return decisions

    async def _strategy_context(self, symbol: str | None = None) -> StrategyContext | None:
        symbol = symbol or (
            getattr(self.strategies[0], "symbol", "BTCUSDT")
            if self.strategies
            else "BTCUSDT"
        )
        book = self.market_data.books.get(symbol)
        try:
            fetched = await self.adapter.get_orderbook(symbol)
            await self.market_data.ingest_snapshot(
                symbol,
                fetched.sequence,
                [(level.price, level.quantity) for level in fetched.bids.values()],
                [(level.price, level.quantity) for level in fetched.asks.values()],
            )
            book = self.market_data.books[symbol]
        except Exception:
            # P0: never let a stale cached orderbook authorize new risk.
            if book is not None:
                book.invalidate()
                self.health.set("market_data", False, f"{symbol} invalidated")
            return None
        account = await self.portfolio.get_account(self.settings.effective_mode())
        positions = await self.portfolio.get_positions()
        market_state = None
        get_market_state = getattr(self.adapter, "get_market_state", None)
        if get_market_state is not None:
            try:
                market_state = await get_market_state(symbol)
            except Exception:
                market_state = None
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
            instrument=self._instruments.get(symbol),
        )

    # --------------------------------------------------------------- signals
    async def process_signal(self, signal: SignalIntent) -> RiskDecision | None:
        run_id = self.run_id
        symbol = signal.symbol
        client_order_id = f"{signal.strategy_id}_{signal.signal_id}"[:60]
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
                and action in {"REDUCE", "EXIT"}
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

        account = await self.portfolio.get_account(self.settings.effective_mode())
        book = self.market_data.books.get(symbol)
        market_price = D("0")
        if book is not None:
            mid = book.mid_price()
            if mid is not None:
                market_price = mid
        open_orders = await self.order_manager.count_open()
        risk_decision = self.risk_engine.check(
            signal,
            account=account,
            positions=positions,
            market_price=market_price,
            open_order_count=open_orders,
            consecutive_failures=self.consecutive_failures,
            run_id=run_id,
        )
        await self._persist_risk(risk_decision)
        if trade_plan_id:
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
        lease_held = (
            self.require_lease
            and self.lease is not None
            and await self.lease_manager.is_held(self.lease_key, self.lease.token)
        )
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
            lease_held=lease_held or not self.require_lease,
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
        elif exchange_order.status == OrderStatus.REJECTED:
            await self.order_manager.reject(
                order.internal_order_id,
                exchange_order.rejection_reason or "rejected on exchange",
                event_id=new_id("evt"),
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
        elif event.event_type == ExchangeEventType.ORDER_REJECTED:
            await self.order_manager.reject(
                local.internal_order_id,
                payload.get("reason", "exchange rejection"),
                event_id=event_id,
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
        try:
            persistence = MemoryPersistence(self.database.session_factory)
            await persistence.save_trade_memory(
                TradeMemoryRecord(
                    decision_id=fill.fill_id,
                    symbol=fill.symbol,
                    side=order.side.value,
                    regime="UNKNOWN",
                    strategy_scores={},
                    effective_weights={},
                    raw_confidence=Decimal("0"),
                    calibrated_confidence=Decimal("0"),
                    recommended_position=fill.quantity,
                    approved_position=fill.quantity,
                    recommended_leverage=Decimal("1"),
                    approved_leverage=Decimal("1"),
                    entry=fill.price,
                    exit=fill.price,
                    fees=fill.fee,
                    funding_pnl=Decimal("0"),
                    realized_pnl=Decimal("0"),
                    r_multiple=Decimal("0"),
                )
            )
        except Exception:
            pass
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
            await self.trade_plans.transition(
                plan.trade_plan_id,
                TradePlanState.CLOSED,
                reason=str(order.metadata.get("lifecycle_action") or "POSITION_CLOSED"),
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

    # ---------------------------------------------------------------- helpers
    def kill_switch_snapshot(self) -> dict:
        return self.risk_engine.kill_switch.snapshot()

    def runtime_snapshot(self) -> dict:
        return {
            "run_id": self.run_id,
            "state": self.state_machine.state.value,
            "mode": self.settings.effective_mode().value,
            "lease_held": self.lease is not None,
            "reconciliation_halted": self.reconciliation_halted,
            "health": self.health.snapshot(),
            "kill_switch": self.kill_switch_snapshot(),
        }

    async def wait_for_event_queue(self) -> None:
        await self._event_queue.join()
