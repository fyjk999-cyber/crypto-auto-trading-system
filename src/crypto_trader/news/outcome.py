"""Factual News outcome review at fixed post-event horizons.

Reviews do not claim causality. Counterfactuals must be explicitly labeled
NON_FACTUAL and never rewrite the original NewsEvidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from crypto_trader.domain.identifiers import new_id
from crypto_trader.news.models import NewsEvidence, NewsOutcomeReview
from crypto_trader.news.repository import NewsRepository

OUTCOME_HORIZONS: dict[str, timedelta] = {
    "+5m": timedelta(minutes=5),
    "+15m": timedelta(minutes=15),
    "+30m": timedelta(minutes=30),
    "+1h": timedelta(hours=1),
    "+4h": timedelta(hours=4),
    "+12h": timedelta(hours=12),
    "+24h": timedelta(hours=24),
}


@dataclass(slots=True)
class MarketObservation:
    price_return: float | None = None
    mfe: float | None = None
    mae: float | None = None
    realized_volatility: float | None = None
    rvol: float | None = None
    spread_change: float | None = None
    oi_change: float | None = None
    funding_change: float | None = None
    payload: dict = field(default_factory=dict)


class NewsOutcomeReviewService:
    def __init__(self, session_factory, *, repository: NewsRepository | None = None) -> None:
        self.repository = repository or NewsRepository(session_factory)

    async def schedule_for_evidence(
        self,
        evidence: NewsEvidence,
        *,
        now: datetime,
        evidence_id: str | None = None,
    ) -> list[str]:
        review_ids: list[str] = []
        for horizon, delta in OUTCOME_HORIZONS.items():
            review = NewsOutcomeReview(
                review_id=new_id("newsout"),
                news_evidence_id=evidence_id or evidence.news_evidence_id,
                event_id=evidence.event_id,
                event_version=evidence.event_version,
                symbol=evidence.symbol,
                horizon=horizon,
                due_at=now + delta,
                status="PENDING",
            )
            await self.repository.insert_outcome_review(review)
            review_ids.append(review.review_id)
        return review_ids

    async def process_due(
        self,
        observation_provider,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> dict:
        moment = now or datetime.now(UTC)
        due = await self.repository.due_outcome_reviews(now=moment, limit=limit)
        processed = 0
        unavailable = 0
        for review in due:
            try:
                observation = await observation_provider.observe(
                    symbol=review["symbol"],
                    horizon=review["horizon"],
                    due_at=review["due_at"],
                    news_evidence_id=review["news_evidence_id"],
                )
            except Exception:
                observation = None
            if observation is None:
                unavailable += 1
                continue
            await self.repository.update_outcome_review(
                review["review_id"],
                status="COMPLETED",
                payload={
                    "price_return": observation.price_return,
                    "mfe": observation.mfe,
                    "mae": observation.mae,
                    "realized_volatility": observation.realized_volatility,
                    "rvol": observation.rvol,
                    "spread_change": observation.spread_change,
                    "oi_change": observation.oi_change,
                    "funding_change": observation.funding_change,
                    "counterfactual_label": "NON_FACTUAL"
                    if observation.payload.get("counterfactual")
                    else None,
                    "causal_claim": False,
                    **observation.payload,
                },
            )
            processed += 1
        return {"due": len(due), "processed": processed, "unavailable": unavailable}
