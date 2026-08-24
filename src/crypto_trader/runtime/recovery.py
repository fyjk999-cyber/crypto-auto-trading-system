"""Crash recovery: load open orders -> query exchange -> reconcile -> restore.

Never blind resubmit. Orders stuck in SUBMITTING/SUBMITTED are resolved by
querying the exchange, not by creating new orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from crypto_trader.domain.enums import OrderEventType, OrderSide, OrderStatus
from crypto_trader.domain.errors import OrderNotFound
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import Fill, Order


def event_type_for_exchange_status(status: OrderStatus) -> OrderEventType:
    return {
        OrderStatus.ACKNOWLEDGED: OrderEventType.ORDER_ACKNOWLEDGED,
        OrderStatus.OPEN: OrderEventType.ORDER_OPENED,
        OrderStatus.PARTIALLY_FILLED: OrderEventType.ORDER_PARTIALLY_FILLED,
        OrderStatus.FILLED: OrderEventType.ORDER_FILLED,
        OrderStatus.CANCELLED: OrderEventType.ORDER_CANCELLED,
        OrderStatus.CANCEL_PENDING: OrderEventType.ORDER_CANCEL_PENDING,
        OrderStatus.REJECTED: OrderEventType.ORDER_REJECTED,
        OrderStatus.EXPIRED: OrderEventType.ORDER_EXPIRED,
        OrderStatus.UNKNOWN: OrderEventType.ORDER_UNKNOWN,
    }.get(status, OrderEventType.ORDER_UNKNOWN)


class RecoveryService:
    def __init__(self, order_manager, adapter, audit=None) -> None:
        self.order_manager = order_manager
        self.adapter = adapter
        self.audit = audit

    async def recover(self, run_id: str | None = None) -> list[str]:
        actions: list[str] = []
        for local in await self.order_manager.list_open():
            if not local.exchange_order_id:
                await self.order_manager.reject(
                    local.internal_order_id,
                    "no exchange_order_id during recovery; no blind resubmit",
                    event_id=new_id("evt"),
                )
                actions.append(f"{local.client_order_id}: REJECTED (missing exchange id)")
                continue
            try:
                exchange_order = await self.adapter.get_order(local.symbol, local.exchange_order_id)
            except OrderNotFound:
                # The order never reached the exchange or was fully purged.
                # We must not resubmit; record terminal state and continue.
                await self.order_manager.reject(
                    local.internal_order_id,
                    "order not found on exchange during recovery; no blind resubmit",
                    event_id=new_id("evt"),
                )
                actions.append(f"{local.client_order_id}: REJECTED (not on exchange)")
                continue

            status = exchange_order.status
            # Fill reconciliation first (exchange truth wins)
            if status == OrderStatus.FILLED and local.filled_quantity < exchange_order.filled_quantity:
                fill = Fill(
                    fill_id=f"recovery_{exchange_order.exchange_order_id}_{format(exchange_order.filled_quantity, 'f').replace('.', '_')}",
                    trade_id=new_id("trade"),
                    order_id=local.internal_order_id,
                    client_order_id=local.client_order_id,
                    exchange_order_id=exchange_order.exchange_order_id,
                    symbol=local.symbol,
                    side=local.side,
                    price=exchange_order.avg_fill_price or exchange_order.price or Decimal("0"),
                    quantity=exchange_order.filled_quantity - local.filled_quantity,
                    fee=Decimal("0"),
                    timestamp=datetime.now(timezone.utc),
                    payload={"recovery": True},
                )
                await self.order_manager.apply_fill(fill)
                actions.append(f"{local.client_order_id}: recovery fill {fill.quantity}")
            if status == OrderStatus.PARTIALLY_FILLED and local.filled_quantity < exchange_order.filled_quantity:
                fill = Fill(
                    fill_id=f"recovery_{exchange_order.exchange_order_id}_partial",
                    trade_id=new_id("trade"),
                    order_id=local.internal_order_id,
                    client_order_id=local.client_order_id,
                    exchange_order_id=exchange_order.exchange_order_id,
                    symbol=local.symbol,
                    side=local.side,
                    price=exchange_order.avg_fill_price or exchange_order.price or Decimal("0"),
                    quantity=exchange_order.filled_quantity - local.filled_quantity,
                    fee=Decimal("0"),
                    timestamp=datetime.now(timezone.utc),
                    payload={"recovery": True},
                )
                await self.order_manager.apply_fill(fill)
                actions.append(f"{local.client_order_id}: recovery partial fill {fill.quantity}")
            elif status != local.status:
                event_type = event_type_for_exchange_status(status)
                if status in (OrderStatus.OPEN, OrderStatus.ACKNOWLEDGED):
                    await self.order_manager.transition(
                        local.internal_order_id, event_type,
                        event_id=new_id("evt"),
                        exchange_order_id=exchange_order.exchange_order_id,
                    )
                elif status == OrderStatus.CANCELLED:
                    await self.order_manager.cancel_confirm(local.internal_order_id, event_id=new_id("evt"))
                elif status == OrderStatus.REJECTED:
                    await self.order_manager.reject(
                        local.internal_order_id,
                        exchange_order.rejection_reason or "rejected on exchange",
                        event_id=new_id("evt"),
                    )
                elif status == OrderStatus.EXPIRED:
                    await self.order_manager.expire(local.internal_order_id)
                actions.append(f"{local.client_order_id}: {local.status.value} -> {status.value}")
            if self.audit is not None:
                await self.audit.log(
                    "RECOVERY_RECONCILE",
                    target=local.client_order_id,
                    run_id=run_id,
                    order_id=local.internal_order_id,
                    client_order_id=local.client_order_id,
                    exchange_order_id=local.exchange_order_id,
                    before={"status": local.status.value},
                    after={"status": status.value},
                )
        return actions
