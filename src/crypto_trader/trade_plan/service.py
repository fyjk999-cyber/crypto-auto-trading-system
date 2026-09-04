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
    signal_id: str | None
    risk_decision_id: str | None
    order_id: str | None
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
    ) -> TradePlan:
        if direction not in {"LONG", "SHORT"} or requested_quantity <= 0:
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
            signal_id=row.signal_id,
            risk_decision_id=row.risk_decision_id,
            order_id=row.order_id,
            terminal_reason=row.terminal_reason,
        )
