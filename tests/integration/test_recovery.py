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
    def __init__(self, bid: str, ask: str):
        self.bid = Decimal(bid)
        self.ask = Decimal(ask)
        self.restored = None

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

    async def restore_from_canonical_state(self, *, balances, positions):
        self.restored = (balances, positions)


class _NoPlans:
    async def get_active_for_symbol(self, symbol):
        return None


class _ActivePlan:
    async def get_active_for_symbol(self, symbol):
        return object()


def _provider(value):
    async def provide():
        return value

    return provide


async def test_recovery_flattens_orphan_linear_perp_at_factual_touch(database):
    from crypto_trader.domain.models import Position

    mgr = OrderManager(database.session_factory)
    settled = []

    async def settle(fill):
        settled.append(fill)

    mgr.settlement_callback = settle
    position = Position(
        symbol="VVVUSDT",
        base_asset="VVV",
        quote_asset="USDT",
        instrument_type="LINEAR_PERP",
        contract_size=Decimal("0.1"),
        contract_multiplier=Decimal("1"),
        quantity=Decimal("-3"),
        avg_entry_price=Decimal("12"),
        leverage=Decimal("2"),
        updated_at=datetime.now(UTC),
    )
    adapter = _HealthyMarketAdapter("25.99", "26.01")
    actions = await RecoveryService(
        mgr,
        adapter,
        positions_provider=_provider({"VVVUSDT": position}),
        plans=_NoPlans(),
    ).recover("run-orphan")

    orders = await mgr.list_all(limit=10)
    recovery = [o for o in orders if o.metadata.get("recovery") == "orphan_position_close"]
    assert len(recovery) == 1
    order = recovery[0]
    assert order.status == OrderStatus.FILLED
    assert order.side == OrderSide.BUY
    assert order.avg_fill_price == Decimal("26.01")
    assert order.metadata["reduce_only"] is True
    assert order.metadata["instrument_type"] == "LINEAR_PERP"
    assert order.metadata["contract_size"] == "0.1"
    assert len(settled) == 1
    assert any("factual touch 26.01" in action for action in actions)


async def test_recovery_does_not_flatten_position_with_active_plan(database):
    from crypto_trader.domain.models import Position

    mgr = OrderManager(database.session_factory)
    position = Position(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("1"),
        avg_entry_price=Decimal("100"),
        updated_at=datetime.now(UTC),
    )
    actions = await RecoveryService(
        mgr,
        _HealthyMarketAdapter("100", "100.1"),
        positions_provider=_provider({"BTCUSDT": position}),
        plans=_ActivePlan(),
    ).recover("run-linked")
    assert actions == []
    assert await mgr.list_open() == []


async def test_recovery_resyncs_paper_adapter_from_ledger(database):
    from crypto_trader.domain.models import Balance, Position

    mgr = OrderManager(database.session_factory)
    adapter = _HealthyMarketAdapter("100", "101")
    balances = {
        "USDT": Balance(
            currency="USDT",
            total=Decimal("1234"),
            available=Decimal("1234"),
            frozen=Decimal("0"),
        )
    }
    positions = {
        "BTCUSDT": Position(
            symbol="BTCUSDT",
            base_asset="BTC",
            quote_asset="USDT",
            quantity=Decimal("2"),
            avg_entry_price=Decimal("100"),
            updated_at=datetime.now(UTC),
        )
    }

    actions = await RecoveryService(
        mgr,
        adapter,
        ledger_state_provider=_provider((balances, positions)),
    ).recover("run-resync")

    assert adapter.restored is not None
    restored_balances, restored_positions = adapter.restored
    assert restored_balances == {"USDT": Decimal("1234")}
    assert restored_positions["BTCUSDT"].quantity == Decimal("2")
    assert "sim resynced from ledger" in actions
