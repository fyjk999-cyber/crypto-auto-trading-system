"""Hierarchical learning engine: weekly/monthly/yearly aggregation."""

from __future__ import annotations

from crypto_trader.evolution.hierarchical.contracts import (
    MonthlyReviewResult,
    WeeklyReviewResult,
    YearlyReviewResult,
)


class HierarchicalLearningEngine:
    def weekly_review(
        self,
        *,
        review_id: str,
        period_id: str,
        starts_at: str,
        ends_at: str,
        daily_reviews: list[dict],
    ) -> WeeklyReviewResult:
        lessons = []
        for daily in daily_reviews:
            for lesson in daily.get("candidate_lessons", []):
                lesson = dict(lesson)
                lesson["_day"] = daily.get("period_id", "")
                lessons.append(lesson)
        patterns = [p for daily in daily_reviews for p in daily.get("patterns", [])]
        by_statement: dict[str, dict] = {}
        for lesson in lessons:
            statement = lesson.get("canonical_statement", "")
            entry = by_statement.setdefault(
                statement, {"lesson": lesson, "days": set(), "evidence": 0}
            )
            entry["days"].add(lesson.get("_day", ""))
            entry["evidence"] += lesson.get("evidence_count", 0)
        confirmed = []
        candidate = []
        invalidated = []
        for _statement, entry in by_statement.items():
            lesson = entry["lesson"]
            # same-day repetition is NOT multi-day confirmation
            if len(entry["days"]) >= 2:
                lesson["status"] = "CONFIRMED"
                confirmed.append(lesson)
            elif entry["evidence"] <= 1:
                candidate.append(lesson)
            else:
                candidate.append(lesson)
        return WeeklyReviewResult(
            review_id=review_id,
            period_id=period_id,
            starts_at=starts_at,
            ends_at=ends_at,
            daily_review_ids=[d.get("review_id", "") for d in daily_reviews],
            trade_count=sum(d.get("trade_count", 0) for d in daily_reviews),
            decision_count=sum(d.get("decision_count", 0) for d in daily_reviews),
            confirmed_lessons=confirmed,
            candidate_lessons=candidate,
            invalidated_lessons=invalidated,
            persistent_patterns=[p for p in patterns if p.get("evidence_count", 0) >= 2],
        )

    def monthly_review(
        self,
        *,
        review_id: str,
        period_id: str,
        starts_at: str,
        ends_at: str,
        weekly_reviews: list[dict],
    ) -> MonthlyReviewResult:
        strategy_evaluations = []
        for weekly in weekly_reviews:
            summary = weekly.get("strategy_quality_summary", {})
            if summary:
                strategy_evaluations.append(summary)
        return MonthlyReviewResult(
            review_id=review_id,
            period_id=period_id,
            starts_at=starts_at,
            ends_at=ends_at,
            weekly_review_ids=[w.get("review_id", "") for w in weekly_reviews],
            strategy_evaluations=strategy_evaluations,
            factor_evaluations=[
                w.get("factor_quality_summary", {})
                for w in weekly_reviews
                if w.get("factor_quality_summary")
            ],
        )

    def yearly_review(
        self,
        *,
        review_id: str,
        period_id: str,
        starts_at: str,
        ends_at: str,
        monthly_reviews: list[dict],
    ) -> YearlyReviewResult:
        return YearlyReviewResult(
            review_id=review_id,
            period_id=period_id,
            starts_at=starts_at,
            ends_at=ends_at,
            monthly_review_ids=[m.get("review_id", "") for m in monthly_reviews],
            complexity_growth=[
                {
                    "month": m.get("period_id", ""),
                    "strategies": len(m.get("strategy_evaluations", [])),
                    "factors": len(m.get("factor_evaluations", [])),
                }
                for m in monthly_reviews
            ],
        )
