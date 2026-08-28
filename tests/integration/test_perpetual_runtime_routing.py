"""Real paper-perpetual runtime routing tests.

These tests exercise the full TradingEngine.process_signal -> RiskEngine ->
ExecutionAuthority -> PerpetualPaperEngine path. No ORM position fixtures; SHORT
positions are created through the real paper runtime.
"""

import asyncio
from decimal import Decimal

from crypto_trader.config import Settings
from crypto_trader.domain.enums import (
    ExecutionDecision,
    MarketType,
    OrderSide,
    OrderType,
    PositionSide,
)
from crypto_trader.domain.models import SignalIntent
from crypto_trader.runtime.bootstrap import build_system
from crypto_trader.runtime.execution_symbols import reference_symbol_for

PERP = "BTCUSDT_PERP"


async def _wait_for_spot(bundle, symbol, predicate, timeout_seconds=3.0, interval=0.01):
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        positions = await bundle.portfolio.get_positions()
        if predicate(positions.get(symbol)):
            return positions
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(
                f"spot {symbol} did not reach expected state within {timeout_seconds}s"
            )
        await asyncio.sleep(interval)


async def _make_bundle(database, auto_start=True):
    settings = Settings(
        _env_file=None,
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        database_url=database.url,
        auto_start_runtime=False,
        paper_mode="PAPER_SYNTHETIC",
        paper_initial_equity="100000",
        engine_tick_seconds=3600,
        reconciliation_interval_seconds=3600,
        run_lease_renew_interval_seconds=3600,
    )
    bundle = await build_system(settings)
    if auto_start:
        await bundle.engine.start()
    return bundle


async def _seed_book(bundle, symbol=PERP, price="100"):
    # Perpetual orders are marked against the REAL reference market book.
    await bundle.market_data.ingest_snapshot(
        reference_symbol_for(symbol),
        1,
        [(Decimal(price), Decimal("10"))],
        [(Decimal(price) + 1, Decimal("10"))],
    )


def _perp_signal(side, qty, *, position_side, reduce_only, signal_id="sig"):
    return SignalIntent(
        signal_id=signal_id,
        strategy_id="ai_brain",
        symbol=PERP,
        side=side,
        quantity=qty,
        order_type=OrderType.MARKET,
        reason="test",
        market_type=MarketType.PERPETUAL,
        position_side=position_side,
        reduce_only=reduce_only,
    )


async def _perp_position(bundle):
    state = await bundle.engine.perpetual_engine.load_state()
    return state.positions.get(PERP)


# TEST A: SHORT OPEN
async def test_short_open_creates_short_position(database):
    bundle = await _make_bundle(database)
    await _seed_book(bundle)
    decision = await bundle.engine.process_signal(
        _perp_signal(OrderSide.SELL, "1.0", position_side=PositionSide.SHORT, reduce_only=False)
    )
    assert decision.decision == ExecutionDecision.APPROVE
    pos = await _perp_position(bundle)
    assert pos is not None and pos.side == PositionSide.SHORT
    assert abs(pos.quantity) == Decimal("1")
    await bundle.engine.stop()
    await bundle.database.close()


# TEST B: SHORT ADD
async def test_short_add_increases_short_position(database):
    bundle = await _make_bundle(database)
    await _seed_book(bundle)
    await bundle.engine.process_signal(
        _perp_signal(
            OrderSide.SELL,
            "1.0",
            position_side=PositionSide.SHORT,
            reduce_only=False,
            signal_id="a",
        )
    )
    decision = await bundle.engine.process_signal(
        _perp_signal(
            OrderSide.SELL,
            "0.5",
            position_side=PositionSide.SHORT,
            reduce_only=False,
            signal_id="b",
        )
    )
    assert decision.decision == ExecutionDecision.APPROVE
    pos = await _perp_position(bundle)
    assert pos.side == PositionSide.SHORT
    assert abs(pos.quantity) == Decimal("1.5")
    await bundle.engine.stop()
    await bundle.database.close()


