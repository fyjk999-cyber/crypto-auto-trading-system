"""Crash recovery: load open orders -> query exchange -> reconcile -> restore.

Never blind resubmit. Orders stuck in SUBMITTING/SUBMITTED are resolved by
querying the exchange, not by creating new orders.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from crypto_trader.domain.enums import (
    OrderEventType,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    TradingMode,
)
from crypto_trader.domain.errors import OrderNotFound
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import Fill, OrderIntent


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
    def __init__(
        self,
        order_manager,
        adapter,
        audit=None,
        *,
        positions_provider: Callable[[], Awaitable[dict[str, Any]]] | None = None,
        plans: Any | None = None,
    ) -> None:
        self.order_manager = order_manager
        self.adapter = adapter
        self.audit = audit
        self.positions_provider = positions_provider
        self.plans = plans

    async def recover(self, run_id: str | None = None) -> list[str]:
        actions: list[str] = []
        for local in await self.order_manager.list_open():
            lookup_key = local.exchange_order_id or local.client_order_id
            if not lookup_key:
                await self.order_manager.reject(
                    local.internal_order_id,
                    "no exchange/client order id during recovery; no blind resubmit",
                    event_id=new_id("evt"),
                )
                actions.append(f"{local.client_order_id}: REJECTED (missing order id)")
                continue
            try:
                exchange_order = await self.adapter.get_order(local.symbol, lookup_key)
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
            if (
                status == OrderStatus.FILLED
                and local.filled_quantity < exchange_order.filled_quantity
            ):
                fill = Fill(
                    fill_id=(
                        f"recovery_{exchange_order.exchange_order_id}_"
                        f"{format(exchange_order.filled_quantity, 'f').replace('.', '_')}"
                    ),
                    trade_id=new_id("trade"),
                    order_id=local.internal_order_id,
                    client_order_id=local.client_order_id,
                    exchange_order_id=exchange_order.exchange_order_id,
                    symbol=local.symbol,
                    side=local.side,
                    price=exchange_order.avg_fill_price or exchange_order.price or Decimal("0"),
                    quantity=exchange_order.filled_quantity - local.filled_quantity,
                    fee=Decimal("0"),
                    timestamp=datetime.now(UTC),
                    payload={"recovery": True},
                )
                await self.order_manager.apply_fill(fill)
                actions.append(f"{local.client_order_id}: recovery fill {fill.quantity}")
            if (
                status == OrderStatus.PARTIALLY_FILLED
                and local.filled_quantity < exchange_order.filled_quantity
            ):
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
                    timestamp=datetime.now(UTC),
                    payload={"recovery": True},
                )
                await self.order_manager.apply_fill(fill)
                actions.append(f"{local.client_order_id}: recovery partial fill {fill.quantity}")
            elif status != local.status:
                event_type = event_type_for_exchange_status(status)
                if status in (OrderStatus.OPEN, OrderStatus.ACKNOWLEDGED):
                    await self.order_manager.transition(
                        local.internal_order_id,
                        event_type,
                        event_id=new_id("evt"),
                        exchange_order_id=exchange_order.exchange_order_id,
                    )
                elif status == OrderStatus.CANCELLED:
                    await self.order_manager.cancel_confirm(
                        local.internal_order_id, event_id=new_id("evt")
                    )
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
        await self._close_orphan_positions(run_id, actions)
        return actions

    async def _close_orphan_positions(self, run_id: str | None, actions: list[str]) -> None:
        """Restore the open-position <-> active-trade-plan invariant.

        The LLM position lifecycle can only manage positions that belong to an
        active trade plan (position decisions route through the plan). A
        position without an active plan can therefore never be exited and can
        only arise from recovery artifacts of corrupted fills. Such orphans
        are flattened at the real market touch with a dedicated reduce-only
        recovery order (audited). No new direction is decided here: this is
        ledger restoration, not a trade decision.
        """
        if self.positions_provider is None or self.plans is None:
            return
        try:
            positions = await self.positions_provider()
        except Exception as exc:  # noqa: BLE001 - recovery must not crash startup
            actions.append(f"orphan close skipped (positions unavailable: {exc})")
            return
        for symbol, position in positions.items():
            if position.quantity == 0:
                continue
            if await self.plans.get_active_for_symbol(symbol) is not None:
                continue
            market = getattr(self.adapter, "get_market_state", None)
            state = None
            if market is not None:
                try:
                    state = await market(symbol)
                except Exception:  # noqa: BLE001 - fail closed below
                    state = None
            if (
                state is None
                or state.health.value != "HEALTHY"
                or state.best_bid <= 0
                or state.best_ask <= 0
            ):
                actions.append(f"{symbol}: orphan close skipped (no real market)")
                continue
            close_side = OrderSide.BUY if position.quantity < 0 else OrderSide.SELL
            touch = state.best_ask if close_side == OrderSide.BUY else state.best_bid
            intent = OrderIntent(
                client_order_id=f"recovery_flat_{symbol}_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
                symbol=symbol,
                side=close_side,
                order_type=OrderType.LIMIT,
                time_in_force=TimeInForce.GTC,
                price=touch,
                quantity=abs(position.quantity),
                strategy_id="recovery",
                run_id=run_id,
                metadata={
                    "recovery": "orphan_position_close",
                    "orphan_quantity": str(position.quantity),
                    "orphan_avg_entry": str(position.avg_entry_price),
                    "real_touch": str(touch),
                },
            )
            order = await self.order_manager.create_from_intent(
                intent, trading_mode=TradingMode.PAPER
            )
            await self.order_manager.validate(order.internal_order_id)
            await self.order_manager.submitting(order.internal_order_id)
            await self.order_manager.submitted(order.internal_order_id)
            await self.order_manager.ack(order.internal_order_id, new_id("sim"))
            fill = Fill(
                fill_id=new_id("fill"),
                trade_id=new_id("trade"),
                order_id=order.internal_order_id,
                client_order_id=order.client_order_id,
                exchange_order_id=order.exchange_order_id,
                symbol=symbol,
                side=close_side,
                price=touch,
                quantity=abs(position.quantity),
                fee=Decimal("0"),
                timestamp=datetime.now(UTC),
                payload={"recovery": "orphan_position_close"},
            )
            await self.order_manager.apply_fill(fill)
            sim_positions = getattr(self.adapter, "positions", None)
            if isinstance(sim_positions, dict):
                sim_positions.pop(symbol, None)
            actions.append(
                f"{symbol}: orphan position {position.quantity} closed at real touch {touch}"
            )
            if self.audit is not None:
                await self.audit.log(
                    "RECOVERY_ORPHAN_POSITION_CLOSED",
                    target=symbol,
                    run_id=run_id,
                    order_id=order.internal_order_id,
                    after={
                        "orphan_quantity": str(position.quantity),
                        "orphan_avg_entry": str(position.avg_entry_price),
                        "close_side": close_side.value,
                        "close_price": str(touch),
                        "real_bid": str(state.best_bid),
                        "real_ask": str(state.best_ask),
                    },
                )
