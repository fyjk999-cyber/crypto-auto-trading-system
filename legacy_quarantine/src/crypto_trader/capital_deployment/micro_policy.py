"""Micro-capital deployment framework. NEVER enables live automatically."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class CapitalStage:
    name: str
    max_deployment_pct: Decimal
    active: bool = False


class MicroCapitalDeploymentPolicy:
    STAGES = [
        CapitalStage("STAGE_0_PAPER_SHADOW_ONLY", Decimal("0"), True),
        CapitalStage("STAGE_1_MICRO_CAPITAL", Decimal("0.01"), False),
        CapitalStage("STAGE_2_SMALL_CAPITAL", Decimal("0.02"), False),
        CapitalStage("STAGE_3_LIMITED_SCALE", Decimal("0.05"), False),
    ]

    def __init__(self) -> None:
        self.approvals: list[dict] = []
        self.current_stage = self.STAGES[0]

    def request_scale_up(
        self,
        stage_name: str,
        approver: str,
        reason: str,
        min_days: float,
        shadow_days: float,
        risk_violations: int,
        drawdown_pct: Decimal,
        unresolved_incidents: int,
    ) -> dict:
        stage = next((s for s in self.STAGES if s.name == stage_name), None)
        if stage is None:
            return {"approved": False, "reason": "UNKNOWN_STAGE"}
        if shadow_days < min_days:
            return {"approved": False, "reason": "DURATION_NOT_MET"}
        if risk_violations > 0:
            return {"approved": False, "reason": "RISK_VIOLATIONS"}
        if drawdown_pct >= Decimal("20"):
            return {"approved": False, "reason": "DRAWDOWN_BREACH"}
        if unresolved_incidents > 0:
            return {"approved": False, "reason": "UNRESOLVED_INCIDENTS"}
        stage.active = True
        self.current_stage = stage
        self.approvals.append(
            {"stage": stage_name, "approver": approver, "reason": reason, "approved": True}
        )
        return {"approved": True, "reason": "APPROVED"}

    def scale_down(self, reason: str) -> dict:
        self.current_stage = self.STAGES[0]
        self.approvals.append(
            {
                "stage": self.current_stage.name,
                "reason": reason,
                "approved": False,
                "scale_down": True,
            }
        )
        return {"approved": True, "reason": "SCALED_DOWN"}
