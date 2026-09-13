"""Crash recovery: load open orders -> query exchange -> reconcile -> restore.

Never blind resubmit. Orders stuck in SUBMITTING/SUBMITTED are resolved by
querying the exchange, not by creating new orders.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.enums import OrderEventType, OrderStatus

logger = logging.getLogger(__name__)

from crypto_trader.domain.errors import OrderNotFound
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import Fill
from crypto_trader.order.recovery_classification import (
    DISPOSITION_MISSING,
    DISPOSITION_REJECT,
    DISPOSITION_UNKNOWN,
    classify_recovery_lookup_outcome,
)


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
        #: Orders recovery could not safely resolve. Reported, never silently
        #: terminalised.
        self.health_unresolved: list[str] = []


    async def _durable_fill_count(self, local) -> int:
        """Factual fill rows for this order. Execution evidence outranks lookup."""
        try:
            count = getattr(self.order_manager, "count_fills_for_order", None)
            if count is not None:
                return int(await count(local.internal_order_id))
        except Exception:
            # Unreadable is not zero: treat as unknown evidence and refuse to
            # terminalise by returning a non-zero sentinel.
            return 1
        return 0

    async def _failure_reason(self, local) -> str | None:
        """Last recorded failure reason, read from durable order events."""
        reason = getattr(local, "rejection_reason", None)
        if reason:
            return str(reason)
        events = getattr(self.order_manager, "list_events", None)
        if events is None:
            return None
        try:
            for event in reversed(await events(local.internal_order_id)):
                payload = getattr(event, "payload", None) or {}
                value = payload.get("reason")
                if value:
                    return str(value)
        except Exception:
            return None
        return None

    async def _pre_broker_lineage_proven(self, local) -> bool:
        """True only when durable lineage proves the broker was never reached.

        Requires an ORDER_UNKNOWN/REJECTED style event carrying a proven
        pre-broker reason AND the absence of any broker identity. Anything
        unreadable returns False, which is the safe direction: no terminalise.
        """
        if local.exchange_order_id:
            return False
        events = getattr(self.order_manager, "list_events", None)
        if events is None:
            return False
        try:
            for event in reversed(await events(local.internal_order_id)):
                payload = getattr(event, "payload", None) or {}
                raw = payload.get("reason")
                if not raw:
                    continue
                from crypto_trader.order.recovery_classification import (
                    PROVEN_PRE_BROKER_REASONS,
                )

                return str(raw).strip().upper() in PROVEN_PRE_BROKER_REASONS
        except Exception:
            return False
        return False

    async def _safe_audit(self, action: str, **fields) -> None:
        """Audit is optional here; a missing audit must never mask a decision."""
        log = getattr(self.audit, "log", None)
        if log is None:
            return
        try:
            await log(action, **fields)
        except Exception:
            logger.warning("recovery audit failed", exc_info=True)

    async def recover(self, run_id: str | None = None) -> list[str]:
        actions: list[str] = []
        for local in await self.order_manager.list_open():
            lookup_key = local.exchange_order_id or local.client_order_id
            if not lookup_key:
                # ORDER NOT FOUND != ORDER NEVER EXISTED. Without any identifier we
                # cannot prove the order never reached the venue, so we must not
                # assert a terminal REJECTED. Stay unresolved; never resubmit.
                await self._safe_audit(
                    "RECOVERY_ORDER_UNIDENTIFIABLE",
                    target=local.client_order_id or local.internal_order_id,
                    run_id=run_id,
                    order_id=local.internal_order_id,
                    client_order_id=local.client_order_id,
                    after={
                        "disposition": DISPOSITION_UNKNOWN,
                        "reason_codes": ["NO_ORDER_IDENTIFIERS"],
                    },
                )
                actions.append(f"{local.client_order_id}: UNKNOWN (no identifiers)")
                continue
            try:
                exchange_order = await self.adapter.get_order(local.symbol, lookup_key)
            except OrderNotFound:
                # CLASSIFY before acting. "Not found" is NOT evidence that the
                # order never existed: a lookup can miss a real order through a
                # cancellation race, a venue purge or a partial response, and a
                # false terminal REJECTED is what leaves a position unmanageable.
                # Only a POSITIVE pre-broker proof may terminalise.
                durable_fills = await self._durable_fill_count(local)
                verdict = classify_recovery_lookup_outcome(
                    lookup_ok=True,
                    exchange_order_id=local.exchange_order_id,
                    filled_quantity=local.filled_quantity,
                    durable_fill_count=durable_fills,
                    failure_reason=await self._failure_reason(local),
                    pre_broker_lineage_proven=await self._pre_broker_lineage_proven(local),
                    has_client_order_id=bool(local.client_order_id),
                )
                if verdict.disposition == DISPOSITION_REJECT:
                    await self.order_manager.reject(
                        local.internal_order_id,
                        "proven pre-broker refusal; no blind resubmit",
                        event_id=new_id("evt"),
                    )
                    actions.append(
                        f"{local.client_order_id}: REJECTED (proven pre-broker)"
                    )
                elif verdict.disposition == DISPOSITION_MISSING:
                    self.health_unresolved.append(local.internal_order_id)
                    await self._safe_audit(
                        "RECOVERY_ORDER_MISSING",
                        target=local.client_order_id,
                        run_id=run_id,
                        order_id=local.internal_order_id,
                        client_order_id=local.client_order_id,
                        exchange_order_id=local.exchange_order_id,
                        after={
                            "disposition": DISPOSITION_MISSING,
                            "reason_codes": list(verdict.reason_codes),
                        },
                    )
                    actions.append(
                        f"{local.client_order_id}: MISSING (reconciliation required)"
                    )
                else:
                    self.health_unresolved.append(local.internal_order_id)
                    await self._safe_audit(
                        "RECOVERY_ORDER_LEFT_UNRESOLVED",
                        target=local.client_order_id,
                        run_id=run_id,
                        order_id=local.internal_order_id,
                        client_order_id=local.client_order_id,
                        after={
                            "classification": verdict.classification,
                            "disposition": DISPOSITION_UNKNOWN,
                            "reason_codes": list(verdict.reason_codes),
                        },
                    )
                    actions.append(f"{local.client_order_id}: UNKNOWN (unproven)")
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
        return actions
