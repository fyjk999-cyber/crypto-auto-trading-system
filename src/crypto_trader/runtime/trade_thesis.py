"""Trade Thesis (STRATEGY DIRECTIVE §13/§14).

A compact structured thesis is lifted from the canonical Chief Trader
decision record — never reconstructed from strategy+fit and never invented.
Missing fields stay None (rendered as NOT_AVAILABLE downstream) so the
thesis is always truthful about what the AI actually provided at entry.

The thesis is EVIDENCE for later AI re-evaluation (§14): it must never be
turned into a hard auto-exit rule by itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


def _first(*values):
    for v in values:
        if v is not None and v != "" and v != []:
            return v
    return None


@dataclass(slots=True)
class TradeThesis:
    symbol: str
    direction: str
    entry_time: datetime
    decision_id: str
    strategy: str | None = None
    entry_reason: str | None = None
    supporting_evidence: list = field(default_factory=list)
    contradicting_evidence: list = field(default_factory=list)
    expected_market_behavior: str | None = None
    invalidation_conditions: list = field(default_factory=list)
    target_conditions: list = field(default_factory=list)
    max_holding_time_seconds: float | None = None
    review_interval_seconds: float | None = None
    llm_invocation_id: str | None = None
    strategy_version: str | None = None
    policy_version: int | None = None
    memory_refs: list = field(default_factory=list)
    tool_refs: list = field(default_factory=list)
    stop_loss: str | None = None
    take_profit: str | None = None

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "strategy": self.strategy,
            "entry_reason": self.entry_reason,
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "expected_market_behavior": self.expected_market_behavior,
            "invalidation_conditions": self.invalidation_conditions,
            "target_conditions": self.target_conditions,
            "entry_time": self.entry_time.isoformat(),
            "max_holding_time_seconds": self.max_holding_time_seconds,
            "review_interval_seconds": self.review_interval_seconds,
            "decision_id": self.decision_id,
            "llm_invocation_id": self.llm_invocation_id,
            "strategy_version": self.strategy_version,
            "policy_version": self.policy_version,
            "memory_refs": self.memory_refs,
            "tool_refs": self.tool_refs,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
        }


def thesis_from_decision_payload(
    payload: dict,
    *,
    entry_time: datetime | None = None,
    max_holding_time_seconds: float | None = None,
    policy_version: int | None = None,
) -> TradeThesis | None:
    """Lift a TradeThesis from the canonical decision evidence payload.

    `payload` is the decision_evidence decision_json dict (or the in-memory
    decision fields with the same names). Returns None when the payload does
    not describe an actual entry decision (no direction action).
    """
    action = str(payload.get("action") or "").upper()
    if action not in ("LONG", "SHORT"):
        return None

    entry_time = entry_time or datetime.now(UTC)
    supporting = payload.get("supporting_evidence") or payload.get("supporting_factors") or []
    contradicting = (
        payload.get("contradicting_evidence") or payload.get("contradicting_factors") or []
    )
    invalidations = payload.get("invalidation_conditions") or []
    exits = payload.get("exit_conditions") or []
    if isinstance(exits, str):
        exits = [exits]

    return TradeThesis(
        symbol=str(payload.get("symbol") or ""),
        direction=action,
        strategy=_first(payload.get("strategy_selected"), payload.get("selected_strategy")),
        entry_reason=_first(payload.get("thesis"), payload.get("dominant_factor")),
        supporting_evidence=(
            list(supporting)
            if isinstance(supporting, (list, tuple))
            else [str(supporting)]
        ),
        contradicting_evidence=(
            list(contradicting)
            if isinstance(contradicting, (list, tuple))
            else [str(contradicting)]
        ),
        expected_market_behavior=_first(
            payload.get("expected_return"), payload.get("expected_market_behavior")
        ),
        invalidation_conditions=(
            list(invalidations)
            if isinstance(invalidations, (list, tuple))
            else [str(invalidations)]
        ),
        target_conditions=list(exits) if exits else [],
        entry_time=entry_time,
        max_holding_time_seconds=(
            float(payload.get("expected_holding_period"))
            if payload.get("expected_holding_period")
            else max_holding_time_seconds
        ),
        review_interval_seconds=None,
        decision_id=str(payload.get("decision_id") or ""),
        llm_invocation_id=_first(payload.get("llm_invocation_id")),
        strategy_version=_first(payload.get("strategy_version")),
        policy_version=policy_version,
        memory_refs=list(payload.get("memory_refs") or []),
        tool_refs=(
            list(payload.get("knowledge_refs") or [])
            + list(payload.get("pattern_refs") or [])
        ),
        stop_loss=_first(payload.get("stop_loss")),
        take_profit=_first(payload.get("take_profit")),
    )
