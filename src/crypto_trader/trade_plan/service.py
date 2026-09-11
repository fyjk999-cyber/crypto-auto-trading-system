"""Idempotent persistence and state transitions for LLM-backed TradePlans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from crypto_trader.domain.identifiers import new_id
from crypto_trader.persistence.models import (
    LLMDecisionORM,
    PositionProjectionORM,
    TradePlanORM,
)


class TradePlanState(StrEnum):
    PLANNED = "PLANNED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    RECOVERY = "RECOVERY"
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
    TradePlanState.ACTIVE: {TradePlanState.CLOSED},
    TradePlanState.RECOVERY: {TradePlanState.CLOSED, TradePlanState.INVALIDATED},
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
        entry_conditions = list(entry_conditions or [])
        invalidation_conditions = list(invalidation_conditions or [])
        reduce_conditions = list(reduce_conditions or [])
        exit_conditions = list(exit_conditions or [])
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(TradePlanORM).where(TradePlanORM.decision_id == decision_id)
                )
            ).scalar_one_or_none()
            if existing is not None:
                immutable = {
                    "symbol": symbol,
                    "direction": direction,
                    "thesis": thesis,
                    "requested_quantity": requested_quantity,
                    "requested_leverage": requested_leverage,
                    "requested_exposure": requested_exposure,
                    "entry_conditions_json": entry_conditions,
                    "invalidation_conditions_json": invalidation_conditions,
                    "reduce_conditions_json": reduce_conditions,
                    "exit_conditions_json": exit_conditions,
                    "expected_holding_period": expected_holding_period,
                    "max_holding_time_seconds": max_holding_time_seconds,
                }
                conflicts = [
                    field
                    for field, expected in immutable.items()
                    if getattr(existing, field) != expected
                ]
                if conflicts:
                    raise ValueError(
                        "immutable TradePlan conflict: " + ",".join(conflicts)
                    )
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
                entry_conditions_json=entry_conditions,
                invalidation_conditions_json=invalidation_conditions,
                reduce_conditions_json=reduce_conditions,
                exit_conditions_json=exit_conditions,
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
                        TradePlanORM.state.in_(
                            (
                                TradePlanState.ACTIVE.value,
                                TradePlanState.RECOVERY.value,
                            )
                        ),
                    )
                    .order_by(TradePlanORM.opened_at.desc(), TradePlanORM.created_at.desc())
                )
            ).scalars().first()
            return self._to_domain(row) if row is not None else None

    async def ensure_recovery_plan(
        self,
        *,
        symbol: str,
        direction: str,
        quantity: Decimal,
        entry_price: Decimal | None = None,
    ) -> TradePlan:
        """Create an explicit ORPHAN recovery plan without fabricating a fill.

        A factual exchange position without an active TradePlan must be
        reconciled only through the normal reduce-only signal -> Risk ->
        ExecutionAuthority -> OrderManager path. This method creates the
        durable RECOVERY lifecycle that path reviews; it never submits orders.
        """
        if direction not in {"LONG", "SHORT"} or quantity <= 0:
            raise ValueError("recovery plan requires direction and positive quantity")
        decision_id = f"orphan_recovery_{symbol}"
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(TradePlanORM)
                    .where(
                        TradePlanORM.decision_id == decision_id,
                        TradePlanORM.state == TradePlanState.RECOVERY.value,
                    )
                    .order_by(TradePlanORM.created_at.desc())
                )
            ).scalars().first()
            if existing is not None:
                return self._to_domain(existing)
            any_plan = (
                await session.execute(
                    select(TradePlanORM).where(TradePlanORM.decision_id == decision_id)
                )
            ).scalars().first()
            if any_plan is not None:
                return self._to_domain(any_plan)
            row = TradePlanORM(
                trade_plan_id=new_id("plan"),
                decision_id=decision_id,
                symbol=symbol,
                direction=direction,
                state=TradePlanState.RECOVERY.value,
                thesis="ORPHAN_POSITION_RECOVERY: factual exchange position without active plan",
                requested_quantity=quantity,
                requested_leverage=Decimal("1"),
                requested_exposure=None,
                entry_conditions_json=[],
                invalidation_conditions_json=[],
                reduce_conditions_json=["RECOVER_TO_ZERO"],
                exit_conditions_json=["FACTUAL_ZERO_POSITION"],
                expected_holding_period="ORPHAN_RECOVERY",
                max_holding_time_seconds=1.0,
                opened_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                row = (
                    await session.execute(
                        select(TradePlanORM).where(
                            TradePlanORM.decision_id == decision_id
                        )
                    )
                ).scalar_one()
            return self._to_domain(row)

    async def plan_covering(
        self, symbol: str, instant: datetime
    ) -> TradePlan | None:
        """The single factual lifecycle covering a settlement instant."""
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(TradePlanORM)
                    .where(
                        TradePlanORM.symbol == symbol,
                        TradePlanORM.state.in_(
                            (
                                TradePlanState.ACTIVE.value,
                                TradePlanState.CLOSED.value,
                            )
                        ),
                        TradePlanORM.opened_at.is_not(None),
                        TradePlanORM.opened_at < instant,
                        or_(
                            TradePlanORM.closed_at.is_(None),
                            TradePlanORM.closed_at >= instant,
                        ),
                    )
                    .order_by(TradePlanORM.opened_at.desc(), TradePlanORM.trade_plan_id)
                )
            ).scalars().all()
        if len(rows) != 1:
            return None
        return self._to_domain(rows[0])

    async def lifecycles_overlapping(
        self, start: datetime, end: datetime
    ) -> list[TradePlan]:
        """Every factual lifecycle whose holding interval intersects window."""
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(TradePlanORM)
                    .where(
                        TradePlanORM.opened_at.is_not(None),
                        TradePlanORM.opened_at < end,
                        TradePlanORM.state.in_(
                            (
                                TradePlanState.ACTIVE.value,
                                TradePlanState.CLOSED.value,
                            )
                        ),
                        or_(
                            TradePlanORM.closed_at.is_(None),
                            TradePlanORM.closed_at >= start,
                        ),
                    )
                    .order_by(TradePlanORM.opened_at, TradePlanORM.trade_plan_id)
                )
            ).scalars().all()
            return [self._to_domain(row) for row in rows]

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
            if state == TradePlanState.CLOSED:
                raise ValueError(
                    "CLOSED requires the factual close method and zero position evidence"
                )
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
            links = {
                "signal_id": signal_id,
                "risk_decision_id": risk_decision_id,
                "order_id": order_id,
            }
            for field, value in links.items():
                if value is None:
                    continue
                current = getattr(row, field)
                if current is not None and current != value:
                    raise ValueError(
                        f"immutable TradePlan entry lineage conflict: {field}"
                    )
                setattr(row, field, value)
            row.updated_at = datetime.now(UTC)
            await session.commit()
        return self._to_domain(row)

    async def link_position_decision(
        self,
        trade_plan_id: str,
        decision_id: str,
    ) -> TradePlan:
        async with self.session_factory() as session:
            row = await session.get(TradePlanORM, trade_plan_id)
            if row is None:
                raise KeyError(f"unknown TradePlan: {trade_plan_id}")
            if TradePlanState(row.state) not in {
                TradePlanState.ACTIVE,
                TradePlanState.RECOVERY,
            }:
                raise ValueError(
                    "position decisions require an ACTIVE/RECOVERY TradePlan"
                )
            row.latest_position_decision_id = decision_id
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return self._to_domain(row)

    async def close_from_factual_position(
        self,
        trade_plan_id: str,
        *,
        exit_decision_id: str,
        reason: str,
    ) -> TradePlan:
        """Close an ACTIVE plan only at the factual zero-position boundary."""

        async with self.session_factory() as session:
            row = await session.get(TradePlanORM, trade_plan_id)
            if row is None:
                raise KeyError(f"unknown TradePlan: {trade_plan_id}")
            current = TradePlanState(row.state)
            if current == TradePlanState.CLOSED:
                if row.exit_decision_id != exit_decision_id:
                    raise ValueError("closed TradePlan exit lineage is immutable")
                return self._to_domain(row)
            if current not in {TradePlanState.ACTIVE, TradePlanState.RECOVERY}:
                raise ValueError("factual close requires an ACTIVE/RECOVERY TradePlan")
            position = (
                await session.execute(
                    select(PositionProjectionORM).where(
                        PositionProjectionORM.symbol == row.symbol
                    )
                )
            ).scalar_one_or_none()
            if position is None or position.quantity != 0:
                raise ValueError("cannot close TradePlan with non-zero factual position")
            exit_decision = await session.get(LLMDecisionORM, exit_decision_id)
            if (
                exit_decision is None
                or exit_decision.position_state != "OPEN"
                or exit_decision.original_trade_plan_id != trade_plan_id
                or exit_decision.original_entry_decision_id != row.decision_id
            ):
                raise ValueError("factual close requires canonical OPEN decision lineage")
            row.exit_decision_id = exit_decision_id
            row.state = TradePlanState.CLOSED.value
            row.updated_at = datetime.now(UTC)
            row.closed_at = row.updated_at
            row.terminal_reason = reason
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
