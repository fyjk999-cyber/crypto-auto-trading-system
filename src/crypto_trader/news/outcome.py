"""Factual News outcome review at fixed post-event horizons.

Reviews do not claim causality. Counterfactuals must be explicitly labeled
NON_FACTUAL and never rewrite the original NewsEvidence. A review is only
marked COMPLETED when a factual, horizon-aligned market observation exists;
transient source errors remain retryable and data gaps are recorded truthfully.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

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

RETRYABLE_OUTCOME_STATUSES = ("PENDING", "TRANSIENT_SOURCE_ERROR")
TERMINAL_OUTCOME_STATUSES = ("COMPLETED", "INCONCLUSIVE_DATA_GAP")


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


@dataclass(slots=True)
class NewsObservationResult:
    """Provider result carrying factual data plus alignment provenance."""

    status: str
    observation: MarketObservation | None = None
    source: str = "UNAVAILABLE"
    endpoint: str = ""
    target_at: datetime | None = None
    alignment_quality: str = "UNAVAILABLE"
    unavailable_reasons: list[str] = field(default_factory=list)
    observed_start_at: datetime | None = None
    observed_end_at: datetime | None = None
    bars_used: int = 0

    def with_status(self, status: str, reason: str | None = None) -> NewsObservationResult:
        reasons = list(self.unavailable_reasons)
        if reason:
            reasons.append(reason)
        return NewsObservationResult(
            status=status,
            observation=self.observation,
            source=self.source,
            endpoint=self.endpoint,
            target_at=self.target_at,
            alignment_quality=self.alignment_quality,
            unavailable_reasons=reasons,
            observed_start_at=self.observed_start_at,
            observed_end_at=self.observed_end_at,
            bars_used=self.bars_used,
        )


def _has_factual_observation(observation: MarketObservation | None) -> bool:
    if observation is None:
        return False
    return any(
        getattr(observation, name) is not None
        for name in (
            "price_return",
            "mfe",
            "mae",
            "realized_volatility",
            "rvol",
            "spread_change",
            "oi_change",
            "funding_change",
        )
    )


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

    @staticmethod
    def _coerce_result(raw: Any) -> NewsObservationResult:
        if isinstance(raw, NewsObservationResult):
            return raw
        if isinstance(raw, MarketObservation) or raw is None:
            if _has_factual_observation(raw):
                return NewsObservationResult(status="COMPLETED", observation=raw)
            return NewsObservationResult(
                status="TRANSIENT_SOURCE_ERROR" if raw is None else "INCONCLUSIVE_DATA_GAP",
                observation=raw,
                unavailable_reasons=["NO_OBSERVATION" if raw is None else "NO_FACTUAL_FIELDS"],
            )
        return NewsObservationResult(
            status="TRANSIENT_SOURCE_ERROR",
            unavailable_reasons=[f"UNSUPPORTED_OBSERVATION_RESULT:{type(raw).__name__}"],
        )

    async def process_due(
        self,
        observation_provider,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> dict:
        moment = now or datetime.now(UTC)
        due = await self.repository.due_outcome_reviews(now=moment, limit=limit)
        metrics = {
            "due": len(due),
            "processed": 0,
            "transient": 0,
            "inconclusive": 0,
            "unavailable": 0,
            "skipped": 0,
        }
        for review in due:
            try:
                raw = await observation_provider.observe(
                    symbol=review["symbol"],
                    horizon=review["horizon"],
                    due_at=review["due_at"],
                    news_evidence_id=review["news_evidence_id"],
                )
            except Exception as exc:
                raw = NewsObservationResult(
                    status="TRANSIENT_SOURCE_ERROR",
                    unavailable_reasons=[f"{type(exc).__name__}: {exc}"[:300]],
                )
            result = self._coerce_result(raw)
            observation = result.observation
            status = result.status
            if status == "COMPLETED" and not _has_factual_observation(observation):
                status = "INCONCLUSIVE_DATA_GAP"
                result = result.with_status(status, "NO_FACTUAL_FIELDS")
            if status not in TERMINAL_OUTCOME_STATUSES + ("TRANSIENT_SOURCE_ERROR",):
                status = "TRANSIENT_SOURCE_ERROR"
                result = result.with_status(status, "INVALID_PROVIDER_STATUS")

            payload: dict[str, Any] = {
                "requested_horizon": review["horizon"],
                "target_at": result.target_at.isoformat() if result.target_at else None,
                "observed_start_at": (
                    result.observed_start_at.isoformat() if result.observed_start_at else None
                ),
                "observed_end_at": (
                    result.observed_end_at.isoformat() if result.observed_end_at else None
                ),
                "source": result.source,
                "observation_endpoint": result.endpoint,
                "alignment_quality": result.alignment_quality,
                "bars_used": result.bars_used,
                "unavailable_reasons": list(result.unavailable_reasons),
                "causal_claim": False,
                "counterfactual_label": "NON_FACTUAL"
                if (observation and observation.payload.get("counterfactual"))
                else None,
            }
            if observation is not None:
                payload.update(
                    {
                        "price_return": observation.price_return,
                        "mfe": observation.mfe,
                        "mae": observation.mae,
                        "realized_volatility": observation.realized_volatility,
                        "rvol": observation.rvol,
                        "spread_change": observation.spread_change,
                        "oi_change": observation.oi_change,
                        "funding_change": observation.funding_change,
                        **observation.payload,
                    }
                )

            updated = await self.repository.update_outcome_review(
                review["review_id"], status=status, payload=payload
            )
            if not updated:
                metrics["skipped"] += 1
                continue
            if status == "COMPLETED":
                metrics["processed"] += 1
            elif status == "TRANSIENT_SOURCE_ERROR":
                metrics["transient"] += 1
                metrics["unavailable"] += 1
            elif status == "INCONCLUSIVE_DATA_GAP":
                metrics["inconclusive"] += 1
                metrics["unavailable"] += 1
        return metrics
