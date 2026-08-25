"""Walk-forward validation engine."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class WalkForwardReport:
    period: str
    performance: Decimal
    drawdown: Decimal
    strategy_used: str
    failure_cases: list[str]
    generalization_score: Decimal


class WalkForwardEngine:
    def run(
        self,
        *,
        period: str,
        performance: Decimal,
        drawdown: Decimal,
        strategy_used: str,
        failure_cases: list[str],
    ) -> WalkForwardReport:
        score = max(D("0"), min(D("1"), performance / D("100") - drawdown / D("100")))
        return WalkForwardReport(
            period=period,
            performance=performance,
            drawdown=drawdown,
            strategy_used=strategy_used,
            failure_cases=failure_cases,
            generalization_score=score,
        )
