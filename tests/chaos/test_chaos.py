"""Mandatory crypto chaos suite (SPAC section 13)."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from crypto_trader.domain.enums import (
    ExchangeEventType,
    LedgerDirection,
    LedgerEntryType,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    TradingMode,
)
from crypto_trader.domain.errors import (
    ExchangeUnavailable,
    IdempotencyConflict,
    JournalUnbalanced,
    MarketDataUnhealthy,
    RateLimited,
    UnknownExecutionState,
)
from crypto_trader.domain.models import OrderIntent, SignalIntent
from crypto_trader.domain.money import DecimalError
from crypto_trader.exchange.binance import BinanceAdapter
from crypto_trader.ledger.projections import replay_projections
from crypto_trader.ledger.service import LedgerPosting, LedgerService, build_trade_entries
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.market_data.websocket import WebSocketReconnectPolicy
from crypto_trader.order.manager import OrderManager
from crypto_trader.persistence.models import Base, OrderORM
from crypto_trader.runtime.lease import LeaseManager
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter
from crypto_trader.strategy.dummy import DummyStrategy
from crypto_trader.strategy.test_strategy import TestStrategy
from tests.conftest import make_paper_engine


def _intent(cid="c_chaos", qty="1", price="100"):
    return OrderIntent(
        client_order_id=cid,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price=price,
        quantity=qty,
        strategy_id="chaos",
    )


def _signal(cid="sig_chaos", qty="0.1", price="101"):
    return SignalIntent(
        signal_id=cid,
        strategy_id="chaos",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=qty,
        limit_price=price,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


async def test_duplicate_client_order_id_test(database):
    mgr = OrderManager(database.session_factory)
    first = await mgr.create_from_intent(_intent(), trading_mode=TradingMode.PAPER)
    second = await mgr.create_from_intent(_intent(), trading_mode=TradingMode.PAPER)
    assert first.internal_order_id == second.internal_order_id
    with pytest.raises(IdempotencyConflict):
        await mgr.create_from_intent(_intent(qty="2"), trading_mode=TradingMode.PAPER)


async def test_partial_fill_test(database):
    mgr = OrderManager(database.session_factory)
    order = await mgr.create_from_intent(_intent(qty="1"), trading_mode=TradingMode.PAPER)
    await mgr.validate(order.internal_order_id)
    await mgr.submitting(order.internal_order_id)
    await mgr.submitted(order.internal_order_id)
    await mgr.ack(order.internal_order_id, "ex_part")
    fill1 = __import__("crypto_trader.domain.models", fromlist=["Fill"]).Fill(
        fill_id="f_part_1",
        order_id=order.internal_order_id,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price="100",
        quantity="0.25",
        timestamp=datetime.now(UTC),
    )
    fill2 = fill1.model_copy(
        update={"fill_id": "f_part_2", "quantity": Decimal("0.75"), "price": Decimal("101")}
    )
    order, _, _ = await mgr.apply_fill(fill1)
    assert order.status == OrderStatus.PARTIALLY_FILLED
    order, _, _ = await mgr.apply_fill(fill2)
    assert order.status == OrderStatus.FILLED
    assert order.avg_fill_price == Decimal("100.75")


async def test_fill_before_ack_test():
    sim = SimulatedExchangeAdapter()
    await sim.connect()
    sim.fill_before_ack = True
    events = []
    await sim.subscribe_order_updates(lambda e: events.append(e.event_type) or asyncio.sleep(0))
    now = datetime.now(UTC)
    from crypto_trader.domain.models import Order

    order = Order(
        internal_order_id="ord_fba",
        client_order_id="c_fba",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price="101",
        quantity="0.1",
        status=OrderStatus.SUBMITTING,
        trading_mode=TradingMode.PAPER,
        created_at=now,
        updated_at=now,
    )
    await sim.submit_order(order)
    assert events == [ExchangeEventType.ORDER_FILLED, ExchangeEventType.ORDER_ACK]


async def test_duplicate_fill_event_test(database):
    applied = []
    mgr = OrderManager(
        database.session_factory,
        settlement_callback=lambda f: applied.append(f.fill_id) or asyncio.sleep(0),
    )
    order = await mgr.create_from_intent(_intent(qty="1"), trading_mode=TradingMode.PAPER)
    await mgr.validate(order.internal_order_id)
    await mgr.submitting(order.internal_order_id)
    await mgr.submitted(order.internal_order_id)
    await mgr.ack(order.internal_order_id, "ex_dup")
    from crypto_trader.domain.models import Fill

    fill = Fill(
        fill_id="dup_fill",
        order_id=order.internal_order_id,
        exchange_order_id="ex_dup",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price="100",
        quantity="0.5",
        timestamp=datetime.now(UTC),
    )
    _, _, first = await mgr.apply_fill(fill)
    _, _, second = await mgr.apply_fill(fill)
    assert (first, second) == (True, False)
    assert applied == ["dup_fill"]


async def test_cancel_fill_race_test():
    sim = SimulatedExchangeAdapter()
    await sim.connect()
    sim.cancel_fill_race = True
    now = datetime.now(UTC)
    from crypto_trader.domain.models import Order

    order = Order(
        internal_order_id="ord_race",
        client_order_id="c_race",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price="1",
        quantity="0.5",
        status=OrderStatus.SUBMITTING,
        trading_mode=TradingMode.PAPER,
        created_at=now,
        updated_at=now,
    )
    submitted = await sim.submit_order(order)
    result = await sim.cancel_order("BTCUSDT", submitted.exchange_order_id)
    assert result.status == OrderStatus.FILLED


async def test_submit_timeout_but_order_created_test():
    sim = SimulatedExchangeAdapter()
    await sim.connect()
    sim.timeout_but_created = True
    now = datetime.now(UTC)
    from crypto_trader.domain.models import Order

    order = Order(
        internal_order_id="ord_timeout",
        client_order_id="c_timeout",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price="1",
        quantity="0.5",
        status=OrderStatus.SUBMITTING,
        trading_mode=TradingMode.PAPER,
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(UnknownExecutionState):
        await sim.submit_order(order)
    recovered = await sim.get_order("BTCUSDT", "sim_1000")
    assert recovered.client_order_id == "c_timeout"


def test_websocket_disconnect_test():
    policy = WebSocketReconnectPolicy(max_attempts=2)
    policy.on_connected()
    policy.on_disconnected()
    assert policy.should_reconnect() and policy.resync_required
    policy.on_disconnected()
    assert policy.should_reconnect()
    policy.on_disconnected()
    assert policy.exhausted()


async def test_websocket_sequence_gap_test():
    svc = MarketDataService()
    with pytest.raises(MarketDataUnhealthy):
        await svc.ingest_delta(
            "BTCUSDT", 5, [(Decimal("1"), Decimal("1"))], [(Decimal("2"), Decimal("1"))]
        )


async def test_orderbook_resync_test():
    snapshots = []

    async def provider(symbol):
        snapshots.append(symbol)
        return {
            "sequence": 20,
            "bids": [(Decimal("99"), Decimal("1"))],
            "asks": [(Decimal("101"), Decimal("1"))],
        }

    svc = MarketDataService(snapshot_provider=provider)
    await svc.ingest_snapshot(
        "BTCUSDT", 10, [(Decimal("99"), Decimal("1"))], [(Decimal("101"), Decimal("1"))]
    )
    # delta 11 ok, then 13 triggers gap and resync
    await svc.ingest_delta("BTCUSDT", 11, [], [])
    await svc.ingest_delta("BTCUSDT", 13, [], [])
    assert svc.books["BTCUSDT"].sequence == 20
    assert snapshots == ["BTCUSDT"]


async def test_rate_limit_test():
    sim = SimulatedExchangeAdapter()
    await sim.connect()
    sim.rate_limit_next = True
    now = datetime.now(UTC)
    from crypto_trader.domain.models import Order

    order = Order(
        internal_order_id="ord_rl",
        client_order_id="c_rl",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price="1",
        quantity="0.5",
        status=OrderStatus.SUBMITTING,
        trading_mode=TradingMode.PAPER,
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(RateLimited):
        await sim.submit_order(order)


async def test_exchange_5xx_test():
    def handler(request):
        return httpx.Response(503, text="upstream unavailable", request=request)

    adapter = BinanceAdapter(
        base_url="https://test.binance",
        client=httpx.AsyncClient(
            base_url="https://test.binance", transport=httpx.MockTransport(handler)
        ),
    )
    await adapter.connect()
    with pytest.raises(ExchangeUnavailable):
        await adapter.get_orderbook("BTCUSDT")


async def test_engine_restart_test(database):
    sim = SimulatedExchangeAdapter(initial_balances={"USDT": Decimal("10000")})
    await sim.connect()
    sim.timeout_but_created = True
    strategy = TestStrategy(quantity="0.1", limit_price="101")
    engine = make_paper_engine(
        database,
        strategy=strategy,
        simulator=sim,
        engine_tick_seconds=3600,
        reconciliation_interval_seconds=3600,
    )
    await engine.start()
    await engine.tick()
    await engine.wait_for_event_queue()
    order = await engine.order_manager.get_by_client(f"test_{strategy.signal_id}"[:60])
    assert order.status in (OrderStatus.UNKNOWN, OrderStatus.ACKNOWLEDGED)
    await engine.stop()

    # "process restart": a new engine instance on the same DB/adapter
    await sim.connect()
    engine2 = make_paper_engine(
        database,
        strategy=DummyStrategy(),
        simulator=sim,
        engine_tick_seconds=3600,
        reconciliation_interval_seconds=3600,
    )
    await engine2.start()
    restored = await engine2.order_manager.get_by_client(f"test_{strategy.signal_id}"[:60])
    assert restored.status == OrderStatus.ACKNOWLEDGED
    async with database.session_factory() as session:
        count = len((await session.execute(select(OrderORM))).scalars().all())
    assert count == 1
    await engine2.stop()


async def test_ledger_replay_test(database):
    ledger = LedgerService(database.session_factory)
    await ledger.record(
        LedgerEntryType.DEPOSIT,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("1000")),
            LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("1000")),
        ],
        transaction_id="txn_chaos_deposit",
        metadata={"amount": "1000"},
    )
    async with database.session_factory() as session:
        snap = await replay_projections(session)
    assert snap.balance("USDT") == Decimal("1000")


async def test_ledger_balance_invariant_test(database):
    ledger = LedgerService(database.session_factory)
    with pytest.raises(JournalUnbalanced):
        await ledger.record(
            LedgerEntryType.DEPOSIT,
            [
                LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("100")),
                LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("99")),
            ],
        )
    postings, _ = build_trade_entries(
        side=OrderSide.BUY,
        symbol="BTCUSDT",
        quote_currency="USDT",
        price=Decimal("100.1"),
        quantity=Decimal("0.12345678"),
        fee=Decimal("0.00000001"),
    )
    debits = sum((p.amount for p in postings if p.direction == LedgerDirection.DEBIT), Decimal("0"))
    credits = sum(
        (p.amount for p in postings if p.direction == LedgerDirection.CREDIT), Decimal("0")
    )
    assert debits == credits


def test_decimal_precision_test():
    from crypto_trader.domain.money import D, format_decimal

    total = D("0.1") + D("0.2")
    assert format_decimal(total) == "0.3"
    assert format_decimal(D("0.12345678") * D("2")) == "0.24691356"
    with pytest.raises(DecimalError):
        D(0.1)


async def test_dual_engine_lease_test(database):
    leases = LeaseManager(database.session_factory)
    first = await leases.acquire("exec", "engine_a", 30)
    second = await leases.acquire("exec", "engine_b", 30)
    assert first is not None and second is None
    assert await leases.is_held("exec", first.token)


async def test_stale_market_data_execution_block_test(database):
    sim = SimulatedExchangeAdapter()
    await sim.connect()
    engine = make_paper_engine(
        database,
        simulator=sim,
        market_data_max_age_seconds=0.001,
        orderbook_max_age_seconds=0.001,
    )
    await engine.start()
    await engine.market_data.ingest_snapshot(
        "BTCUSDT",
        1,
        [(Decimal("99"), Decimal("1"))],
        [(Decimal("101"), Decimal("1"))],
    )
    await asyncio.sleep(0.01)
    decision = await engine.process_signal(_signal())
    order = await engine.order_manager.get_by_client("sig_chaos")
    assert order is None
    # process_signal returns the FINAL outcome truthfully: the authority
    # HOLD is surfaced (risk stage approved; both stages are in the audit).
    assert decision.decision.value == "HOLD"
    await engine.stop()


async def test_reconciliation_mismatch_test(database):
    sim = SimulatedExchangeAdapter(initial_balances={"USDT": Decimal("10000")})
    await sim.connect()
    engine = make_paper_engine(database, simulator=sim)
    await engine.start()
    # deliberately diverge exchange balance
    sim.balances["USDT"] = Decimal("9999")
    report = await engine.reconciliation.reconcile(sim)
    assert report.ok is False
    assert report.halt is True
    await engine.stop()


async def test_kill_switch_test(database):
    engine = make_paper_engine(database)
    await engine.start()
    engine.risk_engine.kill_switch.engage("chaos test")
    decision = await engine.process_signal(_signal())
    assert decision.reason == "GLOBAL_KILL_SWITCH"
    assert await engine.order_manager.get_by_client("sig_chaos") is None
    await engine.stop()


async def test_database_integration_test(database):
    expected = {
        "engine_runs",
        "runtime_leases",
        "orders",
        "order_events",
        "fills",
        "trades",
        "ledger_entries",
        "accounts_projection",
        "positions_projection",
        "market_snapshots",
        "reconciliation_runs",
        "risk_decisions",
        "audit_events",
    }
    assert expected.issubset(set(Base.metadata.tables.keys()))
    orders = Base.metadata.tables["orders"]
    fills = Base.metadata.tables["fills"]
    assert any(
        isinstance(c, __import__("sqlalchemy", fromlist=["UniqueConstraint"]).UniqueConstraint)
        for c in orders.constraints
    )
    assert any(
        isinstance(c, __import__("sqlalchemy", fromlist=["UniqueConstraint"]).UniqueConstraint)
        for c in fills.constraints
    )
