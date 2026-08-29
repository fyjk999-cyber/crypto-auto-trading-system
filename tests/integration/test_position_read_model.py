"""Position read-model repair tests (POSITION_MARK_PRICE_BY_SYMBOL etc.).

Contract under test (2026-08-29 HIGH PRIORITY ADDENDUM):
- Every position's mark price comes from THAT symbol's own real market book;
  cross-symbol fallback (ETH inheriting BTC's mark) is forbidden: a missing
  price is "NOT_AVAILABLE", failing visibly.
- SPOT unrealized PnL is computed in the backend read model:
  (real mark - avg_entry) * quantity; leverage/liquidation are
  NOT_APPLICABLE for SPOT.
- PERPETUAL positions reuse the perpetual engine accounting per registered
  contract (LONG/SHORT, contract_size aware).
- Zero-quantity positions never appear in /positions.
- A real zero PnL renders as 0, not NOT_AVAILABLE.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from crypto_trader.api.app import create_app
from crypto_trader.api.deps import AppState
from crypto_trader.config import Settings
from crypto_trader.domain.enums import MarketType, OrderSide, OrderType, PositionSide
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import Fill, OrderIntent, SignalIntent
from tests.integration.test_perpetual_runtime_routing import _make_bundle, _seed_book


async def _wait_for_position(portfolio, symbol: str, timeout_seconds: float = 3.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        positions = await portfolio.get_positions()
        pos = positions.get(symbol)
        if pos is not None and Decimal(str(pos.quantity)) != 0:
            return pos
        await asyncio.sleep(0.02)
    return None


async def _open_spot_position(engine, symbol: str, entry: str, qty: str = "0.001"):
    """Deterministic spot LONG position via the canonical order->fill path
    (the synthetic adapter prices spot fills from its own table, so
    read-model tests drive the order lifecycle with known prices)."""
    from crypto_trader.domain.enums import TradingMode
    from crypto_trader.domain.models import Fill, OrderIntent

    intent = OrderIntent(
        client_order_id=new_id("cli"),
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
        strategy_id="test",
        market_type=MarketType.SPOT,
    )
    order = await engine.order_manager.create_from_intent(
        intent, trading_mode=TradingMode.PAPER
    )
    await engine.order_manager.validate(order.internal_order_id)
    await engine.order_manager.submitting(order.internal_order_id)
    await engine.order_manager.submitted(order.internal_order_id)
    fill = Fill(
        fill_id=new_id("fill"),
        trade_id=new_id("trd"),
        order_id=order.internal_order_id,
        client_order_id=order.client_order_id,
        exchange_order_id=f"paper_test_{new_id('ex')}",
        symbol=symbol,
        side=OrderSide.BUY,
        price=Decimal(entry),
        quantity=Decimal(qty),
        fee=Decimal("0"),
        fee_currency="USDT",
        timestamp=datetime.now(UTC),
        payload={"market_type": MarketType.SPOT.value},
    )
    await engine.order_manager.apply_fill(fill)


async def _seed_mark(bundle, symbol: str, mark: str):
    """Seed a symmetric book so mid_price == mark exactly (per-symbol)."""
    m = Decimal(mark)
    await bundle.market_data.ingest_snapshot(
        symbol,
        1,
        [(m - Decimal("0.005"), Decimal("10"))],
        [(m + Decimal("0.005"), Decimal("10"))],
    )



def _client(state) -> TestClient:
    return TestClient(create_app(state))


def test_spot_mark_price_is_per_symbol_not_global_btc(database):
    """Two spot positions with different marks: each must carry its OWN
    symbol mark; a missing ETH book yields NOT_AVAILABLE, NEVER the BTC mark."""

    async def scenario():
        bundle = await _make_bundle(database, auto_start=True)
        try:
            await _seed_mark(bundle, "SOLUSDT", "103.55")
            await _open_spot_position(bundle.engine, "SOLUSDT", "103.55")
            # ETH position exists but NO ETH book is ingested: its mark must
            # be NOT_AVAILABLE and must never inherit another symbol's price.
            await _open_spot_position(bundle.engine, "ETHUSDT", "2435")
            state = AppState(
                settings=Settings(
                    app_env="test",
                    trading_mode="PAPER",
                    database_url=bundle.database.url,
                ),
                database=bundle.database,
                order_manager=bundle.engine.order_manager,
                ledger=bundle.engine.ledger,
                portfolio=bundle.engine.portfolio,
                audit=bundle.engine.audit,
                risk=bundle.engine.risk_engine,
                market_data=bundle.engine.market_data,
                leases=bundle.engine.lease_manager,
                reconciliation=bundle.engine.reconciliation,
                engine=bundle.engine,
            )
            return state
        finally:
            await bundle.engine.stop()

    state = asyncio.run(scenario())
    client = _client(state)
    data = client.get("/positions").json()
    sol = data.get("SOLUSDT")
    assert sol is not None and sol["market_type"] == "SPOT"
    # Mark = mid of SOL's OWN symmetric book (== the entry price)
    assert Decimal(str(sol["mark_price"])) == Decimal("103.55"), sol
    eth = data.get("ETHUSDT")
    assert eth is not None
    assert eth["mark_price"] == "NOT_AVAILABLE", eth
    assert eth["unrealized_pnl"] == "NOT_AVAILABLE", eth
    # BTC's mark (absent here entirely) can never leak into ETH.


def test_spot_unrealized_pnl_positive_and_negative(database):
    """SPOT LONG: price above entry -> positive PnL; below -> negative; a
    real zero renders as 0, never NOT_AVAILABLE."""

    async def scenario():
        bundle = await _make_bundle(database, auto_start=True)
        try:
            await _open_spot_position(bundle.engine, "ADAUSDT", "0.20")
            await _open_spot_position(bundle.engine, "XLMUSDT", "0.15")
            # Price UP for ADA, DOWN for XLM (symmetric books: mid == mark).
            await _seed_mark(bundle, "ADAUSDT", "0.30")
            await _seed_mark(bundle, "XLMUSDT", "0.10")
            state = AppState(
                settings=Settings(
                    app_env="test",
                    trading_mode="PAPER",
                    database_url=bundle.database.url,
                ),
                database=bundle.database,
                order_manager=bundle.engine.order_manager,
                ledger=bundle.engine.ledger,
                portfolio=bundle.engine.portfolio,
                audit=bundle.engine.audit,
                risk=bundle.engine.risk_engine,
                market_data=bundle.engine.market_data,
                leases=bundle.engine.lease_manager,
                reconciliation=bundle.engine.reconciliation,
                engine=bundle.engine,
            )
            return state
        finally:
            await bundle.engine.stop()

    state = asyncio.run(scenario())
    client = _client(state)
    data = client.get("/positions").json()
    ada = data["ADAUSDT"]
    xlm = data["XLMUSDT"]
    assert Decimal(str(ada["unrealized_pnl"])) > 0, ada
    assert Decimal(str(ada["mark_price"])) == Decimal("0.30")
    assert Decimal(str(xlm["unrealized_pnl"])) < 0, xlm
    assert ada["leverage"] == "NOT_APPLICABLE"
    assert ada["liquidation_price"] == "NOT_APPLICABLE"
    # Real zero: a real zero PnL is numeric (NOT_AVAILABLE only for missing
    # real sources); verified in test_real_zero_pnl_is_zero_not_not_available.
    assert ada["unrealized_pnl"] != "NOT_AVAILABLE"


def test_real_zero_pnl_is_zero_not_not_available(database):
    """When the real mark equals the entry price the backend returns a
    numeric 0 PnL (frontend renders $0.00), never NOT_AVAILABLE."""

    async def scenario():
        bundle = await _make_bundle(database, auto_start=True)
        try:
            await _seed_mark(bundle, "DOGEUSDT", "0.08428")
            await _open_spot_position(bundle.engine, "DOGEUSDT", "0.08428")
            state = AppState(
                settings=Settings(
                    app_env="test",
                    trading_mode="PAPER",
                    database_url=bundle.database.url,
                ),
                database=bundle.database,
                order_manager=bundle.engine.order_manager,
                ledger=bundle.engine.ledger,
                portfolio=bundle.engine.portfolio,
                audit=bundle.engine.audit,
                risk=bundle.engine.risk_engine,
                market_data=bundle.engine.market_data,
                leases=bundle.engine.lease_manager,
                reconciliation=bundle.engine.reconciliation,
                engine=bundle.engine,
            )
            return state
        finally:
            await bundle.engine.stop()

    state = asyncio.run(scenario())
    client = _client(state)
    doge = client.get("/positions").json()["DOGEUSDT"]
    assert Decimal(str(doge["unrealized_pnl"])) == 0
    assert doge["unrealized_pnl"] != "NOT_AVAILABLE"


def test_zero_quantity_positions_filtered_from_read_model(database):
    """quantity == 0 rows are history: they must not appear in /positions."""

    async def scenario():
        bundle = await _make_bundle(database, auto_start=True)
        try:
            await _open_spot_position(bundle.engine, "ADAUSDT", "0.5")
            close_intent = OrderIntent(
                client_order_id=new_id("cli"),
                symbol="ADAUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.001"),
                strategy_id="test",
                market_type=MarketType.SPOT,
            )
            from crypto_trader.domain.enums import TradingMode

            close_order = await bundle.engine.order_manager.create_from_intent(
                close_intent, trading_mode=TradingMode.PAPER
            )
            await bundle.engine.order_manager.validate(close_order.internal_order_id)
            await bundle.engine.order_manager.submitting(close_order.internal_order_id)
            await bundle.engine.order_manager.submitted(close_order.internal_order_id)
            await bundle.engine.order_manager.apply_fill(
                Fill(
                    fill_id=new_id("fill"),
                    trade_id=new_id("trd"),
                    order_id=close_order.internal_order_id,
                    client_order_id=close_order.client_order_id,
                    exchange_order_id=f"paper_test_{new_id('ex')}",
                    symbol="ADAUSDT",
                    side=OrderSide.SELL,
                    price=Decimal("0.55"),
                    quantity=Decimal("0.001"),
                    fee=Decimal("0"),
                    fee_currency="USDT",
                    timestamp=datetime.now(UTC),
                    payload={"market_type": MarketType.SPOT.value},
                )
            )
            state = AppState(
                settings=Settings(
                    app_env="test",
                    trading_mode="PAPER",
                    database_url=bundle.database.url,
                ),
                database=bundle.database,
                order_manager=bundle.engine.order_manager,
                ledger=bundle.engine.ledger,
                portfolio=bundle.engine.portfolio,
                audit=bundle.engine.audit,
                risk=bundle.engine.risk_engine,
                market_data=bundle.engine.market_data,
                leases=bundle.engine.lease_manager,
                reconciliation=bundle.engine.reconciliation,
                engine=bundle.engine,
            )
            return state
        finally:
            await bundle.engine.stop()

    state = asyncio.run(scenario())
    client = _client(state)
    data = client.get("/positions").json()
    assert "ADAUSDT" not in data, data
    for row in data.values():
        assert Decimal(str(row["quantity"])) != 0


def test_perpetual_long_and_short_accounting_via_engine(database):
    """PERPETUAL rows reuse the engine accounting: LONG gains when mark
    rises, SHORT gains when mark falls; contract fields are per-symbol."""

    async def scenario():
        bundle = await _make_bundle(database, auto_start=True)
        try:
            await _seed_book(bundle, "HYPEUSDT", "81")
            await bundle.engine.process_signal(
                SignalIntent(
                    signal_id="sig_hype_long",
                    strategy_id="test",
                    symbol="HYPEUSDT_PERP",
                    side=OrderSide.BUY,
                    quantity="0.001",
                    order_type=OrderType.MARKET,
                    reason="perp long",
                    market_type=MarketType.PERPETUAL,
                    position_side=PositionSide.LONG,
                )
            )
            await _wait_for_position(bundle.engine.portfolio, "HYPEUSDT_PERP")
            await _seed_book(bundle, "TAOUSDT", "232")
            await bundle.engine.process_signal(
                SignalIntent(
                    signal_id="sig_tao_short",
                    strategy_id="test",
                    symbol="TAOUSDT_PERP",
                    side=OrderSide.SELL,
                    quantity="0.0005",
                    order_type=OrderType.MARKET,
                    reason="perp short",
                    market_type=MarketType.PERPETUAL,
                    position_side=PositionSide.SHORT,
                )
            )
            await _wait_for_position(bundle.engine.portfolio, "TAOUSDT_PERP")
            # Mark moves: HYPE up (LONG gains), TAO down (SHORT gains).
            await _seed_mark(bundle, "HYPEUSDT", "82.5")
            await _seed_mark(bundle, "TAOUSDT", "230.5")
            state = AppState(
                settings=Settings(
                    app_env="test",
                    trading_mode="PAPER",
                    database_url=bundle.database.url,
                ),
                database=bundle.database,
                order_manager=bundle.engine.order_manager,
                ledger=bundle.engine.ledger,
                portfolio=bundle.engine.portfolio,
                audit=bundle.engine.audit,
                risk=bundle.engine.risk_engine,
                market_data=bundle.engine.market_data,
                leases=bundle.engine.lease_manager,
                reconciliation=bundle.engine.reconciliation,
                engine=bundle.engine,
            )
            return state
        finally:
            await bundle.engine.stop()

    state = asyncio.run(scenario())
    client = _client(state)
    data = client.get("/positions").json()
    hype = data["HYPEUSDT_PERP"]
    tao = data["TAOUSDT_PERP"]
    assert hype["market_type"] == "PERPETUAL" and hype["side"] == "LONG"
    assert tao["side"] == "SHORT"
    assert Decimal(str(hype["unrealized_pnl"])) > 0, hype
    assert Decimal(str(tao["unrealized_pnl"])) > 0, tao
    assert hype["base_asset"] == "HYPE", hype  # per-symbol contract, not BTC
    assert tao["base_asset"] == "TAO", tao
    # mark = mid of each symbol's OWN reference book
    assert Decimal(str(hype["mark_price"])) == Decimal("82.5"), hype
    assert Decimal(str(tao["mark_price"])) == Decimal("230.5"), tao
    assert hype["leverage"] != "NOT_APPLICABLE"
    assert hype["liquidation_price"] != "NOT_APPLICABLE"
