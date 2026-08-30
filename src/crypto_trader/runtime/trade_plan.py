"""Canonical durable TradePlan (full-lifecycle 13)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import text


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
    """Durable TradePlan persistence (versioned schema; no runtime DDL)."""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def put(self, plan: TradePlan) -> None:
        import json

        row = {k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
               for k, v in plan.to_row().items()}
        async with self.session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO trade_plans (trade_plan_id, decision_id, "
                    "llm_invocation_id, symbol, execution_symbol, market_type, "
                    "direction, selected_strategy, strategy_version, market_regime, "
                    "entry_thesis, supporting_evidence, contradicting_evidence, "
                    "invalidation_conditions, target_conditions, "
                    "expected_horizon_seconds, max_holding_time_seconds, "
                    "risk_intent, entry_price_reference, factor_snapshot_id, "
                    "tool_trace_id, memory_refs, status, created_at) "
                    "VALUES (:trade_plan_id, :decision_id, :llm_invocation_id, "
                    ":symbol, :execution_symbol, :market_type, :direction, "
                    ":selected_strategy, :strategy_version, :market_regime, "
                    ":entry_thesis, :supporting_evidence, :contradicting_evidence, "
                    ":invalidation_conditions, :target_conditions, "
                    ":expected_horizon_seconds, :max_holding_time_seconds, "
                    ":risk_intent, :entry_price_reference, :factor_snapshot_id, "
                    ":tool_trace_id, :memory_refs, :status, :created_at) "
                    "ON CONFLICT (trade_plan_id) DO UPDATE SET status=excluded.status"
                ),
                {**row, "created_at": datetime.now(UTC).replace(tzinfo=None)},
            )
            await session.commit()

    async def get(self, trade_plan_id: str) -> dict | None:
        async with self.session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT trade_plan_id, decision_id, llm_invocation_id, symbol, "
                    "execution_symbol, market_type, direction, selected_strategy, "
                    "strategy_version, market_regime, entry_thesis, "
                    "supporting_evidence, contradicting_evidence, "
                    "invalidation_conditions, target_conditions, "
                    "expected_horizon_seconds, max_holding_time_seconds, "
                    "risk_intent, entry_price_reference, factor_snapshot_id, "
                    "tool_trace_id, memory_refs, status, created_at "
                    "FROM trade_plans WHERE trade_plan_id = :id"
                ),
                {"id": trade_plan_id},
            )
            row = result.mappings().first()
            return dict(row) if row else None
