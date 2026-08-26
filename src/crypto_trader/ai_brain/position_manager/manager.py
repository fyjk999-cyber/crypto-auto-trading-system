"""Canonical PositionManager: thesis-aware, evidence-driven."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class PositionContext:
    symbol: str
    position_side: str = ""  # LONG | SHORT
    position_quantity: float = 0.0
    entry_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    time_in_position_seconds: float = 0.0
    original_thesis: str = ""
    supporting_evidence: list[str] = field(default_factory=list)
    contradicting_evidence: list[str] = field(default_factory=list)
    invalid_conditions: list[str] = field(default_factory=list)
    factor_intelligence: dict = field(default_factory=dict)
    research_context: dict = field(default_factory=dict)
    memory_context: dict = field(default_factory=dict)
    risk_context: dict = field(default_factory=dict)
    thesis_status: str = "THESIS_INTACT"  # INTACT|STRENGTHENING|WEAKENING|INVALIDATED
    hard_risk_exit: bool = False


@dataclass
class PositionDecision:
    symbol: str
    action: str  # HOLD | ADD | REDUCE | EXIT
    confidence: float
    reason: str
    supporting_evidence: list[str] = field(default_factory=list)
    contradicting_evidence: list[str] = field(default_factory=list)
    thesis_status: str = "THESIS_INTACT"
    exit_reason: str = ""
    risk_notes: list[str] = field(default_factory=list)
    position_before: float = 0.0
    requested_change: float = 0.0
    reduction_fraction: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "confidence": self.confidence,
            "reason": self.reason,
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "thesis_status": self.thesis_status,
            "exit_reason": self.exit_reason,
            "risk_notes": self.risk_notes,
            "position_before": self.position_before,
            "requested_change": self.requested_change,
            "reduction_fraction": self.reduction_fraction,
            "timestamp": self.timestamp,
        }


class PositionManager:
    def decide(self, ctx: PositionContext) -> PositionDecision:
        if ctx.position_quantity <= 0:
            return PositionDecision(
                ctx.symbol, "NO_ACTION", 1.0, "no active position", position_before=0.0
            )
        if ctx.hard_risk_exit:
            return PositionDecision(
                ctx.symbol,
                "EXIT",
                1.0,
                "hard risk exit",
                exit_reason="EMERGENCY_RISK_EXIT",
                thesis_status=ctx.thesis_status,
                position_before=ctx.position_quantity,
                requested_change=ctx.position_quantity,
                risk_notes=["hard risk exit"],
            )
        if ctx.thesis_status == "THESIS_INVALIDATED":
            return PositionDecision(
                ctx.symbol,
                "EXIT",
                0.9,
                "thesis invalidated",
                exit_reason="THESIS_INVALIDATED",
                thesis_status=ctx.thesis_status,
                position_before=ctx.position_quantity,
                requested_change=ctx.position_quantity,
            )
        if ctx.thesis_status == "THESIS_WEAKENING":
            fraction = 0.3 if ctx.unrealized_pnl > 0 else 0.5
            return PositionDecision(
                ctx.symbol,
                "REDUCE",
                0.7,
                "thesis weakening",
                exit_reason="THESIS_WEAKENING",
                thesis_status=ctx.thesis_status,
                position_before=ctx.position_quantity,
                requested_change=round(ctx.position_quantity * fraction, 8),
                reduction_fraction=fraction,
                contradicting_evidence=ctx.contradicting_evidence,
            )
        if ctx.thesis_status == "THESIS_STRENGTHENING" and ctx.position_quantity > 0:
            return PositionDecision(
                ctx.symbol,
                "ADD",
                0.6,
                "thesis strengthening",
                thesis_status=ctx.thesis_status,
                position_before=ctx.position_quantity,
                requested_change=round(ctx.position_quantity * 0.25, 8),
            )
        if ctx.unrealized_pnl > 0 and ctx.time_in_position_seconds > 3600:
            return PositionDecision(
                ctx.symbol,
                "HOLD",
                0.65,
                "profit running; thesis intact",
                supporting_evidence=ctx.supporting_evidence,
                contradicting_evidence=ctx.contradicting_evidence,
                thesis_status=ctx.thesis_status,
                position_before=ctx.position_quantity,
            )
        return PositionDecision(
            ctx.symbol,
            "HOLD",
            0.6,
            "thesis intact",
            supporting_evidence=ctx.supporting_evidence,
            contradicting_evidence=ctx.contradicting_evidence,
            thesis_status=ctx.thesis_status,
            position_before=ctx.position_quantity,
        )
