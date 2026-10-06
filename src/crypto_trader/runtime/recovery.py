"""Crash recovery: load open orders -> query exchange -> reconcile -> restore.

Never blind resubmit. Orders stuck in SUBMITTING/SUBMITTED are resolved by
querying the exchange, not by creating new orders.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from crypto_trader.domain.enums import (
    OrderEventType,
    OrderStatus,
)
from crypto_trader.domain.errors import OrderNotFound
from crypto_trader.domain.identifiers import new_id


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
        ledger_state_provider: Callable[[], Awaitable[tuple[dict[str, Any], dict[str, Any]]]]
        | None = None,
    ) -> None:
        self.order_manager = order_manager
        self.adapter = adapter
        self.audit = audit
        self.positions_provider = positions_provider
        self.plans = plans
        self.ledger_state_provider = ledger_state_provider

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
            # The adapter supplies an aggregate order, not individual fill
            # IDs, fees or timestamps. Never invent those facts from totals.
            if local.filled_quantity != exchange_order.filled_quantity:
                reason = "RECOVERY_FILL_FACTS_UNAVAILABLE"
                coordinator = self.order_manager.settlement_coordinator
                if coordinator is not None:
                    coordinator.fault(local.internal_order_id, reason)
                actions.append(f"{local.client_order_id}: {reason}")
                if self.audit is not None:
                    await self.audit.log(
                        reason,
                        target=local.internal_order_id,
                        run_id=run_id,
                        order_id=local.internal_order_id,
                        after={
                            "local_filled_quantity": str(local.filled_quantity),
                            "exchange_filled_quantity": str(exchange_order.filled_quantity),
                            "exchange_status": status.value,
                        },
                    )
                continue
            if status != local.status:
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
        await self._resync_sim_from_ledger(actions)
        return actions

    async def _resync_sim_from_ledger(self, actions: list[str]) -> None:
        """Mirror canonical ledger state without creating a recovery trade.

        The adapter's canonical restore remains generation-fenced; unresolved
        orphan faults cannot be cleared by hydration.
        """
        restore = getattr(self.adapter, "restore_from_canonical_state", None)
        if restore is None or self.ledger_state_provider is None:
            return
        try:
            balances, positions = await self.ledger_state_provider()
        except Exception as exc:  # noqa: BLE001 - recovery must not crash startup
            actions.append(f"sim resync skipped (ledger unavailable: {exc})")
            return
        await restore(
            balances={c: b.total for c, b in balances.items()},
            positions=positions,
        )
        actions.append("sim resynced from ledger")

    async def _close_orphan_positions(self, run_id: str | None, actions: list[str]) -> None:
        """Retain unresolved exposure; recovery has no execution authority.

        A missing plan is not a factual instruction to flatten. In particular,
        a market quote cannot justify inventing an order, fill or fee.
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
            reason = "ORPHAN_POSITION_UNRESOLVED"
            coordinator = self.order_manager.settlement_coordinator
            if coordinator is not None:
                coordinator.fault("orphan:" + symbol, reason)
            actions.append(f"{symbol}: {reason} quantity={position.quantity}")
            if self.audit is not None:
                await self.audit.log(
                    "RECOVERY_ORPHAN_POSITION_UNRESOLVED",
                    target=symbol,
                    run_id=run_id,
                    after={
                        "orphan_quantity": str(position.quantity),
                        "orphan_avg_entry": str(position.avg_entry_price),
                    },
                )
