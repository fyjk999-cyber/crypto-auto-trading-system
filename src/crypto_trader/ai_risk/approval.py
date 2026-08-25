"""Approval record (in-memory)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class ApprovalRecord:
    symbol: str
    decision: str
    max_leverage: str
    max_position: str
    reason: str
    created_at: str = ""


def record_approval(symbol: str, decision) -> ApprovalRecord:
    return ApprovalRecord(
        symbol=symbol,
        decision=decision.decision,
        max_leverage=str(decision.max_leverage),
        max_position=str(decision.max_position),
        reason=decision.reason,
        created_at=datetime.now(UTC).isoformat(),
    )
