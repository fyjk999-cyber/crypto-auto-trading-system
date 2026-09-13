"""Canonical causal evidence envelope for structured Growth review."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
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


def _episode_ids(episode, domain_name: str, json_name: str) -> list[str]:
    if hasattr(episode, domain_name):
        return list(getattr(episode, domain_name) or [])
    return list(getattr(episode, json_name, None) or [])


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
    risk_decision_ids: list[str] = field(default_factory=list)
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
            available = (
                getattr(self, availability_field)
                == EvidenceAvailability.AVAILABLE
            )
            if available and not getattr(self, reference_field, None):
                raise ValueError(
                    f"CONTRADICTORY_AVAILABILITY:{availability_field}"
                )
            if (
                availability_field == "risk_availability"
                and available
                and (
                    not self.risk_decision_ids
                    or self.risk_decision_id != self.risk_decision_ids[0]
                )
            ):
                raise ValueError("CONTRADICTORY_AVAILABILITY:risk_decision_ids")
        if (
            self.execution_availability == EvidenceAvailability.AVAILABLE
            and (not self.order_ids or not self.fill_ids)
        ):
            raise ValueError(
                "CONTRADICTORY_AVAILABILITY:execution_availability"
            )
        if (
            self.exit_availability == EvidenceAvailability.AVAILABLE
            and str(self.exit_reason or "").strip() in {"", MISSING}
        ):
            raise ValueError("CONTRADICTORY_AVAILABILITY:exit_availability")
        for availability_field, value_field in (
            ("factor_snapshot_availability", "factor_snapshot"),
            ("sizing_availability", "sizing_final_quantity"),
            ("mfe_mae_availability", "mfe"),
            ("slippage_availability", "slippage"),
        ):
            availability = getattr(self, availability_field)
            value = getattr(self, value_field, None)
            has_value = value not in (None, MISSING)
            if availability != EvidenceAvailability.AVAILABLE and has_value:
                raise ValueError(
                    f"CONTRADICTORY_AVAILABILITY:{availability_field}"
                )
            if availability == EvidenceAvailability.AVAILABLE and not has_value:
                raise ValueError(
                    f"CONTRADICTORY_AVAILABILITY:{availability_field}"
                )



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
            order_ids=_episode_ids(episode, "order_ids", "order_ids_json"),
            fill_ids=_episode_ids(episode, "fill_ids", "fill_ids_json"),
            exit_decision_id=episode.exit_decision_id,
            exit_reason=MISSING,
            holding_seconds=episode.holding_time_seconds,
            gross_pnl=episode.gross_pnl,
            fees=episode.fees,
            funding=episode.funding_pnl,
            net_pnl=episode.net_pnl,
            known_at=(now or datetime.now(UTC)).isoformat(),
            reviewed_at=(now or datetime.now(UTC)).isoformat(),
        )
        terminal_reason = str(getattr(episode, "terminal_reason", None) or "").strip()
        if terminal_reason:
            evidence.exit_availability = EvidenceAvailability.AVAILABLE
            evidence.exit_reason = terminal_reason
        else:
            evidence.exit_availability = EvidenceAvailability.UNAVAILABLE
            evidence.exit_reason = MISSING
            if "EXIT" not in evidence.missing_evidence:
                evidence.missing_evidence.append("EXIT")
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
                    evidence.decision_conviction = MISSING
            else:
                evidence.missing_evidence.append("DECISION")
            risk_ids = _episode_ids(
                episode, "risk_decision_ids", "risk_decision_ids_json"
            )
            risks = (
                await session.execute(
                    select(RiskDecisionORM).where(
                        RiskDecisionORM.risk_decision_id.in_(tuple(risk_ids))
                    )
                )
            ).scalars().all() if risk_ids else []
            risk_by_id = {row.risk_decision_id: row for row in risks}
            duplicate = len(risk_by_id) != len(risks)
            complete = (
                bool(risk_ids)
                and not duplicate
                and len(risk_ids) == len(set(risk_ids))
                and all(risk_id in risk_by_id for risk_id in risk_ids)
            )
            if complete:
                ordered = [risk_by_id[risk_id] for risk_id in risk_ids]
                primary = ordered[0]
                evidence.risk_availability = EvidenceAvailability.AVAILABLE
                evidence.risk_decision_ids = list(risk_ids)
                evidence.risk_decision_id = risk_ids[0]
                evidence.risk_result = _value(primary, "decision")
                risk_reason = _value(primary, "reason")
                evidence.risk_reason_codes = [risk_reason] if risk_reason else []
            else:
                evidence.risk_decision_ids = []
                evidence.risk_decision_id = None
                evidence.missing_evidence.append("RISK")
            expected_order_ids = _episode_ids(
                episode, "order_ids", "order_ids_json"
            )
            expected_fill_ids = _episode_ids(
                episode, "fill_ids", "fill_ids_json"
            )
            order_rows = (
                await session.execute(
                    select(OrderORM).where(
                        OrderORM.internal_order_id.in_(tuple(expected_order_ids))
                    )
                )
            ).scalars().all() if expected_order_ids else []
            fill_rows = (
                await session.execute(
                    select(FillORM).where(
                        FillORM.fill_id.in_(tuple(expected_fill_ids))
                    )
                )
            ).scalars().all() if expected_fill_ids else []
            orders_by_id = {row.internal_order_id: row for row in order_rows}
            fills_by_id = {row.fill_id: row for row in fill_rows}
            duplicate = len(orders_by_id) != len(order_rows) or len(
                fills_by_id
            ) != len(fill_rows)
            complete = (
                bool(expected_order_ids)
                and bool(expected_fill_ids)
                and not duplicate
                and len(expected_order_ids) == len(set(expected_order_ids))
                and len(expected_fill_ids) == len(set(expected_fill_ids))
                and all(oid in orders_by_id for oid in expected_order_ids)
                and all(fid in fills_by_id for fid in expected_fill_ids)
            )
            evidence.order_ids = list(expected_order_ids)
            evidence.fill_ids = list(expected_fill_ids)
            if complete:
                evidence.execution_availability = EvidenceAvailability.AVAILABLE
                quantities = [
                    Decimal(str(_value(fills_by_id[fid], "quantity") or 0))
                    for fid in expected_fill_ids
                ]
                prices = [
                    Decimal(str(_value(fills_by_id[fid], "price") or 0))
                    for fid in expected_fill_ids
                ]
                total_qty = sum(quantities, Decimal("0"))
                if total_qty > 0:
                    evidence.weighted_entry_price = (
                        sum((p * q for p, q in zip(prices, quantities, strict=True)), Decimal("0"))
                        / total_qty
                    )
            else:
                evidence.execution_availability = EvidenceAvailability.UNAVAILABLE
                evidence.weighted_entry_price = MISSING
                if "ORDERS_FILLS" not in evidence.missing_evidence:
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
        evidence.validate_availability()
        return evidence


class CausalEvidenceUnavailable(ValueError):
    pass


_REF_AVAILABILITY = {
    "decision": "decision_availability",
    "factor": "factor_snapshot_availability",
    "factor_snapshot": "factor_snapshot_availability",
    "sizing": "sizing_availability",
    "risk": "risk_availability",
    "order": "execution_availability",
    "fill": "execution_availability",
    "position": "position_lifecycle_availability",
    "exit": "exit_availability",
    "mfe": "mfe_mae_availability",
    "mae": "mfe_mae_availability",
    "slippage": "slippage_availability",
    "fees": "fees_availability",
    "funding": "funding_availability",
}


def _availability_field_for_ref(evidence, ref):
    prefix, _, subtype = str(ref).partition(":")
    prefix = prefix.lower()
    if prefix == "episode":
        if str(ref) != f"episode:{evidence.episode_id}":
            raise CausalEvidenceUnavailable(f"UNKNOWN_EVIDENCE_REF:{ref}")
        return None
    if prefix == "accounting":
        if subtype == "fees":
            return "fees_availability"
        if subtype == "funding":
            return "funding_availability"
        raise CausalEvidenceUnavailable(f"UNKNOWN_EVIDENCE_REF:{ref}")
    field = _REF_AVAILABILITY.get(prefix)
    if field is None:
        raise CausalEvidenceUnavailable(f"UNKNOWN_EVIDENCE_REF:{ref}")
    return field


def validate_causal_evidence_refs(evidence, refs):
    if not refs:
        raise CausalEvidenceUnavailable("CAUSAL_CLAIM_REQUIRES_EVIDENCE_REFS")
    for ref in refs:
        field = _availability_field_for_ref(evidence, ref)
        if field is None:
            continue
        if getattr(evidence, field) != EvidenceAvailability.AVAILABLE:
            raise CausalEvidenceUnavailable(f"EVIDENCE_UNAVAILABLE:{ref}")
