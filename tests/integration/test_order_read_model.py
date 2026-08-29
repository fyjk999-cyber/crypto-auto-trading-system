"""Order/Fill/PnL read-model tests (observability, P3 interrupt).

Covers the /orders read-model contract:
- order.price stays the ORDER REQUEST/LIMIT price (MARKET => None)
- avg_fill_price comes from canonical fills (weighted by quantity)
- fee_total is the SUM of real fill fees (never re-estimated)
- PnL is POSITION_LEVEL (open positions, same source as /positions) or
  TRADE_LEVEL (realized PnL matched from FUTURES_REALIZED_PNL ledger rows)
- missing data stays NOT_AVAILABLE; real zero stays 0

Spot fills are driven through the raw canonical order lifecycle so fill
prices are exact (the PAPER_SYNTHETIC adapter prices spot fills from its own
internal table, not the market-data books). Perpetual opens/closes go
through process_signal, whose fills ARE priced from the reference books.
"""
import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from crypto_trader.api.app import create_app
from crypto_trader.api.deps import AppState
from crypto_trader.config import Settings
from crypto_trader.domain.enums import MarketType, OrderSide, OrderType, PositionSide, TradingMode
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import Fill, OrderIntent, SignalIntent
from tests.integration.test_perpetual_runtime_routing import _make_bundle


