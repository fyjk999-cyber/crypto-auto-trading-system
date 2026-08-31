"""Canonical durable TradePlan (full-lifecycle 13)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError


@dataclass(frozen=True)
class TradePlan:
    trade_plan_id: str
    decision_id: str
    symbol: str
    execution_symbol: str
    market_type: str
    direction: str
    entry_thesis: str
    llm_invocation_id: str | None = None
    selected_strategy: str | None = None
    strategy_version: str | None = None
    market_regime: str | None = None
    supporting_evidence: list = field(default_factory=list)
    contradicting_evidence: list = field(default_factory=list)
    invalidation_conditions: list = field(default_factory=list)
    target_conditions: list = field(default_factory=list)
    expected_horizon_seconds: float | None = None
    max_holding_time_seconds: float | None = None
    risk_intent: str = "NORMAL"
    entry_price_reference: str | None = None
    factor_snapshot_id: str | None = None
    tool_trace_id: str | None = None
    memory_refs: list = field(default_factory=list)
    status: str = "PLANNED"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_row(self) -> dict:
        return {
            "trade_plan_id": self.trade_plan_id,
            "decision_id": self.decision_id,
            "llm_invocation_id": self.llm_invocation_id,
            "symbol": self.symbol,
            "execution_symbol": self.execution_symbol,
            "market_type": self.market_type,
            "direction": self.direction,
            "selected_strategy": self.selected_strategy,
            "strategy_version": self.strategy_version,
            "market_regime": self.market_regime,
            "entry_thesis": self.entry_thesis[:500],
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "invalidation_conditions": self.invalidation_conditions,
            "target_conditions": self.target_conditions,
            "expected_horizon_seconds": self.expected_horizon_seconds,
            "max_holding_time_seconds": self.max_holding_time_seconds,
            "risk_intent": self.risk_intent[:16],
            "entry_price_reference": self.entry_price_reference,
            "factor_snapshot_id": self.factor_snapshot_id,
            "tool_trace_id": self.tool_trace_id,
            "memory_refs": self.memory_refs,
            "status": self.status[:16],
        }


class TradePlanStore:
    """Durable TradePlan persistence via SQLAlchemy JSON type semantics."""

    STATUS_TRANSITIONS = {
        "PLANNED": {"PLANNED", "OPEN", "INVALIDATED"},
        "OPEN": {"OPEN", "MANAGING", "CLOSED"},
        "MANAGING": {"MANAGING", "EXIT_REQUESTED", "CLOSED"},
        "EXIT_REQUESTED": {"EXIT_REQUESTED", "CLOSED"},
        "CLOSED": {"CLOSED"},
        "INVALIDATED": {"INVALIDATED"},
    }

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def _table(self):
        from crypto_trader.persistence.models import TradePlanORM

        return TradePlanORM.__table__

    def _row(self, plan: TradePlan) -> dict:
        return plan.to_row()

    async def put(self, plan: TradePlan) -> str:
        """Create an immutable original TradePlan.

        Idempotent by decision_id: one entry decision == one TradePlan.
        If a plan already exists for the same trade_plan_id or decision_id,
        this is a NO-OP and returns the existing trade_plan_id. Status
        transitions are only allowed via update_status().
        """
        from crypto_trader.persistence.models import TradePlanORM

        async with self.session_factory() as session:
            by_pk = (
                await session.execute(
                    select(TradePlanORM).where(
                        TradePlanORM.trade_plan_id == plan.trade_plan_id
                    )
                )
            ).scalar_one_or_none()
            if by_pk is not None:
                return by_pk.trade_plan_id
            by_decision = (
                await session.execute(
                    select(TradePlanORM).where(
                        TradePlanORM.decision_id == plan.decision_id
                    )
                )
            ).scalar_one_or_none()
            if by_decision is not None:
                return by_decision.trade_plan_id
            row = self._row(plan)
            session.add(TradePlanORM(**row))
            try:
                await session.commit()
                return plan.trade_plan_id
            except IntegrityError:
                # Concurrent duplicate decision_id: the other writer won.
                await session.rollback()
                by_decision = (
                    await session.execute(
                        select(TradePlanORM).where(
                            TradePlanORM.decision_id == plan.decision_id
                        )
                    )
                ).scalar_one_or_none()
                return by_decision.trade_plan_id if by_decision else plan.trade_plan_id

    async def get(self, trade_plan_id: str) -> dict | None:
        from crypto_trader.persistence.models import TradePlanORM

        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(TradePlanORM).where(
                        TradePlanORM.trade_plan_id == trade_plan_id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return {
                "trade_plan_id": row.trade_plan_id,
                "decision_id": row.decision_id,
                "llm_invocation_id": row.llm_invocation_id,
                "symbol": row.symbol,
                "execution_symbol": row.execution_symbol,
                "market_type": row.market_type,
                "direction": row.direction,
                "selected_strategy": row.selected_strategy,
                "strategy_version": row.strategy_version,
                "market_regime": row.market_regime,
                "entry_thesis": row.entry_thesis,
                "supporting_evidence": row.supporting_evidence or [],
                "contradicting_evidence": row.contradicting_evidence or [],
                "invalidation_conditions": row.invalidation_conditions or [],
                "target_conditions": row.target_conditions or [],
                "expected_horizon_seconds": row.expected_horizon_seconds,
                "max_holding_time_seconds": row.max_holding_time_seconds,
                "risk_intent": row.risk_intent,
                "entry_price_reference": row.entry_price_reference,
                "factor_snapshot_id": row.factor_snapshot_id,
                "tool_trace_id": row.tool_trace_id,
                "memory_refs": row.memory_refs or [],
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }

    async def get_by_decision_id(self, decision_id: str) -> dict | None:
        from crypto_trader.persistence.models import TradePlanORM

        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(TradePlanORM).where(
                        TradePlanORM.decision_id == decision_id
                    )
                )
            ).scalar_one_or_none()
            return await self.get(row.trade_plan_id) if row else None

    async def get_active_by_execution_symbol(self, execution_symbol: str) -> dict | None:
        from crypto_trader.persistence.models import TradePlanORM

        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(TradePlanORM)
                    .where(TradePlanORM.execution_symbol == execution_symbol)
                    .where(TradePlanORM.status.in_(["OPEN", "MANAGING"]))
                    .order_by(TradePlanORM.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return await self.get(row.trade_plan_id) if row else None

    async def list_active(self) -> list[dict]:
        from crypto_trader.persistence.models import TradePlanORM

        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(TradePlanORM).where(
                        TradePlanORM.status.in_(["OPEN", "MANAGING"])
                    )
                )
            ).scalars().all()
            return [await self.get(r.trade_plan_id) for r in rows]

    async def count_all(self) -> int:
        from crypto_trader.persistence.models import TradePlanORM

        async with self.session_factory() as session:
            return int(
                (await session.execute(select(func.count()).select_from(TradePlanORM))).scalar()
            )

    async def update_status(self, trade_plan_id: str, status: str) -> bool:
        """Validate and apply a status transition. Idempotent for same state."""
        from crypto_trader.persistence.models import TradePlanORM

        current = await self.get(trade_plan_id)
        if current is None:
            return False
        old = current["status"]
        if status not in self.STATUS_TRANSITIONS.get(old, set()):
            return False
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(TradePlanORM).where(
                        TradePlanORM.trade_plan_id == trade_plan_id
                    )
                )
            ).scalar_one_or_none()
            if row is not None:
                row.status = status
                await session.commit()
        return True
