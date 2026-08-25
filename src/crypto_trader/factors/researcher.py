"""Factor research engine: ask research questions about factor effectiveness."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class ResearchQuestion:
    question_id: str
    hypothesis: str
    factor: str
    dataset: str
    timeframe: str
    status: str = "OPEN"


@dataclass
class ResearchResult:
    question_id: str
    hypothesis: str
    factor: str
    sample_size: int
    result: str
    confidence: Decimal
    conclusion: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class FactorResearcher:
    def research(
        self,
        question_id: str,
        hypothesis: str,
        factor: str,
        dataset: str,
        timeframe: str,
        observations: list[dict],
    ) -> ResearchResult:
        wins = sum(1 for o in observations if o.get("result") == "WIN")
        total = len(observations)
        win_rate = Decimal(wins) / Decimal(total) if total else D("0")
        confidence = min(D("0.9"), D("0.3") + Decimal(total) / D("100"))
        if total < 30:
            conclusion = "insufficient sample; collect more data"
        elif win_rate > Decimal("0.55"):
            conclusion = "factor shows predictive power"
        else:
            conclusion = "no stable predictive power observed"
        return ResearchResult(
            question_id,
            hypothesis,
            factor,
            total,
            "VALIDATED" if win_rate > Decimal("0.55") and total >= 30 else "INCONCLUSIVE",
            confidence,
            conclusion,
        )