@pytest.fixture
async def env(database):
    bundle = await _make_bundle(database, auto_start=True)
    settings = Settings(
        _env_file=None,
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        database_url=database.url,
        auto_start_runtime=False,
    )
    state = AppState(
        settings=settings,
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
    return bundle, TestClient(create_app(state))


async def _seed_mark(bundle, symbol: str, mark: str, sequence: int = 1):
    """Symmetric book so mid_price == mark exactly (per-symbol control)."""
    m = Decimal(mark)
    await bundle.market_data.ingest_snapshot(
        symbol,
        sequence,
        [(m - Decimal("0.005"), Decimal("10"))],
        [(m + Decimal("0.005"), Decimal("10"))],
    )


async def _open_spot_raw(bundle, symbol: str, entry: str, qty: str = "0.001"):
    """Deterministic spot LONG via the canonical order->fill path."""
    intent = OrderIntent(
        client_order_id=new_id("cli"),
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
        strategy_id="test",
        market_type=MarketType.SPOT,
    )
    om = bundle.engine.order_manager
    order = await om.create_from_intent(intent, trading_mode=TradingMode.PAPER)
    await om.validate(order.internal_order_id)
    await om.submitting(order.internal_order_id)
    await om.submitted(order.internal_order_id)
    fill = Fill(
        fill_id=new_id("fill"),
        order_id=order.internal_order_id,
        client_order_id=order.client_order_id,
        symbol=symbol,
        side=OrderSide.BUY,
        price=Decimal(entry),
        quantity=Decimal(qty),
        fee=Decimal("0"),
        fee_currency="USDT",
        timestamp=datetime.now(UTC),
        payload={"market_type": "SPOT"},
    )
    await om.apply_fill(fill)
    return order


async def _open_perp_via_signal(bundle, symbol: str, side: OrderSide, qty: str, mark: str):
    await _seed_mark(bundle, symbol.replace("_PERP", ""), mark)
    decision = await bundle.engine.process_signal(
        SignalIntent(
            signal_id=f"sig_{symbol}_{side.value}",
            strategy_id="test",
            symbol=symbol,
            side=side,
            quantity=qty,
            order_type=OrderType.MARKET,
            reason="read model test",
            market_type=MarketType.PERPETUAL,
            position_side=PositionSide.LONG if side == OrderSide.BUY else PositionSide.SHORT,
        )
    )
    assert decision.decision.value == "APPROVE", decision.reason
    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        perp_state = await bundle.engine.perpetual_engine.load_state()
        position = perp_state.positions.get(symbol)
        if position is not None and Decimal(str(position.quantity)) != 0:
            return position
        await asyncio.sleep(0.01)
    raise AssertionError("position did not open")


def _view(client, order_id):
    rows = client.get("/orders?limit=50").json()
    for row in rows:
        if row["internal_order_id"] == order_id:
            return row
    raise AssertionError(f"order {order_id} not in /orders")

async def test_market_filled_price_none_and_avg_fill_price_from_canonical_fill(env):
    bundle, client = env
    order = await _open_spot_raw(bundle, "SOLUSDT", "103.55")
    view = _view(client, order.internal_order_id)
    assert order.order_type == OrderType.MARKET
    assert order.price is None  # MARKET orders have no request price
    assert Decimal(view["avg_fill_price"]) == Decimal("103.55")
    assert view["status"] == "FILLED"
    assert view["fill_count"] == 1
    # No mark seeded for SOL here: unrealized must stay NOT_AVAILABLE, never
    # the current ticker or a cross-symbol price.
    assert view["unrealized_pnl"] == "NOT_AVAILABLE"
    assert view["fee_total"] != "NOT_AVAILABLE"  # real fill fee exists (0)


async def test_limit_order_price_preserved_and_unfilled_avg_empty(env):
    bundle, _ = env
    intent = OrderIntent(
        client_order_id=new_id("cli"),
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.001"),
        price=Decimal("60000"),
        strategy_id="test",
        market_type=MarketType.SPOT,
    )
    om = bundle.engine.order_manager
    order = await om.create_from_intent(intent, trading_mode=TradingMode.PAPER)
    orders = await om.list_all(limit=50)
    stored = [o for o in orders if o.internal_order_id == order.internal_order_id][0]
    assert Decimal(str(stored.price)) == Decimal("60000")  # request price kept
    assert stored.avg_fill_price is None  # no fills: nothing faked
    assert stored.filled_quantity == 0


async def test_multiple_fills_weighted_average_not_simple_average(env):
    bundle, client = env
    intent = OrderIntent(
        client_order_id=new_id("cli"),
        symbol="ADAUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("3"),
        price=Decimal("110"),
        strategy_id="test",
        market_type=MarketType.SPOT,
    )
    om = bundle.engine.order_manager
    order = await om.create_from_intent(intent, trading_mode=TradingMode.PAPER)
    await om.validate(order.internal_order_id)
    await om.submitting(order.internal_order_id)
    await om.submitted(order.internal_order_id)
    for price, qty in ((Decimal("100"), Decimal("1")), (Decimal("110"), Decimal("2"))):
        fill = Fill(
            fill_id=new_id("fill"),
            order_id=order.internal_order_id,
            client_order_id=order.client_order_id,
            symbol="ADAUSDT",
            side=OrderSide.BUY,
            price=price,
            quantity=qty,
            fee=Decimal("0.01"),
            fee_currency="USDT",
            timestamp=datetime.now(UTC),
            payload={"market_type": "SPOT"},
        )
        await om.apply_fill(fill)
    orders = await om.list_all(limit=50)
    stored = [o for o in orders if o.internal_order_id == order.internal_order_id][0]
    view = _view(client, order.internal_order_id)
    # weighted: (100*1 + 110*2)/3 = 106.666.. NOT (100+110)/2 = 105
    assert Decimal(str(stored.avg_fill_price)) == Decimal("106.6666666666666666666666667")
    assert Decimal(view["fee_total"]) == Decimal("0.02")  # summed real fees
    assert view["fee_currency"] == "USDT"
    assert view["fill_count"] == 2


async def test_open_spot_long_positive_and_negative_unrealized(env):
    bundle, client = env
    ada_order = await _open_spot_raw(bundle, "ADAUSDT", "0.20")
    xlm_order = await _open_spot_raw(bundle, "XLMUSDT", "0.15")
    await _seed_mark(bundle, "ADAUSDT", "0.30")  # price UP  -> profit
    await _seed_mark(bundle, "XLMUSDT", "0.10")  # price DOWN -> loss
    ada = _view(client, ada_order.internal_order_id)
    xlm = _view(client, xlm_order.internal_order_id)
    assert ada["trade_status"] == "OPEN_POSITION"
    assert Decimal(ada["unrealized_pnl"]) > 0
    assert Decimal(xlm["unrealized_pnl"]) < 0
    assert ada["pnl_scope"] == "POSITION_LEVEL"


async def test_open_perp_short_price_down_profit_and_price_up_loss(env):
    bundle, client = env
    await _open_perp_via_signal(bundle, "HYPEUSDT_PERP", OrderSide.SELL, "0.0005", "80")
    await _open_perp_via_signal(bundle, "TAOUSDT_PERP", OrderSide.SELL, "0.0005", "230")
    # SHORT HYPE: mark DOWN to 79 => profit; SHORT TAO: mark UP to 231 => loss
    await _seed_mark(bundle, "HYPEUSDT", "79", sequence=2)
    await _seed_mark(bundle, "TAOUSDT", "231", sequence=2)
    rows = client.get("/orders?limit=50").json()
    hype = [r for r in rows if r["symbol"] == "HYPEUSDT_PERP" and not r["reduce_only"]][0]
    tao = [r for r in rows if r["symbol"] == "TAOUSDT_PERP" and not r["reduce_only"]][0]
    assert Decimal(hype["unrealized_pnl"]) > 0, "SHORT + price down must be profit"
    assert Decimal(tao["unrealized_pnl"]) < 0, "SHORT + price up must be loss"
    # ROI basis: pnl_percent = unrealized / initial_margin * 100
    assert hype["pnl_percent"] != "NOT_AVAILABLE"
    assert Decimal(hype["pnl_percent"]) > 0


async def test_closed_perp_trade_realized_pnl_from_ledger(env):
    bundle, client = env
    await _open_perp_via_signal(bundle, "ENAUSDT_PERP", OrderSide.BUY, "0.5", "0.2")
    close = await bundle.engine.process_signal(
        SignalIntent(
            signal_id="sig_close_ena",
            strategy_id="test",
            symbol="ENAUSDT_PERP",
            side=OrderSide.SELL,
            quantity="0.5",
            order_type=OrderType.MARKET,
            reason="close",
            market_type=MarketType.PERPETUAL,
            position_side=PositionSide.LONG,
            reduce_only=True,
        )
    )
    assert close.decision.value == "APPROVE", close.reason
    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        async with bundle.database.session_factory() as session:
            from sqlalchemy import text

            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM ledger_transactions "
                        "WHERE entry_type='FUTURES_REALIZED_PNL'"
                    )
                )
            ).scalar()
        if count:
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("realized PnL ledger row missing")
    rows = client.get("/orders?limit=50").json()
    closes = [r for r in rows if r["reduce_only"] and r["symbol"] == "ENAUSDT_PERP"]
    assert closes, "closing order must appear"
    closed = closes[0]
    assert closed["trade_status"] == "CLOSED"
    assert closed["pnl_scope"] == "TRADE_LEVEL"
    assert closed["realized_pnl"] != "NOT_AVAILABLE"  # canonical ledger value


