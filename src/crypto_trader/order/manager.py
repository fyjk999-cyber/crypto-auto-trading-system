"""Idempotent, persisted OrderManager.

- client_order_id unique: one ID never produces two business orders.
- duplicate fill_id/event_id are persisted no-ops.
- REST timeout -> UNKNOWN -> query exchange -> recover; never blind resubmit.
- settlement callback receives each unique fill exactly once.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from crypto_trader.domain.enums import (
    MarketType,
    OrderEventType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    TimeInForce,
    TradingMode,
)
from crypto_trader.domain.errors import IdempotencyConflict, InvalidStateTransition, OrderNotFound
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import Fill, Order, OrderEvent, OrderIntent
from crypto_trader.order.state_machine import OrderStateMachine
from crypto_trader.persistence.models import FillORM, OrderEventORM, OrderORM

SettlementCallback = Callable[[Fill], Awaitable[None]]


def _orm_to_order(row: OrderORM) -> Order:
    return Order(
        internal_order_id=row.internal_order_id,
        client_order_id=row.client_order_id,
        exchange_order_id=row.exchange_order_id,
        symbol=row.symbol,
        side=OrderSide(row.side),
        order_type=OrderType(row.order_type),
        time_in_force=TimeInForce(row.time_in_force),
        price=row.price,
        quantity=row.quantity,
        filled_quantity=row.filled_quantity,
        avg_fill_price=row.avg_fill_price,
        status=OrderStatus(row.status),
        trading_mode=TradingMode(row.trading_mode),
        strategy_id=row.strategy_id,
        run_id=row.run_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        expires_at=row.expires_at,
        rejection_reason=row.rejection_reason,
        last_event_id=row.last_event_id,
        market_type=MarketType(row.market_type),
        position_side=PositionSide(row.position_side),
        reduce_only=bool(row.reduce_only),
    )


def _orm_to_event(row: OrderEventORM) -> OrderEvent:
    return OrderEvent(
        event_id=row.event_id,
        order_id=row.order_id,
        client_order_id=row.client_order_id,
        exchange_order_id=row.exchange_order_id,
        event_type=OrderEventType(row.event_type),
        status_after=OrderStatus(row.status_after),
        timestamp=row.timestamp,
        payload=row.payload_json or {},
    )


def _orm_to_fill(row: FillORM) -> Fill:
    return Fill(
        fill_id=row.fill_id,
        trade_id=row.trade_id,
        order_id=row.order_id,
        client_order_id=row.client_order_id,
        exchange_order_id=row.exchange_order_id,
        symbol=row.symbol,
        side=OrderSide(row.side),
        price=row.price,
        quantity=row.quantity,
        fee=row.fee,
        fee_currency=row.fee_currency,
        timestamp=row.timestamp,
        payload=row.payload_json or {},
    )


class OrderManager:
    def __init__(
        self, session_factory, settlement_callback: SettlementCallback | None = None
    ) -> None:
        self.session_factory = session_factory
        self.settlement_callback = settlement_callback

    async def create_from_intent(self, intent: OrderIntent, *, trading_mode: TradingMode) -> Order:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            existing = await self.get_by_client(intent.client_order_id)
            if existing is not None:
                return await self._reuse_or_conflict(existing, intent)
            order_id = new_id("ord")
            row = OrderORM(
                internal_order_id=order_id,
                client_order_id=intent.client_order_id,
                symbol=intent.symbol,
                side=intent.side.value,
                order_type=intent.order_type.value,
                time_in_force=intent.time_in_force.value,
                price=intent.price,
                quantity=intent.quantity,
                filled_quantity=Decimal("0"),
                status=OrderStatus.CREATED.value,
                trading_mode=trading_mode.value,
                strategy_id=intent.strategy_id,
                run_id=intent.run_id,
                created_at=now,
                updated_at=now,
                expires_at=intent.expires_at,
                market_type=intent.market_type.value,
                position_side=intent.position_side.value,
                reduce_only=intent.reduce_only,
            )
            session.add(row)
            await session.flush()
            event_id = new_id("evt")
            session.add(
                OrderEventORM(
                    event_id=event_id,
                    order_id=order_id,
                    client_order_id=intent.client_order_id,
                    event_type=OrderEventType.ORDER_CREATED.value,
                    status_after=OrderStatus.CREATED.value,
                    timestamp=now,
                    payload_json={"trading_mode": trading_mode.value},
                )
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                existing = await self.get_by_client(intent.client_order_id)
                if existing is not None:
                    return await self._reuse_or_conflict(existing, intent)
                raise exc
        return _orm_to_order(row)

    async def _reuse_or_conflict(self, existing: Order, intent: OrderIntent) -> Order:
        same = (
            existing.symbol == intent.symbol
            and existing.side == intent.side
            and existing.order_type == intent.order_type
            and (existing.price or Decimal("0")) == (intent.price or Decimal("0"))
            and existing.quantity == intent.quantity
        )
        if same:
            return existing
        raise IdempotencyConflict(
            f"client_order_id {intent.client_order_id} already used for a different order"
        )

    async def get(self, order_id: str) -> Order | None:
        async with self.session_factory() as session:
            row = await session.get(OrderORM, order_id)
            return _orm_to_order(row) if row else None

    async def get_by_client(self, client_order_id: str) -> Order | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(OrderORM).where(OrderORM.client_order_id == client_order_id)
                )
            ).scalar_one_or_none()
            return _orm_to_order(row) if row else None

    async def get_by_exchange(self, exchange_order_id: str) -> Order | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(OrderORM).where(OrderORM.exchange_order_id == exchange_order_id)
                )
            ).scalar_one_or_none()
            return _orm_to_order(row) if row else None

    async def list_open(self) -> list[Order]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(OrderORM).where(
                            OrderORM.status.in_(
                                [
                                    OrderStatus.SUBMITTED.value,
                                    OrderStatus.ACKNOWLEDGED.value,
                                    OrderStatus.OPEN.value,
                                    OrderStatus.PARTIALLY_FILLED.value,
                                    OrderStatus.CANCEL_PENDING.value,
                                    OrderStatus.UNKNOWN.value,
                                ]
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
            return [_orm_to_order(r) for r in rows]

    async def count_open(self) -> int:
        return len(await self.list_open())

    async def list_all(self, limit: int = 200) -> list[Order]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(OrderORM).order_by(OrderORM.created_at.desc()).limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return [_orm_to_order(r) for r in rows]

    async def _record_event(
        self,
        order: Order,
        event_type: OrderEventType,
        status_after: OrderStatus,
        *,
        event_id: str | None = None,
        exchange_order_id: str | None = None,
        payload: dict | None = None,
        rejection_reason: str | None = None,
        now: datetime | None = None,
    ) -> OrderEvent:
        now = now or datetime.now(UTC)
        event_id = event_id or new_id("evt")
        async with self.session_factory() as session:
            row = await session.get(OrderORM, order.internal_order_id)
            if row is None:
                raise OrderNotFound(order.internal_order_id)
            row.status = status_after.value
            row.updated_at = now
            row.last_event_id = event_id
            if exchange_order_id:
                row.exchange_order_id = exchange_order_id
            if rejection_reason:
                row.rejection_reason = rejection_reason
            event = OrderEventORM(
                event_id=event_id,
                order_id=order.internal_order_id,
                client_order_id=order.client_order_id,
                exchange_order_id=exchange_order_id or order.exchange_order_id,
                event_type=event_type.value,
                status_after=status_after.value,
                timestamp=now,
                payload_json=payload or {},
            )
            session.add(event)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                async with self.session_factory() as s2:
                    existing = (
                        await s2.execute(
                            select(OrderEventORM).where(OrderEventORM.event_id == event_id)
                        )
                    ).scalar_one_or_none()
                if existing is not None:
                    return _orm_to_event(existing)
                raise exc
        return OrderEvent(
            event_id=event_id,
            order_id=order.internal_order_id,
            client_order_id=order.client_order_id,
            exchange_order_id=exchange_order_id or order.exchange_order_id,
            event_type=event_type,
            status_after=status_after,
            timestamp=now,
            payload=payload or {},
        )

    async def transition(self, order_id: str, event_type: OrderEventType, **kwargs) -> Order:
        order = await self.get(order_id)
        if order is None:
            raise OrderNotFound(order_id)
        result = OrderStateMachine.transition(order.status, event_type)
        if result.noop and not result.changed:
            await self._record_event(order, event_type, order.status, **kwargs)
            return order
        await self._record_event(order, event_type, result.new_status, **kwargs)
        return await self.get(order_id)

    async def validate(self, order_id: str) -> Order:
        return await self.transition(order_id, OrderEventType.ORDER_VALIDATED)

    async def submitting(self, order_id: str) -> Order:
        return await self.transition(order_id, OrderEventType.ORDER_SUBMITTING)

    async def submitted(self, order_id: str) -> Order:
        return await self.transition(order_id, OrderEventType.ORDER_SUBMITTED)

    async def ack(
        self, order_id: str, exchange_order_id: str, event_id: str | None = None
    ) -> Order:
        return await self.transition(
            order_id,
            OrderEventType.ORDER_ACKNOWLEDGED,
            event_id=event_id,
            exchange_order_id=exchange_order_id,
        )

    async def opened(self, order_id: str, event_id: str | None = None) -> Order:
        return await self.transition(order_id, OrderEventType.ORDER_OPENED, event_id=event_id)

    async def cancel_pending(self, order_id: str, reason: str = "user request") -> Order:
        return await self.transition(
            order_id, OrderEventType.ORDER_CANCEL_PENDING, payload={"reason": reason}
        )

    async def cancel_confirm(self, order_id: str, event_id: str | None = None) -> Order:
        return await self.transition(order_id, OrderEventType.ORDER_CANCELLED, event_id=event_id)

    async def reject(self, order_id: str, reason: str, event_id: str | None = None) -> Order:
        return await self.transition(
            order_id,
            OrderEventType.ORDER_REJECTED,
            event_id=event_id,
            rejection_reason=reason,
            payload={"reason": reason},
        )

    async def expire(self, order_id: str) -> Order:
        return await self.transition(order_id, OrderEventType.ORDER_EXPIRED)

    async def mark_unknown(self, order_id: str, reason: str) -> Order:
        return await self.transition(
            order_id, OrderEventType.ORDER_UNKNOWN, payload={"reason": reason}
        )

    async def apply_fill(self, fill: Fill) -> tuple[Order, Fill, bool]:
        """Apply a normalized fill exactly once. Returns (order, fill, newly_applied)."""
        async with self.session_factory() as session:
            existing = (
                await session.execute(select(FillORM).where(FillORM.fill_id == fill.fill_id))
            ).scalar_one_or_none()
            if existing is not None:
                return (
                    _orm_to_order(await session.get(OrderORM, existing.order_id)),
                    _orm_to_fill(existing),
                    False,
                )
            order_row: OrderORM | None = None
            if fill.exchange_order_id:
                order_row = (
                    await session.execute(
                        select(OrderORM).where(OrderORM.exchange_order_id == fill.exchange_order_id)
                    )
                ).scalar_one_or_none()
            if order_row is None:
                order_row = await session.get(OrderORM, fill.order_id)
            if order_row is None:
                raise OrderNotFound(f"cannot apply fill for unknown order {fill.order_id}")

            new_filled = order_row.filled_quantity + fill.quantity
            if new_filled > order_row.quantity:
                raise InvalidStateTransition(
                    f"fill quantity {fill.quantity} exceeds remaining "
                    f"{order_row.quantity - order_row.filled_quantity}"
                )
            fully_filled = new_filled == order_row.quantity
            event_type = (
                OrderEventType.ORDER_FILLED
                if fully_filled
                else OrderEventType.ORDER_PARTIALLY_FILLED
            )
            current = OrderStatus(order_row.status)
            result = OrderStateMachine.transition(current, event_type)
            previous_total = order_row.filled_quantity * (order_row.avg_fill_price or Decimal("0"))
            incremental = fill.price * fill.quantity
            new_avg = (
                (previous_total + incremental) / new_filled if new_filled > 0 else Decimal("0")
            )

            order_row.filled_quantity = new_filled
            order_row.avg_fill_price = new_avg
            order_row.status = result.new_status.value
            order_row.updated_at = fill.timestamp
            order_row.last_event_id = new_id("evt")
            if fill.exchange_order_id:
                order_row.exchange_order_id = fill.exchange_order_id
            event_id = new_id("evt")
            event = OrderEventORM(
                event_id=event_id,
                order_id=order_row.internal_order_id,
                client_order_id=order_row.client_order_id,
                exchange_order_id=order_row.exchange_order_id,
                event_type=event_type.value,
                status_after=result.new_status.value,
                timestamp=fill.timestamp,
                payload_json={"fill_id": fill.fill_id, "fill_quantity": str(fill.quantity)},
            )
            fill_row = FillORM(
                fill_id=fill.fill_id,
                trade_id=fill.trade_id or new_id("trd"),
                order_id=order_row.internal_order_id,
                client_order_id=order_row.client_order_id,
                exchange_order_id=order_row.exchange_order_id,
                symbol=fill.symbol,
                side=fill.side.value,
                price=fill.price,
                quantity=fill.quantity,
                fee=fill.fee,
                fee_currency=fill.fee_currency,
                timestamp=fill.timestamp,
                payload_json=fill.payload,
            )
            session.add_all([event, fill_row])
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                async with self.session_factory() as s2:
                    existing_after_race = (
                        await s2.execute(select(FillORM).where(FillORM.fill_id == fill.fill_id))
                    ).scalar_one_or_none()
                if existing_after_race is not None:
                    return (
                        _orm_to_order(await self.get(existing_after_race.order_id)),
                        _orm_to_fill(existing_after_race),
                        False,
                    )
                raise exc
        order = _orm_to_order(order_row)
        if self.settlement_callback is not None:
            await self.settlement_callback(fill)
        return order, fill, True

    async def get_fill(self, fill_id: str) -> Fill | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(FillORM).where(FillORM.fill_id == fill_id))
            ).scalar_one_or_none()
            return _orm_to_fill(row) if row else None

    async def list_events(self, order_id: str) -> list[OrderEvent]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(OrderEventORM)
                        .where(OrderEventORM.order_id == order_id)
                        .order_by(OrderEventORM.id)
                    )
                )
                .scalars()
                .all()
            )
            return [_orm_to_event(r) for r in rows]
