from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.money import D

HARD_MAX_LEVERAGE = D("6")


@dataclass
class LeverageDecision:
    recommended: Decimal
    risk_capped: Decimal
    review_approved: Decimal
    effective: Decimal
    stages: list[dict] = field(default_factory=list)
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))


class LeverageControlChain:
    def __init__(self, hard_max: Decimal = HARD_MAX_LEVERAGE) -> None:
        self.hard_max = hard_max

    def apply(
        self,
        recommended: Decimal,
        *,
        risk_cap: Decimal | None = None,
        review_approved: Decimal | None = None,
    ) -> LeverageDecision:
        rec = D(recommended)
        if rec <= 0:
            rec = D("1")
        capped = min(rec, self.hard_max)
        stage1 = {
            "stage": "recommended_leverage",
            "value": str(rec),
            "reason": "alpha_advisory",
            "authority": "alpha",
            "policy_version": "v1",
        }
        if risk_cap is not None:
            capped = min(capped, D(risk_cap))
        stage2 = {
            "stage": "risk_capped_leverage",
            "value": str(capped),
            "reason": "risk_limits",
            "authority": "risk",
            "policy_version": "v1",
        }
        approved = capped
        if review_approved is not None:
            approved = min(capped, D(review_approved))
        stage3 = {
            "stage": "review_approved_leverage",
            "value": str(approved),
            "reason": "trade_review",
            "authority": "review",
            "policy_version": "v1",
        }
        effective = min(approved, self.hard_max)
        stage4 = {
            "stage": "effective_leverage",
            "value": str(effective),
            "reason": "hard_max",
            "authority": "execution",
            "policy_version": "v1",
        }
        return LeverageDecision(rec, capped, approved, effective, [stage1, stage2, stage3, stage4])