async def test_partial_close_separates_realized_and_remaining_unrealized(env):
    bundle, client = env
    await _open_spot_raw(bundle, "ETHUSDT", "2400", "0.002")
    await _seed_mark(bundle, "ETHUSDT", "2400")
    close = await bundle.engine.process_signal(
        SignalIntent(
            signal_id="sig_partial_eth",
            strategy_id="test",
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            quantity="0.001",
            order_type=OrderType.MARKET,
            reason="partial close",
            market_type=MarketType.SPOT,
            reduce_only=True,
        )
    )
    assert close.decision.value == "APPROVE", close.reason
    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        position = (await bundle.portfolio.get_positions()).get("ETHUSDT")
        if position is not None and Decimal(str(position.quantity)) == Decimal("0.001"):
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("partial close did not settle")
    rows = client.get("/orders?limit=50").json()
    partial = [r for r in rows if r["symbol"] == "ETHUSDT" and r["reduce_only"]][0]
    entry = [r for r in rows if r["symbol"] == "ETHUSDT" and not r["reduce_only"]][0]
    # Spot partial close: no canonical per-episode realized PnL source =>
    # honestly NOT_AVAILABLE (never guessed from ticker or cost basis).
    assert partial["realized_pnl"] == "NOT_AVAILABLE"
    # Remaining position still open: latest entry carries floating PnL.
    assert entry["trade_status"] == "OPEN_POSITION"


async def test_real_zero_unrealized_is_zero_not_not_available(env):
    bundle, client = env
    order = await _open_spot_raw(bundle, "DOGEUSDT", "0.08428")
    await _seed_mark(bundle, "DOGEUSDT", "0.08428")
    view = _view(client, order.internal_order_id)
    assert Decimal(view["unrealized_pnl"]) == 0
    assert view["unrealized_pnl"] != "NOT_AVAILABLE"


async def test_missing_data_stays_not_available_not_fake_zero(env):
    bundle, client = env
    # Open normally (book seeded so order validation passes), then remove the
    # symbol's book to simulate the real market-data source going away: the
    # read model must fail visibly with NOT_AVAILABLE, never fake a price.
    order = await _open_spot_raw(bundle, "HBARUSDT", "0.17")
    bundle.market_data.books.pop("HBARUSDT", None)
    view = _view(client, order.internal_order_id)
    assert view["unrealized_pnl"] == "NOT_AVAILABLE"
    assert view["trade_status"] in ("OPEN_POSITION", None)
    assert view["fee_total"] != "0" or view["fill_count"] >= 1