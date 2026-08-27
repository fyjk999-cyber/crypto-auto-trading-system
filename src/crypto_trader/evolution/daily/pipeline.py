"""Daily review pipeline orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field

from crypto_trader.evolution.daily.error_mining import ErrorEvent, mine_error
from crypto_trader.evolution.daily.lesson import LessonEngine
from crypto_trader.evolution.daily.models import (
    DailyReviewResult,
    build_attribution_evidence_based,
)
from crypto_trader.evolution.daily.pattern import extract_patterns
from crypto_trader.evolution.daily.replay import HistoricalReplayEngine


@dataclass
class DailyReviewPipeline:
    replay_engine: HistoricalReplayEngine = field(default_factory=HistoricalReplayEngine)
    lesson_engine: LessonEngine = field(default_factory=LessonEngine)
    completed_keys: set = field(default_factory=set)

    def run(
        self,
        *,
        review_id: str,
        period_id: str,
        starts_at: str,
        ends_at: str,
        decisions: list[dict],
        triggered_at: str = "",
    ) -> DailyReviewResult:
        key = f"review:daily:{period_id}"
        if key in self.completed_keys:
            return DailyReviewResult(
                review_id=review_id, period_id=period_id, status="ALREADY_COMPLETED"
            )
        errors: list[ErrorEvent] = []
        for decision in decisions:
            event = mine_error(
                decision_quality=decision.get("decision_quality", "GOOD"),
                outcome_quality=decision.get("outcome_quality", "GOOD"),
                rule_violation=decision.get("rule_violation", False),
                factor_conflict=decision.get("factor_conflict", False),
                market_shock=decision.get("market_shock", False),
            )
            if event is not None:
                event.decision_id = decision.get("decision_id", "")
                errors.append(event)
        factor_attributions = []
        for decision in decisions:
            attribution = build_attribution_evidence_based(
                attribution_id=f"attr_{decision.get('decision_id', '')}",
                review_id=review_id,
                evidence=decision.get("evidence", {}),
                decision_quality=decision.get("decision_quality", "GOOD"),
                outcome_quality=decision.get("outcome_quality", "GOOD"),
            )
            factor_attributions.append(
                attribution.to_dict() if hasattr(attribution, "to_dict") else attribution
            )
        patterns = extract_patterns(errors)
        lessons = []
        for pattern in patterns:
            lesson = self.lesson_engine.derive_from_pattern(pattern)
            if self.lesson_engine.deduplicate(lesson) is not None:
                lessons.append(lesson.to_dict())
        self.completed_keys.add(key)
        return DailyReviewResult(
            review_id=review_id,
            period_id=period_id,
            starts_at=starts_at,
            ends_at=ends_at,
            triggered_at=triggered_at,
            decision_count=len(decisions),
            trade_count=sum(1 for d in decisions if d.get("trade")),
            factor_attributions=factor_attributions,
            reviewed_decisions=list(decisions),
            error_clusters=[e.to_dict() for e in errors],
            patterns=[p.to_dict() for p in patterns],
            candidate_lessons=lessons,
        )
