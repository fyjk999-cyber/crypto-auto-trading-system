"""AI risk committee: deterministic second approval layer. Cannot bypass risk engine."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.ai_risk.policy import RiskPolicy


@dataclass
class CommitteeDecision:
    decision: str  # APPROVE | REDUCE | REJECT
    max_leverage: Decimal
    max_position: Decimal
    reason: str


class AIRiskCommittee:
    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or RiskPolicy()

    def review(
        self,
        *,
        leverage: Decimal,
        position_pct: Decimal,
        drawdown_pct: Decimal,
        asset_category: str,
        volatility_pct: Decimal,
        loss_streak: int,
    ) -> CommitteeDecision:
        if drawdown_pct >= self.policy.max_drawdown_pct:
            return CommitteeDecision("REJECT", Decimal("0"), Decimal("0"), "DRAWDOWN_LIMIT")
        if position_pct > self.policy.max_position_pct:
            return CommitteeDecision(
                "REDUCE",
                self.policy.max_leverage_default,
                self.policy.max_position_pct,
                "POSITION_TOO_LARGE",
            )
        if leverage > self.policy.max_leverage_default:
            return CommitteeDecision(
                "REDUCE", self.policy.max_leverage_default, position_pct, "LEVERAGE_TOO_HIGH"
            )
        if asset_category in ("MEME", "LOW_CAP") and position_pct > Decimal("5"):
            return CommitteeDecision("REDUCE", Decimal("2"), Decimal("5"), "SMALL_CAP_RISK")
        if volatility_pct > Decimal("8"):
            return CommitteeDecision("REDUCE", Decimal("2"), position_pct, "EXTREME_VOLATILITY")
        if loss_streak >= 3:
            return CommitteeDecision(
                "REDUCE", Decimal("2"), position_pct * Decimal("0.5"), "LOSS_STREAK"
            )
        return CommitteeDecision("APPROVE", leverage, position_pct, "OK")