# TEST C: SHORT HOLD -> zero order
async def test_short_hold_zero_order(database):
    bundle = await _make_bundle(database)
    await _seed_book(bundle)
    await bundle.engine.process_signal(
        _perp_signal(OrderSide.SELL, "1.0", position_side=PositionSide.SHORT, reduce_only=False)
    )
    before = await bundle.order_manager.count_open()
    bundle.ai_bridge.thesis_overrides[PERP] = "THESIS_INTACT"
    await bundle.ai_bridge.evaluate_active_positions(bundle.engine, bundle.portfolio)
    after = await bundle.order_manager.count_open()
    assert after == before
    decisions = bundle.ai_bridge.decision_history
    assert any(d["symbol"] == PERP and d["action"] == "HOLD" for d in decisions)
    await bundle.engine.stop()
    await bundle.database.close()


# TEST D: SHORT REDUCE
async def test_short_reduce_partial(database):
    bundle = await _make_bundle(database)
    await _seed_book(bundle)
    await bundle.engine.process_signal(
        _perp_signal(OrderSide.SELL, "1.0", position_side=PositionSide.SHORT, reduce_only=False)
    )
    decision = await bundle.engine.process_signal(
        _perp_signal(
            OrderSide.BUY,
            "0.4",
            position_side=PositionSide.SHORT,
            reduce_only=True,
            signal_id="r",
        )
    )
    assert decision.decision == ExecutionDecision.APPROVE
    pos = await _perp_position(bundle)
    assert pos.side == PositionSide.SHORT
    assert abs(pos.quantity) == Decimal("0.6")
    await bundle.engine.stop()
    await bundle.database.close()


# TEST E: SHORT EXIT -> FLAT
async def test_short_exit_flat(database):
    bundle = await _make_bundle(database)
    await _seed_book(bundle)
    await bundle.engine.process_signal(
        _perp_signal(OrderSide.SELL, "1.0", position_side=PositionSide.SHORT, reduce_only=False)
    )
    decision = await bundle.engine.process_signal(
        _perp_signal(
            OrderSide.BUY,
            "1.0",
            position_side=PositionSide.SHORT,
            reduce_only=True,
            signal_id="x",
        )
    )
    assert decision.decision == ExecutionDecision.APPROVE
    pos = await _perp_position(bundle)
    assert pos is None or pos.is_flat
    await bundle.engine.stop()
    await bundle.database.close()


# TEST F: SHORT NEVER REVERSES
async def test_short_reduce_never_reverses(database):
    bundle = await _make_bundle(database)
    await _seed_book(bundle)
    await bundle.engine.process_signal(
        _perp_signal(OrderSide.SELL, "1.0", position_side=PositionSide.SHORT, reduce_only=False)
    )
    decision = await bundle.engine.process_signal(
        _perp_signal(
            OrderSide.BUY,
            "1.2",
            position_side=PositionSide.SHORT,
            reduce_only=True,
            signal_id="f",
        )
    )
    assert decision.decision == ExecutionDecision.REJECT
    pos = await _perp_position(bundle)
    assert pos.side == PositionSide.SHORT
    assert abs(pos.quantity) == Decimal("1")
    await bundle.engine.stop()
    await bundle.database.close()


# TEST G: LONG NEVER REVERSES
async def test_long_reduce_never_reverses(database):
    bundle = await _make_bundle(database)
    await _seed_book(bundle)
    await bundle.engine.process_signal(
        _perp_signal(OrderSide.BUY, "1.0", position_side=PositionSide.LONG, reduce_only=False)
    )
    decision = await bundle.engine.process_signal(
        _perp_signal(
            OrderSide.SELL,
            "1.2",
            position_side=PositionSide.LONG,
            reduce_only=True,
            signal_id="g",
        )
    )
    assert decision.decision == ExecutionDecision.REJECT
    pos = await _perp_position(bundle)
    assert pos.side == PositionSide.LONG
    assert abs(pos.quantity) == Decimal("1")
    await bundle.engine.stop()
    await bundle.database.close()


# TEST H: SPOT CANNOT SHORT
async def test_spot_cannot_short(database):
    bundle = await _make_bundle(database)
    await _seed_book(bundle, "BTCUSDT")
    # open a spot long of 0.5
    open_signal = SignalIntent(
        signal_id="spot_open",
        strategy_id="test",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity="0.5",
        order_type=OrderType.MARKET,
        reason="open",
    )
    await bundle.engine.process_signal(open_signal)
    await _wait_for_spot(
        bundle, "BTCUSDT", lambda p: p is not None and p.quantity >= Decimal("0.5")
    )
    sell_signal = SignalIntent(
        signal_id="spot_sell",
        strategy_id="test",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        quantity="1.0",
        order_type=OrderType.MARKET,
        reason="oversell",
    )
    decision = await bundle.engine.process_signal(sell_signal)
    assert decision.decision == ExecutionDecision.REJECT
    positions = await bundle.portfolio.get_positions()
    assert positions["BTCUSDT"].quantity == Decimal("0.5")  # never negative
    await bundle.engine.stop()
    await bundle.database.close()


