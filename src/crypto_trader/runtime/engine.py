"""TradingEngine: the only orchestration path from market event to audit.

Market Event -> StrategyPlugin -> SignalIntent -> PreTrade Risk
-> ExecutionAuthority -> OrderManager -> ExchangeAdapter -> Exchange Events
-> Order State Machine -> Ledger -> Portfolio Projection -> Audit
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.config import Settings
from crypto_trader.domain.clock import Clock, SystemClock
from crypto_trader.domain.enums import (
    ExchangeEventType,
    ExecutionDecision,
    LedgerDirection,
    LedgerEntryType,
    MarketType,
    OrderSide,
    OrderStatus,
    PositionSide,
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
    Instrument,
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
from crypto_trader.ledger.service import LedgerPosting, LedgerService, build_trade_entries
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.observability.audit import AuditService
from crypto_trader.order.manager import OrderManager
from crypto_trader.perpetual.engine import PerpetualPaperEngine
from crypto_trader.persistence.database import Database
from crypto_trader.persistence.models import EngineRunORM, RiskDecisionORM
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.reconciliation.service import ReconciliationService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.ai_position_bridge import AIPositionRuntimeBridge
from crypto_trader.runtime.event_bus import EventBus
from crypto_trader.runtime.execution_symbols import reference_symbol_for
from crypto_trader.runtime.health import HealthRegistry
from crypto_trader.runtime.lease import Lease, LeaseManager
from crypto_trader.runtime.recovery import RecoveryService
from crypto_trader.runtime.state_machine import RuntimeStateMachine
from crypto_trader.strategy.base import StrategyContext, StrategyPlugin

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
        ai_position_bridge: AIPositionRuntimeBridge | None = None,
        clock: Clock | None = None,
        authority: ExecutionAuthority | None = None,
        perpetual_engine: PerpetualPaperEngine | None = None,
        lease_key: str = "crypto_engine_execution",
        require_lease: bool = True,
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
        self.ai_position_bridge = ai_position_bridge
        self.clock = clock or SystemClock()
        self.authority = authority or ExecutionAuthority()
        self.perpetual_engine = perpetual_engine
        self.lease_key = lease_key
        self.require_lease = require_lease
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
        self.quarantined_fill_ids: set[str] = set()

    # ------------------------------------------------------------------ state
    async def _load_quarantined_fill_ids(self) -> set[str]:
        """Fills quarantined by an EVIDENCE_QUARANTINE audit event are
        excluded from learning (trade_memory_records) while every raw audit
        fact stays untouched. Best-effort: no rows means no quarantines."""
        from sqlalchemy import text
        try:
            async with self.database.session_factory() as session:
                result = await session.execute(
                    text("SELECT after_json FROM audit_events WHERE action='EVIDENCE_QUARANTINE'")
                )
                rows = result.all()
        except Exception:
            return set()
        quarantined: set[str] = set()
        for row in rows:
            try:
                payload = json.loads(row[0] or '{}')
                quarantined.update(payload.get('tainted_fill_ids') or [])
            except Exception:
                continue
        return quarantined

    async def start(self, run_id: str | None = None) -> str:
        self.quarantined_fill_ids = await self._load_quarantined_fill_ids()
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
        # Ledger-first paper execution: adopt the persistent ledger state so
        # restarts never diverge from the ledger (reconciliation halt guard).
        hydrate = getattr(self.adapter, "hydrate_from_ledger", None)
        if hydrate is not None:
            await hydrate(self.database.session_factory)
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
                logger.exception(
                    "EVENT_PROCESSING_FAILED type=%s", type(event.event_type).name
                )
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
        positions = await self.portfolio.get_positions()
        active_symbols = {
            symbol for symbol, position in positions.items() if float(position.quantity or 0) != 0
        }
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
            if signals:
                # An LLM-backed strategy may take seconds to decide; refresh
                # the cached orderbook once so the ExecutionAuthority sees
                # CURRENT market data at authorization time. The authority's
                # staleness gate stays the safety check — it is only fed
                # fresh data, never bypassed.
                await self._refresh_orderbook(reference_symbol_for(signals[0].symbol))
            for signal in signals:
                # Active-position priority: suppress accidental duplicate entry
                # for symbols already held unless this is the AI position path.
                if (
                    signal.symbol in active_symbols
                    and getattr(signal, "strategy_id", "") != "ai_brain"
                ):
                    continue
                decision = await self.process_signal(signal)
                if decision is not None:
                    decisions.append(decision)
        if self.ai_position_bridge is not None:
            await self.ai_position_bridge.evaluate_active_positions(self, self.portfolio)
        self.health.set("engine_loop", True)
        return decisions

    async def _refresh_orderbook(self, symbol: str) -> None:
        """Best-effort orderbook refresh before authorization.

        A FAILED refresh deliberately leaves the previous book state untouched
        (no invalidate here): the ExecutionAuthority's freshness gate still
        judges whatever data exists, so fail-closed semantics are preserved.
        """
        try:
            fetched = await self.adapter.get_orderbook(symbol)
            await self.market_data.ingest_snapshot(
                symbol,
                fetched.sequence,
                [(level.price, level.quantity) for level in fetched.bids.values()],
                [(level.price, level.quantity) for level in fetched.asks.values()],
            )
        except Exception as exc:
            self.health.set("market_data_refresh", False, f"{symbol}: {type(exc).__name__}")

    async def _strategy_context(self) -> StrategyContext | None:
        symbol = getattr(self.strategies[0], "symbol", "BTCUSDT") if self.strategies else "BTCUSDT"
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
            # A successful real ingest IS the recovery signal: clear the
            # market-data health flag set by any earlier transient fetch
            # failure. Per-symbol staleness/health gates are unchanged.
            self.health.set("market_data", True)
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
        )

    # --------------------------------------------------------------- signals
    async def _current_signed_quantity(
        self, symbol: str, market_type: MarketType, positions: dict
    ) -> Decimal:
        """Signed position for the order's symbol (positive LONG, negative SHORT)."""
        if market_type == MarketType.PERPETUAL:
            if self.perpetual_engine is None:
                return Decimal("0")
            state = await self.perpetual_engine.load_state()
            pos = state.positions.get(symbol)
            return pos.quantity if pos is not None and not pos.is_flat else Decimal("0")
        spot = positions.get(symbol)
        return D(spot.quantity) if spot is not None else Decimal("0")

    async def _execute_perpetual_order(
        self,
        intent: OrderIntent,
        market_price: Decimal,
        position_side: PositionSide,
        run_id: str | None,
        client_order_id: str,
    ) -> None:
        engine = self.perpetual_engine
        if engine is None:
            await self.audit.log(
                "PERPETUAL_ENGINE_MISSING",
                target=client_order_id,
                run_id=run_id,
                client_order_id=client_order_id,
            )
            return
        if position_side == PositionSide.FLAT:
            position_side = (
                PositionSide.LONG if intent.side == OrderSide.BUY else PositionSide.SHORT
            )
        # §6: this path is only reached after the PERPETUAL_REFERENCE_PRICE
        # gate above has verified a real, positive reference mark price.
        if market_price <= 0:
            await self.audit.log(
                "PERPETUAL_REFERENCE_PRICE_UNAVAILABLE",
                target=client_order_id,
                run_id=run_id,
                client_order_id=client_order_id,
                after={"price": str(market_price)},
            )
            return
        price = market_price
        qty = D(intent.quantity)
        order = await self.order_manager.create_from_intent(
            intent, trading_mode=self.settings.effective_mode()
        )
        await self.order_manager.validate(order.internal_order_id)
        await self.order_manager.submitting(order.internal_order_id)
        await self.order_manager.submitted(order.internal_order_id)
        # §9: desired PAPER exploration leverage is centralized; the margin
        # engine still caps it at the contract maximum. Never hardcoded 5x.
        leverage = D(str(self.settings.paper_exploration_leverage))
        if intent.reduce_only:
            await engine.close_position(
                position_side, qty, price, order_id=order.internal_order_id
            )
        else:
            await engine.open_position(
                position_side, qty, price, leverage, order_id=order.internal_order_id
            )
        # §15/§17: persist a canonical FillORM for every PAPER perpetual open
        # and close so orders UI / fills / exploration attribution / Daily
        # Learning all see the same auditable fill record.
        contract = engine.contract
        fee = qty * price * contract.contract_size * contract.taker_fee_rate
        fill = Fill(
            fill_id=new_id("fill"),
            trade_id=new_id("trd"),
            order_id=order.internal_order_id,
            client_order_id=client_order_id,
            exchange_order_id=f"paper_perp_{order.internal_order_id}",
            symbol=intent.symbol,
            side=intent.side,
            price=price,
            quantity=qty,
            fee=fee,
            fee_currency="USDT",
            timestamp=datetime.now(UTC),
            payload={
                "market_type": MarketType.PERPETUAL.value,
                "position_side": position_side.value,
                "decision_id": (intent.metadata or {}).get("decision_id", ""),
                "signal_id": (intent.metadata or {}).get("signal_id", ""),
                "reference_market_symbol": (
                    intent.metadata or {}
                ).get("reference_market_symbol", reference_symbol_for(intent.symbol)),
                "paper_execution": True,
            },
        )
        await self.order_manager.apply_fill(fill)
        await self.audit.log(
            "PERPETUAL_ORDER_FILLED",
            target=client_order_id,
            run_id=run_id,
            client_order_id=client_order_id,
            order_id=order.internal_order_id,
            after={
                "side": position_side.value,
                "quantity": str(qty),
                "reduce_only": intent.reduce_only,
                "fill_id": fill.fill_id,
                "price": str(price),
                "fee": str(fee),
            },
        )
        self.health.set("submission", True)

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

        account = await self.portfolio.get_account(self.settings.effective_mode())
        positions = await self.portfolio.get_positions()
        # Normalize the order contract into typed fields: read legacy metadata
        # once here, then downstream layers rely on the typed fields only.
        market_type = signal.market_type
        position_side = signal.position_side
        reduce_only = bool(signal.reduce_only or signal.metadata.get("reduce_only", False))
        # §5/§13: perpetual orders are marked against the REAL reference
        # market book (BTCUSDT), never against a non-existent BTCUSDT_PERP
        # book, and never against a fallback price.
        reference_symbol = (
            reference_symbol_for(symbol)
            if market_type == MarketType.PERPETUAL
            else symbol
        )
        # Pre-authorization refresh for THIS signal's symbol: every
        # authorization path (strategy entries AND bridge reduce-only EXITs)
        # must price against a fresh real book, not whatever stale state a
        # previous tick happened to leave. Best-effort: a failed refresh
        # keeps the previous book and the RiskEngine/ExecutionAuthority
        # freshness gates still judge it (fail-closed semantics unchanged).
        # Only real-market adapters refresh here: a simulated adapter may
        # fabricate a seeded book on get_orderbook, which would substitute a
        # synthetic price into authorization (the exact thing the no-fake-
        # price rules forbid). Synthetic harnesses seed explicitly.
        if hasattr(self.adapter, "refresh_market_state"):
            await self._refresh_orderbook(reference_symbol)
        book = self.market_data.books.get(reference_symbol)
        market_price = D("0")
        if book is not None:
            mid = book.mid_price()
            if mid is not None:
                market_price = mid
        open_orders = await self.order_manager.count_open()

        # §6 HARD GATE: no real reference mark price -> no new PERPETUAL
        # order. Do not substitute 100 or any other placeholder.
        if market_type == MarketType.PERPETUAL and market_price <= 0:
            risk_decision = RiskDecision(
                risk_decision_id=new_id("risk"),
                client_order_id=client_order_id,
                symbol=symbol,
                side=signal.side,
                decision=ExecutionDecision.REJECT,
                reason="PERPETUAL_REFERENCE_PRICE_UNAVAILABLE",
                checks={"reference_market_symbol": reference_symbol},
                timestamp=datetime.now(UTC),
                run_id=run_id,
            )
            await self._persist_risk(risk_decision)
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

        current_signed_qty = await self._current_signed_quantity(symbol, market_type, positions)

        risk_decision = self.risk_engine.check(
            signal,
            account=account,
            positions=positions,
            market_price=market_price,
            open_order_count=open_orders,
            consecutive_failures=self.consecutive_failures,
            run_id=run_id,
            current_signed_qty=current_signed_qty,
        )
        await self._persist_risk(risk_decision)
        if risk_decision.decision != ExecutionDecision.APPROVE:
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

        instrument = self._instruments.get(symbol)
        if (
            instrument is None
            and market_type == MarketType.PERPETUAL
            and self.perpetual_engine is not None
        ):
            contract = self.perpetual_engine.contract
            instrument = Instrument(
                symbol=symbol,
                base_asset=contract.base,
                quote_asset=contract.quote,
                status="TRADING",
                tick_size=contract.tick_size,
                step_size=contract.quantity_step,
                exchange="PAPER_PERPETUAL",
            )
        lease_held = (
            self.require_lease
            and self.lease is not None
            and await self.lease_manager.is_held(self.lease_key, self.lease.token)
        )
        intent = OrderIntent(
            client_order_id=client_order_id,
            symbol=symbol,
            side=signal.side,
            order_type=signal.order_type,
            time_in_force=signal.time_in_force,
            price=signal.limit_price,
            quantity=signal.quantity,
            strategy_id=signal.strategy_id,
            run_id=run_id,
            expires_at=signal.expires_at,
            market_type=market_type,
            position_side=position_side,
            reduce_only=reduce_only,
            metadata={**signal.metadata, "signal_id": signal.signal_id},
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
                reference_symbol, self.settings.market_data_max_age_seconds
            ),
            orderbook_fresh=self.market_data.is_fresh(
                reference_symbol, self.settings.orderbook_max_age_seconds
            ),
            orderbook_healthy=self.market_data.is_healthy(reference_symbol),
            symbol_tradeable=instrument is not None and instrument.status == "TRADING",
            exchange_connected=self.adapter.connected,
            current_signed_qty=current_signed_qty,
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

        # Route PERPETUAL orders to the paper perpetual engine; SPOT orders
        # continue through the spot order lifecycle below.
        if market_type == MarketType.PERPETUAL:
            await self._execute_perpetual_order(
                intent, market_price, position_side, run_id, client_order_id
            )
            return risk_decision

        # Core order lifecycle: create -> validate -> submit
        order = await self.order_manager.create_from_intent(
            intent, trading_mode=self.settings.effective_mode()
        )
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
        # §16: PERPETUAL fills are recorded for audibility but monetary
        # settlement is owned by FuturesLedger. Never double-post SPOT trade
        # ledger entries or spot positions for a perpetual fill.
        if str((fill.payload or {}).get("market_type")) == MarketType.PERPETUAL.value:
            return
        order = await self.order_manager.get(fill.order_id)
        if order is None:
            return
        if fill.fill_id in self.quarantined_fill_ids:
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
        cost_released = None
        if order.side == OrderSide.SELL:
            # avg_entry_price can be None on a legacy/partially-known
            # position; fall back to the fill price so settlement never
            # crashes on a None * Decimal multiplication (the reduce-only
            # EXIT path depends on this settlement completing).
            avg_entry = None
            if position is not None:
                avg_entry = position.avg_entry_price or fill.price
            else:
                avg_entry = fill.price
            if position is None or position.quantity < fill.quantity:
                # conservative: use current average cost for the filled slice
                cost_released = avg_entry * fill.quantity
            else:
                cost_released = avg_entry * fill.quantity
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
