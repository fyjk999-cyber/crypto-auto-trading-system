"""Canonical causal evidence envelope for structured Growth review."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

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
            available = (
                getattr(self, availability_field)
                == EvidenceAvailability.AVAILABLE
            )
            if available and not getattr(self, reference_field, None):
                raise ValueError(
                    f"CONTRADICTORY_AVAILABILITY:{availability_field}"
                )
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
    "accounting": "fees_availability",
    "fees": "fees_availability",
    "funding": "funding_availability",
}


def validate_causal_evidence_refs(evidence, refs):
    if not refs:
        raise CausalEvidenceUnavailable("CAUSAL_CLAIM_REQUIRES_EVIDENCE_REFS")
    for ref in refs:
        field = _REF_AVAILABILITY.get(str(ref).split(":", 1)[0].lower())
        if field is None:
            raise CausalEvidenceUnavailable(f"UNKNOWN_EVIDENCE_REF:{ref}")
        if getattr(evidence, field) != EvidenceAvailability.AVAILABLE:
            raise CausalEvidenceUnavailable(f"EVIDENCE_UNAVAILABLE:{ref}")