# TEST I: REDUCE_ONLY FULL PROPAGATION (typed fields persisted end-to-end)
async def test_reduce_only_full_propagation(database):
    bundle = await _make_bundle(database)
    await _seed_book(bundle)
    await bundle.engine.process_signal(
        _perp_signal(OrderSide.SELL, "1.0", position_side=PositionSide.SHORT, reduce_only=False)
    )
    signal = _perp_signal(
        OrderSide.BUY, "0.4", position_side=PositionSide.SHORT, reduce_only=True, signal_id="prop"
    )
    decision = await bundle.engine.process_signal(signal)
    assert decision.decision == ExecutionDecision.APPROVE
    order = await bundle.order_manager.get_by_client(f"ai_brain_{signal.signal_id}")
    assert order is not None
    assert order.reduce_only is True
    assert order.market_type == MarketType.PERPETUAL
    assert order.position_side == PositionSide.SHORT
    await bundle.engine.stop()
    await bundle.database.close()


# TEST J: MIXED LONG (spot) + SHORT (perpetual) multi-position reevaluation
async def test_mixed_spot_long_perpetual_short_reevaluation(database):
    bundle = await _make_bundle(database)
    await _seed_book(bundle, "BTCUSDT")
    await _seed_book(bundle)
    # spot long
    await bundle.engine.process_signal(
        SignalIntent(
            signal_id="spot_long",
            strategy_id="test",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity="0.1",
            order_type=OrderType.MARKET,
            reason="open",
        )
    )
    await _wait_for_spot(bundle, "BTCUSDT", lambda p: p is not None)
    # perpetual short
    await bundle.engine.process_signal(
        _perp_signal(OrderSide.SELL, "1.0", position_side=PositionSide.SHORT, reduce_only=False)
    )
    await bundle.ai_bridge.evaluate_active_positions(bundle.engine, bundle.portfolio)
    symbols = {d["symbol"] for d in bundle.ai_bridge.decision_history}
    assert {"BTCUSDT", PERP} <= symbols
    await bundle.engine.stop()
    await bundle.database.close()


# TEST K: RESTART RECOVERY preserves SHORT side + quantity
async def test_restart_preserves_short(database):
    bundle = await _make_bundle(database)
    await _seed_book(bundle)
    await bundle.engine.process_signal(
        _perp_signal(OrderSide.SELL, "1.0", position_side=PositionSide.SHORT, reduce_only=False)
    )
    await bundle.engine.stop()

    bundle2 = await _make_bundle(database, auto_start=False)
    pos = await _perp_position(bundle2)
    assert pos is not None and pos.side == PositionSide.SHORT
    assert abs(pos.quantity) == Decimal("1")
    await bundle2.database.close()
    await bundle.database.close()


# TEST L: PERPETUAL_REFERENCE_PRICE_UNAVAILABLE -> no order, no fake 100 fill
async def test_perpetual_price_unavailable_blocks_entry(database):
    bundle = await _make_bundle(database)
    # Deliberately DO NOT seed the reference BTCUSDT book.
    decision = await bundle.engine.process_signal(
        _perp_signal(OrderSide.SELL, "1.0", position_side=PositionSide.SHORT, reduce_only=False)
    )
    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "PERPETUAL_REFERENCE_PRICE_UNAVAILABLE"
    orders = await bundle.order_manager.list_all(limit=10)
    assert orders == []
    state = await bundle.engine.perpetual_engine.load_state()
    assert state.positions.get(PERP) is None or state.positions[PERP].is_flat
    await bundle.engine.stop()
    await bundle.database.close()


