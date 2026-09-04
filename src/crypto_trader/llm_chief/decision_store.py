"""Durable canonical store for ChiefTrader decisions and their lineage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from crypto_trader.llm_chief.decision import ChiefTraderDecision, PositionState
from crypto_trader.persistence.models import LLMDecisionORM


@dataclass(frozen=True)
class LLMDecisionRecord:
    decision_id: str
    run_id: str | None
    symbol: str
    position_state: PositionState
    action: str
    model_provider: str
    model: str
    model_version: str
    prompt_version: str
    thesis: str
    trade_plan_id: str | None
    created_at: datetime


class LLMDecisionStore:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def save(
        self,
        decision: ChiefTraderDecision,
        *,
        run_id: str | None,
        prompt_version: str,
        tool_refs: list[str] | None = None,
        research_refs: list[str] | None = None,
        episode_refs: list[str] | None = None,
        parent_decision_id: str | None = None,
        position_context: dict[str, Any] | None = None,
    ) -> LLMDecisionRecord:
        position = position_context or {}
        async with self.session_factory() as session:
            row = await session.get(LLMDecisionORM, decision.decision_id)
            if row is None:
                row = LLMDecisionORM(
                    decision_id=decision.decision_id,
                    run_id=run_id,
                    symbol=decision.symbol,
                    position_state=decision.position_state.value,
                    action=decision.action.value,
                    model_provider=decision.model_provider,
                    model=decision.model,
                    model_version=decision.model_version,
                    prompt_version=prompt_version,
                    market_regime=decision.market_regime,
                    thesis=decision.thesis,
                    supporting_evidence_json=decision.supporting_evidence,
                    contradicting_evidence_json=decision.contradicting_evidence,
                    tool_refs_json=tool_refs or [],
                    memory_refs_json=decision.memory_refs,
                    research_refs_json=research_refs or [],
                    episode_refs_json=episode_refs or [],
                    requested_exposure=_decimal_or_none(position.get("requested_exposure")),
                    requested_quantity=Decimal(str(decision.position_size_request)),
                    requested_leverage=Decimal(str(decision.leverage_request)),
                    parent_decision_id=parent_decision_id,
                    position_quantity_before=_decimal_or_none(position.get("quantity")),
                    entry_price=_decimal_or_none(position.get("entry_price")),
                    mark_price=_decimal_or_none(position.get("mark_price")),
                    unrealized_pnl=_decimal_or_none(position.get("unrealized_pnl")),
                    time_in_trade_seconds=_float_or_none(position.get("time_in_trade_seconds")),
                    original_trade_plan_id=position.get("trade_plan_id"),
                    original_entry_decision_id=position.get("entry_decision_id"),
                    created_at=_created_at(decision.created_at),
                )
                session.add(row)
                await session.commit()
            return self._record(row)

    async def link_trade_plan(self, decision_id: str, trade_plan_id: str) -> None:
        async with self.session_factory() as session:
            row = await session.get(LLMDecisionORM, decision_id)
            if row is None:
                raise KeyError(f"unknown LLM decision: {decision_id}")
            if row.trade_plan_id not in {None, trade_plan_id}:
                raise ValueError("LLM decision already linked to a different TradePlan")
            row.trade_plan_id = trade_plan_id
            await session.commit()

    async def get(self, decision_id: str) -> LLMDecisionRecord | None:
        async with self.session_factory() as session:
            row = await session.get(LLMDecisionORM, decision_id)
            return self._record(row) if row is not None else None

    async def list_for_symbol(self, symbol: str) -> list[LLMDecisionRecord]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(LLMDecisionORM)
                    .where(LLMDecisionORM.symbol == symbol)
                    .order_by(LLMDecisionORM.created_at, LLMDecisionORM.decision_id)
                )
            ).scalars()
            return [self._record(row) for row in rows]

    @staticmethod
    def _record(row: LLMDecisionORM) -> LLMDecisionRecord:
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return LLMDecisionRecord(
            decision_id=row.decision_id,
            run_id=row.run_id,
            symbol=row.symbol,
            position_state=PositionState(row.position_state),
            action=row.action,
            model_provider=row.model_provider,
            model=row.model,
            model_version=row.model_version,
            prompt_version=row.prompt_version,
            thesis=row.thesis,
            trade_plan_id=row.trade_plan_id,
            created_at=created_at,
        )


def _decimal_or_none(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _float_or_none(value: Any) -> float | None:
    return float(value) if value is not None else None


def _created_at(value: str) -> datetime:
    if not value:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
