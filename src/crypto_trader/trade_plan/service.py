"""Idempotent persistence and state transitions for LLM-backed TradePlans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from crypto_trader.domain.identifiers import new_id
from crypto_trader.persistence.models import TradePlanORM


class TradePlanState(StrEnum):
    PLANNED = "PLANNED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    CLOSED = "CLOSED"


TERMINAL_STATES = {
    TradePlanState.REJECTED,
    TradePlanState.CANCELLED,
    TradePlanState.EXPIRED,
    TradePlanState.INVALIDATED,
    TradePlanState.CLOSED,
}

ALLOWED_TRANSITIONS = {
    TradePlanState.PLANNED: {
        TradePlanState.APPROVED,
        TradePlanState.REJECTED,
        TradePlanState.CANCELLED,
        TradePlanState.EXPIRED,
        TradePlanState.INVALIDATED,
    },
    TradePlanState.APPROVED: {
        TradePlanState.ACTIVE,
        TradePlanState.CANCELLED,
        TradePlanState.EXPIRED,
        TradePlanState.INVALIDATED,
    },
    TradePlanState.ACTIVE: {TradePlanState.CLOSED, TradePlanState.INVALIDATED},
}


@dataclass(frozen=True)
class TradePlan:
    trade_plan_id: str
    decision_id: str
    symbol: str
    direction: str
    state: TradePlanState
    thesis: str
    requested_quantity: Decimal
    requested_leverage: Decimal | None
    requested_exposure: Decimal | None
    entry_conditions: list[str]
    invalidation_conditions: list[str]
    reduce_conditions: list[str]
    exit_conditions: list[str]
    expected_holding_period: str
    max_holding_time_seconds: float
    signal_id: str | None
    risk_decision_id: str | None
    order_id: str | None
    latest_position_decision_id: str | None
    exit_decision_id: str | None
    opened_at: datetime | None
    closed_at: datetime | None
    terminal_reason: str | None


class TradePlanService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def create(
        self,
        *,
        decision_id: str,
        symbol: str,
        direction: str,
        thesis: str,
        requested_quantity: Decimal,
        requested_leverage: Decimal | None = None,
        requested_exposure: Decimal | None = None,
        entry_conditions: list[str] | None = None,
        invalidation_conditions: list[str] | None = None,
        reduce_conditions: list[str] | None = None,
        exit_conditions: list[str] | None = None,
        expected_holding_period: str = "",
        max_holding_time_seconds: float = 86400.0,
    ) -> TradePlan:
        if (
            direction not in {"LONG", "SHORT"}
            or requested_quantity <= 0
            or max_holding_time_seconds <= 0
        ):
            raise ValueError("TradePlan requires a directional positive-size proposal")
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(TradePlanORM).where(TradePlanORM.decision_id == decision_id)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return self._to_domain(existing)
            row = TradePlanORM(
                trade_plan_id=new_id("plan"),
                decision_id=decision_id,
                symbol=symbol,
                direction=direction,
                state=TradePlanState.PLANNED.value,
                thesis=thesis,
                requested_quantity=requested_quantity,
                requested_leverage=requested_leverage,
                requested_exposure=requested_exposure,
                entry_conditions_json=list(entry_conditions or []),
                invalidation_conditions_json=list(invalidation_conditions or []),
                reduce_conditions_json=list(reduce_conditions or []),
                exit_conditions_json=list(exit_conditions or []),
                expected_holding_period=expected_holding_period,
                max_holding_time_seconds=max_holding_time_seconds,
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                row = (
                    await session.execute(
                        select(TradePlanORM).where(TradePlanORM.decision_id == decision_id)
                    )
                ).scalar_one()
            return self._to_domain(row)

    async def get(self, trade_plan_id: str) -> TradePlan | None:
        async with self.session_factory() as session:
            row = await session.get(TradePlanORM, trade_plan_id)
            return self._to_domain(row) if row is not None else None

    async def get_by_order(self, order_id: str) -> TradePlan | None:
        """Resolve factual execution lineage without trusting signal metadata."""
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(TradePlanORM).where(TradePlanORM.order_id == order_id)
                )
            ).scalar_one_or_none()
            return self._to_domain(row) if row is not None else None

    async def get_active_for_symbol(self, symbol: str) -> TradePlan | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(TradePlanORM)
                    .where(
                        TradePlanORM.symbol == symbol,
                        TradePlanORM.state == TradePlanState.ACTIVE.value,
                    )
                    .order_by(TradePlanORM.opened_at.desc(), TradePlanORM.created_at.desc())
                )
            ).scalars().first()
            return self._to_domain(row) if row is not None else None

    async def transition(
        self, trade_plan_id: str, state: TradePlanState, *, reason: str | None = None
    ) -> TradePlan:
        async with self.session_factory() as session:
            row = await session.get(TradePlanORM, trade_plan_id)
            if row is None:
                raise KeyError(f"unknown TradePlan: {trade_plan_id}")
            current = TradePlanState(row.state)
            if current == state:
                return self._to_domain(row)
            if state not in ALLOWED_TRANSITIONS.get(current, set()):
                raise ValueError(f"invalid TradePlan transition: {current} -> {state}")
            row.state = state.value
            row.updated_at = datetime.now(UTC)
            if state == TradePlanState.ACTIVE and row.opened_at is None:
                row.opened_at = row.updated_at
                row.position_symbol = row.symbol
            if state == TradePlanState.CLOSED:
                row.closed_at = row.updated_at
            if state in TERMINAL_STATES:
                row.terminal_reason = reason or state.value
            await session.commit()
            return self._to_domain(row)

    async def link(
        self,
        trade_plan_id: str,
        *,
        signal_id: str | None = None,
        risk_decision_id: str | None = None,
        order_id: str | None = None,
    ) -> TradePlan:
        async with self.session_factory() as session:
            row = await session.get(TradePlanORM, trade_plan_id)
            if row is None:
                raise KeyError(f"unknown TradePlan: {trade_plan_id}")
            if signal_id is not None:
                row.signal_id = signal_id
            if risk_decision_id is not None:
                row.risk_decision_id = risk_decision_id
            if order_id is not None:
                row.order_id = order_id
            row.updated_at = datetime.now(UTC)
            await session.commit()
        return self._to_domain(row)

    async def link_position_decision(
        self,
        trade_plan_id: str,
        decision_id: str,
        *,
        is_exit: bool = False,
    ) -> TradePlan:
        async with self.session_factory() as session:
            row = await session.get(TradePlanORM, trade_plan_id)
            if row is None:
                raise KeyError(f"unknown TradePlan: {trade_plan_id}")
            if TradePlanState(row.state) != TradePlanState.ACTIVE:
                raise ValueError("position decisions require an ACTIVE TradePlan")
            row.latest_position_decision_id = decision_id
            if is_exit:
                row.exit_decision_id = decision_id
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return self._to_domain(row)

    @staticmethod
    def _to_domain(row: TradePlanORM) -> TradePlan:
        return TradePlan(
            trade_plan_id=row.trade_plan_id,
            decision_id=row.decision_id,
            symbol=row.symbol,
            direction=row.direction,
            state=TradePlanState(row.state),
            thesis=row.thesis,
            requested_quantity=row.requested_quantity,
            requested_leverage=row.requested_leverage,
            requested_exposure=row.requested_exposure,
            entry_conditions=list(row.entry_conditions_json or []),
            invalidation_conditions=list(row.invalidation_conditions_json or []),
            reduce_conditions=list(row.reduce_conditions_json or []),
            exit_conditions=list(row.exit_conditions_json or []),
            expected_holding_period=row.expected_holding_period,
            max_holding_time_seconds=row.max_holding_time_seconds,
            signal_id=row.signal_id,
            risk_decision_id=row.risk_decision_id,
            order_id=row.order_id,
            latest_position_decision_id=row.latest_position_decision_id,
            exit_decision_id=row.exit_decision_id,
            opened_at=row.opened_at,
            closed_at=row.closed_at,
            terminal_reason=row.terminal_reason,
        )