# TEST M: perpetual open/close persist canonical Order + Fill records and
# never post SPOT TRADE ledger entries (FuturesLedger is the sole settlement).
async def test_perpetual_fill_persistence_and_single_settlement(database):
    from sqlalchemy import select

    from crypto_trader.persistence.models import FillORM, LedgerEntryORM

    bundle = await _make_bundle(database)
    await _seed_book(bundle)
    await bundle.engine.process_signal(
        _perp_signal(
            OrderSide.SELL,
            "1.0",
            position_side=PositionSide.SHORT,
            reduce_only=False,
        )
    )
    await bundle.engine.process_signal(
        _perp_signal(
            OrderSide.BUY,
            "1.0",
            position_side=PositionSide.SHORT,
            reduce_only=True,
            signal_id="x",
        )
    )
    from crypto_trader.config import get_settings
    from crypto_trader.runtime.exploration_analytics import exploration_status

    status = await exploration_status(database.session_factory, get_settings())
    assert status["progress"]["completed_short"] == 1
    assert status["progress"]["completed_long"] == 0

    async with database.session_factory() as session:
        fill_rows = (
            (
                await session.execute(
                    select(FillORM).order_by(FillORM.timestamp.asc())
                )
            )
            .scalars()
            .all()
        )
        assert len(fill_rows) == 2
        assert all(
            f.payload_json and f.payload_json.get("market_type") == "PERPETUAL"
            for f in fill_rows
        )
        order = await bundle.order_manager.get_by_client(
            fill_rows[0].client_order_id or ""
        )
        assert order is not None and order.status.value == "FILLED"
        ledger_rows = (
            (
                await session.execute(
                    select(LedgerEntryORM).where(
                        LedgerEntryORM.order_id == order.internal_order_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert ledger_rows
        assert all(
            not (row.entry_type or "").startswith("TRADE") for row in ledger_rows
        )
    await bundle.engine.stop()
    await bundle.database.close()


# TEST N: duplicate entry gate sees PERPETUAL state via provider
async def test_perpetual_position_provider_blocks_duplicate_entry():
    from datetime import UTC, datetime

    from crypto_trader.domain.models import Account
    from crypto_trader.market_data.orderbook import OrderBook
    from crypto_trader.runtime.chief_trader_strategy import ChiefTraderStrategyAdapter
    from crypto_trader.strategy.base import StrategyContext

    book = OrderBook(symbol="BTCUSDT", exchange="test")
    book.apply_snapshot(1, [(Decimal("100"), Decimal("1"))], [(Decimal("101"), Decimal("1"))])
    ctx = StrategyContext(
        symbol="BTCUSDT",
        book=book,
        account=Account(equity=Decimal("100000")),
        positions={},
        clock_time=datetime(2026, 8, 28, tzinfo=UTC),
        mark_price=Decimal("100"),
    )

    class FakeProvider:
        name = "fake"
        calls = 0

        def healthy(self):
            return True

        def route_ready(self):
            return True

        async def complete_json(self, *, prompt, temperature=0.2, timeout_seconds=30.0, retries=2):
            from crypto_trader.llm_chief.provider import LLMResponse

            self.calls += 1
            return LLMResponse("{}", self.name, "fake", 0, parsed_json={}, ok=True)

    adapter = ChiefTraderStrategyAdapter(
        min_decision_interval_seconds=0.0,
        decision_context_provider=None,
        perpetual_position_provider=lambda: True,
    )
    provider = FakeProvider()
    adapter.provider = provider
    signals = await adapter.on_market_data(ctx)
    assert signals == []
    assert provider.calls == 0  # duplicate gate before LLM
    adapter.perpetual_position_provider = lambda: False
    await adapter.on_market_data(ctx)
    assert provider.calls == 0  # no context provider -> fail closed, no LLM


# TEST O: backend position/risk truth includes BTCUSDT_PERP SHORT (not empty)
async def test_positions_and_risk_show_perpetual_short(database):
    from fastapi.testclient import TestClient

    from crypto_trader.api.app import create_app

    bundle = await _make_bundle(database)
    await _seed_book(bundle)
    await bundle.engine.process_signal(
        _perp_signal(OrderSide.SELL, "1.0", position_side=PositionSide.SHORT, reduce_only=False)
    )
    client = TestClient(create_app(bundle.app_state))
    positions = client.get("/positions").json()
    assert PERP in positions
    assert positions[PERP]["market_type"] == "PERPETUAL"
    assert positions[PERP]["side"] == "SHORT"
    risk = client.get("/risk").json()
    assert risk["metrics"]["flat"] is False
    assert risk["metrics"]["effective_leverage"] != "0"
    await bundle.engine.stop()
    await bundle.database.close()
