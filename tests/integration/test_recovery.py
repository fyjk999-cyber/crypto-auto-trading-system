from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce, TradingMode
from crypto_trader.domain.models import OrderIntent
from crypto_trader.order.manager import OrderManager
from crypto_trader.runtime.recovery import RecoveryService


class StubRecoveryAdapter:
    """Exchange view that says the submitted order is FILLED."""

    def __init__(self):
        self.view = None

    async def get_order(self, symbol, exchange_order_id):
        return self.view

    async def get_positions(self):
        return []

    async def get_balances(self):
        from crypto_trader.domain.models import Balance

        return [
            Balance(
                currency="USDT", total=Decimal("0"), available=Decimal("0"), frozen=Decimal("0")
            )
        ]


async def test_recovery_never_blind_resubmits_and_applies_exchange_fill(database):
    mgr = OrderManager(database.session_factory)
    intent = OrderIntent(
        client_order_id="c_rec",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price="100",
        quantity="1",
    )
    local = await mgr.create_from_intent(intent, trading_mode=TradingMode.PAPER)
    await mgr.validate(local.internal_order_id)
    await mgr.submitting(local.internal_order_id)
    await mgr.submitted(local.internal_order_id)
    await mgr.ack(local.internal_order_id, "sim_999")

    adapter = StubRecoveryAdapter()
    now = datetime.now(UTC)
    from crypto_trader.domain.models import Order

    adapter.view = Order(
        internal_order_id=local.internal_order_id,
        client_order_id="c_rec",
        exchange_order_id="sim_999",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price="100",
        quantity="1",
        filled_quantity="1",
        avg_fill_price="100",
        status=OrderStatus.FILLED,
        trading_mode=TradingMode.PAPER,
        created_at=now,
        updated_at=now,
    )
    actions = await RecoveryService(mgr, adapter).recover("run_rec")
    restored = await mgr.get(local.internal_order_id)
    assert restored.status == OrderStatus.FILLED
    assert restored.filled_quantity == Decimal("1")
    assert any("recovery fill" in a for a in actions)
    # no resubmission happened: adapter has no submit_order at all
    assert not hasattr(adapter, "submit_order")


async def test_recovery_rejects_order_missing_from_exchange(database):
    mgr = OrderManager(database.session_factory)
    intent = OrderIntent(
        client_order_id="c_lost",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price="100",
        quantity="1",
    )
    local = await mgr.create_from_intent(intent, trading_mode=TradingMode.PAPER)
    await mgr.validate(local.internal_order_id)
    await mgr.submitting(local.internal_order_id)
    await mgr.submitted(local.internal_order_id)
    await mgr.ack(local.internal_order_id, "sim_998")

    from crypto_trader.domain.errors import OrderNotFound

    class MissingAdapter:
        async def get_order(self, symbol, exchange_order_id):
            raise OrderNotFound(exchange_order_id)

    actions = await RecoveryService(mgr, MissingAdapter()).recover("run_missing")
    restored = await mgr.get(local.internal_order_id)
    assert restored.status == OrderStatus.REJECTED
    assert any("not on exchange" in a for a in actions)



class _HealthyMarketAdapter:
    """Adapter exposing a real, healthy two-sided market."""

    def __init__(self, bid: str, ask: str):
        self.bid = bid
        self.ask = ask
        self.positions: dict = {}

    async def get_market_state(self, symbol):
        from crypto_trader.market_data.state import DataHealth, MarketState

        return MarketState(
            symbol=symbol,
            provider="OKX_PUBLIC",
            best_bid=self.bid,
            best_ask=self.ask,
            health=DataHealth.HEALTHY,
            sources={},
        )


class _NoPlans:
    async def get_active_for_symbol(self, symbol):
        return None


class _ActivePlanOnly:
    async def get_active_for_symbol(self, symbol):
        return object()


async def test_recovery_flattens_orphan_position_at_real_touch(database):
    from crypto_trader.domain.models import Position

    mgr = OrderManager(database.session_factory)
    adapter = _HealthyMarketAdapter("25.99", "26.01")
    positions = {
        "VVVUSDT": Position(
            symbol="VVVUSDT",
            base_asset="VVV",
            quote_asset="USDT",
            quantity=Decimal("-334.4"),
            avg_entry_price=Decimal("12.061"),
            updated_at=datetime.now(UTC),
        )
    }

    actions = await RecoveryService(
        mgr,
        adapter,
        positions_provider=_provider(positions),
        plans=_NoPlans(),
    ).recover("run_orphan")

    assert any("orphan position -334.4" in a for a in actions)
    open_orders = await mgr.list_open()
    assert open_orders == []
    closed = await mgr.list_all(limit=10)
    recovery_orders = [
        o for o in closed if o.metadata.get("recovery") == "orphan_position_close"
    ]
    assert len(recovery_orders) == 1
    order = recovery_orders[0]
    assert order.side == OrderSide.BUY  # close the short by buying back
    assert order.quantity == Decimal("334.4")
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == Decimal("334.4")
    # The close price is the REAL ask (26.01), never the corrupted 12.06 entry.
    assert order.avg_fill_price == Decimal("26.01")


def _provider(positions):
    async def provide():
        return positions

    return provide


async def test_recovery_leaves_plan_linked_positions_alone(database):
    from crypto_trader.domain.models import Position

    mgr = OrderManager(database.session_factory)
    positions = {
        "BTCUSDT": Position(
            symbol="BTCUSDT",
            base_asset="BTC",
            quote_asset="USDT",
            quantity=Decimal("1"),
            avg_entry_price=Decimal("100"),
            updated_at=datetime.now(UTC),
        )
    }

    actions = await RecoveryService(
        mgr,
        _HealthyMarketAdapter("100", "100.1"),
        positions_provider=_provider(positions),
        plans=_ActivePlanOnly(),
    ).recover("run_linked")

    assert actions == []
    assert await mgr.list_open() == []