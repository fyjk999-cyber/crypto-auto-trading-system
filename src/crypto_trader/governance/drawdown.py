from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class DrawdownDecision:
    drawdown_pct: Decimal
    risk_multiplier: Decimal
    kill_switch: bool
    allow_new_risk: bool
    allow_reduce: bool = True
    allow_close: bool = True
    reason: str = ""


class DrawdownPolicy:
    def __init__(self) -> None:
        self.bands = [
            (D("0.10"), D("1.00"), False),
            (D("0.20"), D("0.80"), False),
            (D("0.30"), D("0.50"), False),
            (D("0.40"), D("0.25"), False),
            (D("0.45"), D("0.10"), False),
            (D("0.50"), D("0.00"), True),
        ]

    def evaluate(self, drawdown_pct: Decimal) -> DrawdownDecision:
        dd = abs(D(drawdown_pct))
        multiplier = D("0")
        kill = False
        for threshold, mult, kill_flag in self.bands:
            if dd >= threshold:
                multiplier = mult
                kill = kill_flag
        if dd < D("0.10"):
            multiplier = D("1.00")
        allow_new_risk = not kill
        reason = "KILL_SWITCH_50PCT_DD" if kill else f"DD_BAND_{dd:.0%}".replace("%", "PCT")
        return DrawdownDecision(
            drawdown_pct=dd,
            risk_multiplier=multiplier,
            kill_switch=kill,
            allow_new_risk=allow_new_risk,
            reason=reason,
        )

    def allow_action(self, decision: DrawdownDecision, action: str) -> bool:
        if decision.kill_switch:
            return action in ("REDUCE", "CLOSE")
        return True
