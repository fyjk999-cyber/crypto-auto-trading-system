from datetime import UTC, datetime

from crypto_trader.evolution.hierarchical.engine import HierarchicalLearningEngine
from crypto_trader.evolution.hierarchical.runner import due_periods
from crypto_trader.evolution.time.review_period import (
    previous_monthly,
    previous_weekly,
    previous_yearly,
)


def _utc(y, m, d, hh=0, mm=5):
    return datetime(y, m, d, hh, mm, 0, tzinfo=UTC)


def test_monday_00_05_selects_previous_iso_week():
    period = previous_weekly(_utc(2026, 8, 31))
    assert period.period_id.endswith("W35")


def test_month_first_selects_previous_month():
    period = previous_monthly(_utc(2026, 9, 1))
    assert period.period_id == "2026-08"


def test_jan1_selects_previous_year():
    period = previous_yearly(_utc(2026, 1, 1))
    assert period.period_id == "2025"


def test_weekly_confirmation_requires_multiple_days():
    engine = HierarchicalLearningEngine()
    lesson = {"canonical_statement": "X", "evidence_count": 2}
    daily = [
        {
            "review_id": "d1",
            "period_id": "2026-08-24",
            "candidate_lessons": [lesson],
            "patterns": [],
        },
        {
            "review_id": "d2",
            "period_id": "2026-08-25",
            "candidate_lessons": [{"canonical_statement": "X", "evidence_count": 2}],
            "patterns": [],
        },
    ]
    result = engine.weekly_review(
        review_id="w1", period_id="2026-W35", starts_at="", ends_at="", daily_reviews=daily
    )
    assert any(lesson["canonical_statement"] == "X" for lesson in result.confirmed_lessons)


def test_same_day_repetition_not_confirmed():
    engine = HierarchicalLearningEngine()
    daily = [
        {
            "review_id": "d1",
            "period_id": "2026-08-24",
            "candidate_lessons": [
                {"canonical_statement": "X", "evidence_count": 2},
                {"canonical_statement": "X", "evidence_count": 2},
            ],
            "patterns": [],
        },
    ]
    result = engine.weekly_review(
        review_id="w1", period_id="2026-W35", starts_at="", ends_at="", daily_reviews=daily
    )
    assert result.confirmed_lessons == []
    assert any(lesson["canonical_statement"] == "X" for lesson in result.candidate_lessons)


def test_monthly_aggregates_weekly():
    engine = HierarchicalLearningEngine()
    weekly = [
        {
            "review_id": "w1",
            "strategy_quality_summary": {"trend": "OK"},
            "factor_quality_summary": {"momentum": "OK"},
        },
        {
            "review_id": "w2",
            "strategy_quality_summary": {"trend": "OK"},
            "factor_quality_summary": {},
        },
    ]
    result = engine.monthly_review(
        review_id="m1", period_id="2026-08", starts_at="", ends_at="", weekly_reviews=weekly
    )
    assert len(result.strategy_evaluations) == 2
    assert len(result.factor_evaluations) == 1


def test_yearly_aggregates_monthly():
    engine = HierarchicalLearningEngine()
    monthly = [
        {
            "review_id": "m1",
            "period_id": "2026-01",
            "strategy_evaluations": [{"a": 1}],
            "factor_evaluations": [{"b": 2}],
        }
    ]
    result = engine.yearly_review(
        review_id="y1", period_id="2026", starts_at="", ends_at="", monthly_reviews=monthly
    )
    assert result.complexity_growth[0]["strategies"] == 1
    assert result.complexity_growth[0]["factors"] == 1


def test_due_periods_order():
    due = due_periods(_utc(2026, 8, 26))
    # Aug 26 00:05 is not Monday/month/year; only daily is the natural trigger.
    # Runner returns period IDs in canonical order for any boundary.
    assert due == [
        ("DAILY", "2026-08-25"),
        ("WEEKLY", "2026-W34"),
        ("MONTHLY", "2026-07"),
        ("YEARLY", "2025"),
    ]
