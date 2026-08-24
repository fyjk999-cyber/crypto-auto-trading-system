from datetime import datetime, timezone
from decimal import Decimal

from crypto_trader.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce, TradingMode
from crypto_trader.domain.models import OrderIntent
from crypto_trader.order.manager import OrderManager
from crypto_trader.runtime.recovery import RecoveryService
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter


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
        return [Balance(currency="USDT", total=Decimal("0"), available=Decimal("0"), frozen=Decimal("0"))]


async def test_recovery_never_blind_resubmits_and_applies_exchange_fill(database):
    mgr = OrderManager(database.session_factory)
    intent = OrderIntent(client_order_id="c_rec", symbol="BTCUSDT", side=OrderSide.BUY,
                         order_type=OrderType.LIMIT, time_in_force=TimeInForce.GTC,
                         price="100", quantity="1")
    local = await mgr.create_from_intent(intent, trading_mode=TradingMode.PAPER)
    await mgr.validate(local.internal_order_id)
    await mgr.submitting(local.internal_order_id)
    await mgr.submitted(local.internal_order_id)
    await mgr.ack(local.internal_order_id, "sim_999")

    adapter = StubRecoveryAdapter()
    now = datetime.now(timezone.utc)
    from crypto_trader.domain.models import Order
    adapter.view = Order(
        internal_order_id=local.internal_order_id, client_order_id="c_rec",
        exchange_order_id="sim_999", symbol="BTCUSDT", side=OrderSide.BUY,
        order_type=OrderType.LIMIT, time_in_force=TimeInForce.GTC,
        price="100", quantity="1", filled_quantity="1", avg_fill_price="100",
        status=OrderStatus.FILLED, trading_mode=TradingMode.PAPER,
        created_at=now, updated_at=now,
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
    intent = OrderIntent(client_order_id="c_lost", symbol="BTCUSDT", side=OrderSide.BUY,
                         order_type=OrderType.LIMIT, time_in_force=TimeInForce.GTC,
                         price="100", quantity="1")
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
