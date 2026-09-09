from datetime import UTC, datetime
from decimal import Decimal

import pytest

from crypto_trader.domain.enums import (
    ExchangeEventType,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    TradingMode,
)
from crypto_trader.domain.errors import OrderRejected, RateLimited, UnknownExecutionState
from crypto_trader.domain.models import Instrument, Order
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter


def make_order(cid="c1", qty="0.1", price="100"):
    now = datetime.now(UTC)
    return Order(
        internal_order_id="ord_1",
        client_order_id=cid,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price=price,
        quantity=qty,
        status=OrderStatus.SUBMITTING,
        trading_mode=TradingMode.PAPER,
        strategy_id="test",
        created_at=now,
        updated_at=now,
    )


async def test_simulator_connects_and_implements_contract():
    sim = SimulatedExchangeAdapter()
    await sim.connect()
    sim.seed_book("BTCUSDT")
    book = await sim.get_orderbook("BTCUSDT")
    assert book.sequence is not None
    ticker = await sim.get_ticker("BTCUSDT")
    assert Decimal(ticker["ask"]) > Decimal(ticker["bid"])


async def test_non_marketable_limit_rests_open():
    sim = SimulatedExchangeAdapter()
    await sim.connect()
    sim.seed_book("BTCUSDT")
    events = []
    await sim.subscribe_order_updates(lambda e: events.append(e) or _noop())
    order = await sim.submit_order(make_order(price="1"))
    assert order.status == OrderStatus.ACKNOWLEDGED or order.status == OrderStatus.OPEN
    assert [e.event_type for e in events] == [
        ExchangeEventType.ORDER_ACK,
        ExchangeEventType.ORDER_OPENED,
    ]


async def test_marketable_limit_fills_and_updates_balance():
    sim = SimulatedExchangeAdapter(initial_balances={"USDT": Decimal("10000")})
    await sim.connect()
    sim.seed_book("BTCUSDT")
    order = await sim.submit_order(make_order(qty="0.5", price="101"))
    assert order.status == OrderStatus.FILLED
    balances = {b.currency: b.total for b in await sim.get_balances()}
    assert balances["BTC"] == Decimal("0.5")
    # ask 100.05 * 0.5 = 50.025; fee 0.050025 -> USDT left 9949.924975
    assert balances["USDT"] == Decimal("9949.924975")
    positions = await sim.get_positions()
    assert positions[0].quantity == Decimal("0.5")


async def test_linear_perp_fee_uses_canonical_contract_notional():
    instrument = Instrument(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        tick_size="0.1",
        step_size="1",
        min_qty="1",
        min_notional="0.01",
        price_precision=1,
        quantity_precision=0,
        exchange="OKX",
        instrument_type="LINEAR_PERP",
        contract_size="0.01",
        contract_multiplier="1",
    )
    sim = SimulatedExchangeAdapter(
        initial_balances={"USDT": Decimal("1000")}, instruments=[instrument]
    )
    await sim.connect()
    sim.seed_book("BTCUSDT")
    events = []
    await sim.subscribe_order_updates(lambda event: events.append(event) or _noop())
    order = make_order(qty="2", price="101").model_copy(
        update={
            "metadata": {
                "instrument_type": "LINEAR_PERP",
                "contract_size": "0.01",
                "contract_multiplier": "1",
            }
        }
    )
    await sim.submit_order(order)
    fills = [
        event
        for event in events
        if event.event_type
        in {ExchangeEventType.ORDER_PARTIALLY_FILLED, ExchangeEventType.ORDER_FILLED}
    ]
    # One contract fills at 100.05 and one at 100.10. Both use 0.01 contract size.
    assert sum((Decimal(event.payload["fee"]) for event in fills), Decimal("0")) == Decimal(
        "0.0020015"
    )
    balances = {row.currency: row.total for row in await sim.get_balances()}
    assert balances["USDT"] == Decimal("999.9979985")


async def test_fill_before_ack_ordering():
    sim = SimulatedExchangeAdapter()
    await sim.connect()
    sim.seed_book("BTCUSDT")
    sim.fill_before_ack = True
    events = []
    await sim.subscribe_order_updates(lambda e: events.append(e.event_type) or _noop())
    order = await sim.submit_order(make_order(qty="0.1", price="101"))
    assert order.status == OrderStatus.FILLED
    assert events == [ExchangeEventType.ORDER_FILLED, ExchangeEventType.ORDER_ACK]


async def test_duplicate_fill_emitted():
    sim = SimulatedExchangeAdapter()
    await sim.connect()
    sim.seed_book("BTCUSDT")
    sim.duplicate_fill = True
    events = []
    await sim.subscribe_order_updates(lambda e: events.append(e) or _noop())
    await sim.submit_order(make_order(qty="0.1", price="101"))
    fill_events = [e for e in events if e.event_type == ExchangeEventType.ORDER_FILLED]
    assert len(fill_events) == 2


async def test_submit_timeout_but_order_created():
    sim = SimulatedExchangeAdapter()
    await sim.connect()
    sim.seed_book("BTCUSDT")
    sim.timeout_but_created = True
    with pytest.raises(UnknownExecutionState):
        await sim.submit_order(make_order())
    # order exists at exchange and can be recovered
    recovered = await sim.get_order("BTCUSDT", "sim_1000")
    assert recovered.exchange_order_id == "sim_1000"
    assert recovered.status == OrderStatus.ACKNOWLEDGED


async def test_cancel_fill_race_fill_wins():
    sim = SimulatedExchangeAdapter()
    await sim.connect()
    sim.seed_book("BTCUSDT")
    sim.cancel_fill_race = True
    order = await sim.submit_order(make_order(price="1"))
    order = await sim.cancel_order("BTCUSDT", order.exchange_order_id)
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == order.quantity


async def test_normal_cancel():
    sim = SimulatedExchangeAdapter()
    await sim.connect()
    sim.seed_book("BTCUSDT")
    order = await sim.submit_order(make_order(price="1"))
    canceled = await sim.cancel_order("BTCUSDT", order.exchange_order_id)
    assert canceled.status == OrderStatus.CANCELLED


async def test_fault_injection_reject_and_rate_limit():
    sim = SimulatedExchangeAdapter()
    await sim.connect()
    sim.seed_book("BTCUSDT")
    sim.rate_limit_next = True
    with pytest.raises(RateLimited):
        await sim.submit_order(make_order())
    sim.reject_next_order = "test reject"
    with pytest.raises(OrderRejected):
        await sim.submit_order(make_order())


async def test_market_delta_sequence_gap_visible_to_core():
    sim = SimulatedExchangeAdapter()
    await sim.connect()
    sim.seed_book("BTCUSDT")
    events = []
    await sim.subscribe_market_data("BTCUSDT", lambda e: events.append(e) or _noop())
    book = await sim.get_orderbook("BTCUSDT")
    expected_next = book.sequence + 1
    await sim.emit_market_delta("BTCUSDT", [("99", "1")], [("101", "1")])
    assert events[-1].payload["sequence"] == expected_next
    sim.sequence_gap_next_delta = True
    await sim.emit_market_delta("BTCUSDT", [("99", "1")], [("101", "1")])
    assert events[-1].payload["sequence"] > expected_next + 1


async def _noop():
    pass
