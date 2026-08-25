"""Manual approval required for any future live capital."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApprovalState:
    approved: bool = False
    approver: str = ""
    reason: str = ""


class CapitalApproval:
    def __init__(self) -> None:
        self.state = ApprovalState()

    def approve(self, approver: str, reason: str) -> None:
        self.state = ApprovalState(True, approver, reason)

    def required(self) -> bool:
        return not self.state.approved
