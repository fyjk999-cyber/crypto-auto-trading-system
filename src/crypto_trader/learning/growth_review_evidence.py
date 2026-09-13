"""Canonical causal evidence envelope for structured Growth review."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from crypto_trader.persistence.models import (
    FillORM,
    LLMDecisionORM,
    OrderORM,
    RiskDecisionORM,
    TradeEpisodeORM,
)

MISSING = "UNKNOWN"


class EvidenceAvailability(str):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _value(obj, name: str):
    return getattr(obj, name, None) if obj is not None else None


@dataclass
class GrowthReviewEvidence:
    episode_id: str
    account_id: str = "default"
    execution_mode: str = "PAPER"
    evidence_domain: str = "PAPER"
    symbol: str = MISSING
    direction: str = MISSING
    decision_id: str | None = None
    decision_action: Any = MISSING
    decision_thesis: Any = MISSING
    decision_conviction: Any = MISSING
    factor_snapshot_id: str | None = None
    factor_snapshot: Any = MISSING
    sizing_audit_id: str | None = None
    sizing_final_quantity: Any = MISSING
    sizing_risk_budget: Any = MISSING
    sizing_binding_cap: Any = MISSING
    requested_leverage: Any = MISSING
    approved_leverage: Any = MISSING
    stop_at_entry: Any = MISSING
    risk_decision_id: str | None = None
    risk_result: Any = MISSING
    risk_reason_codes: list[Any] = field(default_factory=list)
    order_ids: list[str] = field(default_factory=list)
    fill_ids: list[str] = field(default_factory=list)
    weighted_entry_price: Any = MISSING
    position_action_ids: list[str] = field(default_factory=list)
    position_lifecycle: list[Any] = field(default_factory=list)
    exit_decision_id: str | None = None
    exit_reason: Any = MISSING
    exit_order_ids: list[str] = field(default_factory=list)
    exit_fill_ids: list[str] = field(default_factory=list)
    weighted_exit_price: Any = MISSING
    holding_seconds: Any = MISSING
    gross_pnl: Any = MISSING
    fees: Any = MISSING
    funding: Any = MISSING
    slippage: Any = MISSING
    net_pnl: Any = MISSING
    mfe: Any = MISSING
    mae: Any = MISSING
    missing_evidence: list[str] = field(default_factory=list)
    known_at: str | None = None
    reviewed_at: str | None = None
    decision_availability: str = EvidenceAvailability.UNAVAILABLE
    factor_snapshot_availability: str = EvidenceAvailability.UNAVAILABLE
    sizing_availability: str = EvidenceAvailability.UNAVAILABLE
    risk_availability: str = EvidenceAvailability.UNAVAILABLE
    execution_availability: str = EvidenceAvailability.UNAVAILABLE
    position_lifecycle_availability: str = EvidenceAvailability.UNAVAILABLE
    exit_availability: str = EvidenceAvailability.UNAVAILABLE
    mfe_mae_availability: str = EvidenceAvailability.UNAVAILABLE
    slippage_availability: str = EvidenceAvailability.UNAVAILABLE
    fees_availability: str = EvidenceAvailability.AVAILABLE
    funding_availability: str = EvidenceAvailability.AVAILABLE

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)

    def validate_availability(self) -> None:
        checks = (
            ("decision_availability", "decision_id"),
            ("risk_availability", "risk_decision_id"),
        )
        for availability_field, reference_field in checks:
            if getattr(self, availability_field) == EvidenceAvailability.AVAILABLE and not getattr(self, reference_field, None):
                raise ValueError(f"CONTRADICTORY_AVAILABILITY:{availability_field}")
        for availability_field, value_field in (
            ("factor_snapshot_availability", "factor_snapshot"),
            ("sizing_availability", "sizing_final_quantity"),
            ("mfe_mae_availability", "mfe"),
            ("slippage_availability", "slippage"),
        ):
            if getattr(self, availability_field) != EvidenceAvailability.AVAILABLE and getattr(self, value_field, None) not in (None, MISSING):
                raise ValueError(f"CONTRADICTORY_AVAILABILITY:{availability_field}")
            if getattr(self, availability_field) == EvidenceAvailability.AVAILABLE and getattr(self, value_field, None) in (None, MISSING):
                raise ValueError(f"CONTRADICTORY_AVAILABILITY:{availability_field}")


class GrowthReviewEvidenceLoader:
    """Resolve canonical persisted facts; never recompute or invent them."""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def load(
        self,
        episode: TradeEpisodeORM,
        *,
        account_id: str = "default",
        mode: str = "PAPER",
        evidence_domain: str | None = None,
        now: datetime | None = None,
    ) -> GrowthReviewEvidence:
        evidence = GrowthReviewEvidence(
            episode_id=episode.episode_id,
            account_id=account_id,
            execution_mode=mode,
            evidence_domain=evidence_domain or mode,
            symbol=episode.symbol,
            direction=episode.direction,
            decision_id=episode.entry_decision_id,
            order_ids=list(episode.order_ids_json or []),
            fill_ids=list(episode.fill_ids_json or []),
            exit_decision_id=episode.exit_decision_id,
            exit_reason=episode.terminal_reason or MISSING,
            holding_seconds=episode.holding_time_seconds,
            gross_pnl=episode.gross_pnl,
            fees=episode.fees,
            funding=episode.funding_pnl,
            net_pnl=episode.net_pnl,
            known_at=(now or datetime.now(UTC)).isoformat(),
            reviewed_at=(now or datetime.now(UTC)).isoformat(),
        )
        async with self.session_factory() as session:
            if episode.entry_decision_id:
                decision = await session.get(
                    LLMDecisionORM, episode.entry_decision_id
                )
                if decision is None:
                    evidence.missing_evidence.append("DECISION")
                else:
                    evidence.decision_availability = EvidenceAvailability.AVAILABLE
                    evidence.decision_action = _value(decision, "action")
                    evidence.decision_thesis = _value(decision, "thesis")
                    evidence.decision_conviction = _value(
                        decision, "raw_llm_confidence"
                    )
            else:
                evidence.missing_evidence.append("DECISION")
            risk = (
                await session.execute(
                    select(RiskDecisionORM)
                    .where(RiskDecisionORM.decision_id == episode.entry_decision_id)
                    .limit(1)
                )
            ).scalar_one_or_none() if episode.entry_decision_id else None
            if risk is not None:
                evidence.risk_availability = EvidenceAvailability.AVAILABLE
                evidence.risk_decision_id = _value(risk, "decision_id")
                evidence.risk_result = _value(risk, "approved")
                evidence.risk_reason_codes = list(
                    _value(risk, "reason_codes") or []
                )
            else:
                evidence.missing_evidence.append("RISK")
            orders = (
                await session.execute(
                    select(OrderORM).where(
                        OrderORM.order_id.in_(tuple(evidence.order_ids or ["none"]))
                    )
                )
            ).scalars().all() if evidence.order_ids else []
            fills = (
                await session.execute(
                    select(FillORM).where(
                        FillORM.fill_id.in_(tuple(evidence.fill_ids or ["none"]))
                    )
                )
            ).scalars().all() if evidence.fill_ids else []
            if orders and fills:
                prices = [
                    float(_value(fill, "price"))
                    for fill in fills
                    if _value(fill, "price") is not None
                ]
                evidence.execution_availability = EvidenceAvailability.AVAILABLE
                evidence.weighted_entry_price = (
                    sum(prices) / len(prices) if prices else MISSING
                )
            else:
                evidence.missing_evidence.append("ORDERS_FILLS")
        for name in (
            "factor_snapshot",
            "sizing_audit_id",
            "sizing_final_quantity",
            "sizing_risk_budget",
            "sizing_binding_cap",
            "requested_leverage",
            "approved_leverage",
            "stop_at_entry",
            "slippage",
            "mfe",
            "mae",
        ):
            if getattr(evidence, name) is MISSING:
                evidence.missing_evidence.append(name.upper())
        return evidence
