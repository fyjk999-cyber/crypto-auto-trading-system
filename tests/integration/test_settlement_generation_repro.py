"""Diagnostic reproduction, not an acceptance of inconsistent snapshots.

Synthetic trades are restricted to tmp_path SQLite and a local PAPER adapter.
The barrier pauses delivery after the real adapter applies a fill but before
the real order/ledger settlement callback receives it. No timing sleeps.
"""

import asyncio
import os
from decimal import Decimal

import pytest

from crypto_trader.domain.enums import ExchangeEventType, OrderSide, TradingMode
from crypto_trader.domain.models import Instrument, OrderIntent
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter
from tests.conftest import make_paper_engine


class DeliveryBarrierAdapter(SimulatedExchangeAdapter):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pause_delivery = False
        self.external_fill_applied = asyncio.Event()
        self.release_delivery = asyncio.Event()

    async def _emit(self, event):
        if self.pause_delivery and event.event_type == ExchangeEventType.ORDER_FILLED:
            self.external_fill_applied.set()
            await self.release_delivery.wait()
        await super()._emit(event)


@pytest.mark.parametrize("iteration", range(20))
async def test_real_settlement_cross_generation_window(database, iteration):
    adapter = DeliveryBarrierAdapter(
        instruments=[
            Instrument(
                symbol="NEARUSDT",
                base_asset="NEAR",
                quote_asset="USDT",
                instrument_type="LINEAR_PERP",
                contract_size="10",
            )
        ],
        initial_balances={"USDT": Decimal("100000")},
    )
    engine = make_paper_engine(database, simulator=adapter)
    await adapter.connect()
    # Same setup and callbacks as engine startup, without unrelated schedulers.
    await engine._seed_initial_balances()
    engine.order_manager.settlement_callback = engine._settle_fill
    adapter.seed_book("NEARUSDT", mid="5.128", spread="0.001")

    async def submit(side, quantity, reduce_only):
        intent = OrderIntent(
            client_order_id=f"repro-{iteration}-{side.value}",
            symbol="NEARUSDT",
            side=side,
            price=Decimal("5.128"),
            quantity=quantity,
            metadata={
                "instrument_type": "LINEAR_PERP",
                "contract_size": "10",
                "reduce_only": reduce_only,
            },
        )
        order = await engine.order_manager.create_from_intent(
            intent, trading_mode=TradingMode.PAPER
        )
        await engine.order_manager.validate(order.internal_order_id)
        await engine.order_manager.submitting(order.internal_order_id)
        await engine.order_manager.submitted(order.internal_order_id)

        async def receive(event):
            if event.payload.get("client_order_id") != order.client_order_id:
                return
            if event.event_type == ExchangeEventType.ORDER_ACK:
                await engine.order_manager.ack(
                    order.internal_order_id, event.payload["exchange_order_id"]
                )
            else:
                await engine.process_exchange_event(event)

        await adapter.subscribe_order_updates(receive)
        return await adapter.submit_order(order)

    # Aggressive limits cross the factual fixture book; no production fills.
    adapter.seed_book("NEARUSDT", mid="5.117", spread="0.001")
    await submit(OrderSide.BUY, Decimal("0.6"), False)
    before = await engine.reconciliation.reconcile(adapter)
    assert before.ok and not before.halt
    assert (await engine.portfolio.get_position("NEARUSDT")).quantity == Decimal("0.6")
    adapter.seed_book("NEARUSDT", mid="5.143", spread="0.001")
    adapter.pause_delivery = True
    reduction = asyncio.create_task(submit(OrderSide.SELL, Decimal("0.3"), True))
    try:
        await asyncio.wait_for(adapter.external_fill_applied.wait(), timeout=5)
        # Concurrent real reconcile legally enters while delivery/settlement waits.
        inflight = await engine.reconciliation.reconcile(adapter)
        assert inflight.halt and not inflight.ok
        assert inflight.positions_diff["NEARUSDT"] == {
            "local_quantity": "0.6",
            "exchange_quantity": "0.3",
        }
        assert any(a.startswith("POSITION_MISMATCH NEARUSDT") for a in inflight.alerts)
        assert (await engine.portfolio.get_position("NEARUSDT")).quantity == Decimal("0.6")
    finally:
        adapter.release_delivery.set()
        await asyncio.wait_for(reduction, timeout=5)
    after = await engine.reconciliation.reconcile(adapter)
    assert after.ok and not after.halt
    assert after.positions_diff == {}
    assert (await engine.portfolio.get_position("NEARUSDT")).quantity == Decimal("0.3")
    assert Decimal(after.local_balances["USDT"]) == Decimal(after.exchange_balances["USDT"])
    if os.environ.get("LOWRISK_REPRO_ASSERT_COHERENT") == "1":
        assert not inflight.halt, "RED: real concurrent settlement permits cross-generation halt"
