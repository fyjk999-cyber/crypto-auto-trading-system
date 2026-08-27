from datetime import UTC, datetime

from crypto_trader.evolution.persistence_backends import (
    HierarchicalReviewJobStore,
    HierarchicalReviewStore,
)


def make_weekly(review_id="w1", period_id="2026-W35"):
    return {
        "review_id": review_id,
        "period_id": period_id,
        "starts_at": "2026-08-24T00:00:00+00:00",
        "ends_at": "2026-08-30T23:59:59.999999+00:00",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": "COMPLETED",
        "daily_review_ids": ["d1", "d2"],
        "confirmed_lessons": [{"lesson_id": "L1"}],
        "invalidated_lessons": [],
        "candidate_lessons": [],
        "persistent_patterns": [{"pattern_id": "P1"}],
        "research_questions": [],
        "data_quality": "OK",
        "warnings": [],
    }


def make_monthly(review_id="m1", period_id="2026-08"):
    return {
        "review_id": review_id,
        "period_id": period_id,
        "starts_at": "2026-08-01T00:00:00+00:00",
        "ends_at": "2026-08-31T23:59:59.999999+00:00",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": "COMPLETED",
        "weekly_review_ids": ["w1"],
        "confirmed_lessons": [],
        "invalidated_lessons": [],
        "candidate_lessons": [],
        "strategy_evaluations": [],
        "factor_evaluations": [],
        "strategy_proposals": [],
        "factor_proposals": [],
        "data_quality": "OK",
        "warnings": [],
    }


def make_yearly(review_id="y1", period_id="2026"):
    return {
        "review_id": review_id,
        "period_id": period_id,
        "starts_at": "2026-01-01T00:00:00+00:00",
        "ends_at": "2026-12-31T23:59:59.999999+00:00",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": "COMPLETED",
        "monthly_review_ids": ["m1"],
        "confirmed_lessons": [],
        "invalidated_lessons": [],
        "candidate_lessons": [],
        "architecture_proposals": [],
        "research_policy_proposals": [],
        "complexity_reduction_proposals": [],
        "data_quality": "OK",
        "warnings": [],
    }


async def test_weekly_monthly_yearly_persist_and_reload(database):
    store = HierarchicalReviewStore(database.session_factory)
    await store.store_review("WEEKLY", make_weekly())
    await store.store_review("MONTHLY", make_monthly())
    await store.store_review("YEARLY", make_yearly())
    assert (await store.get_review("WEEKLY", "w1"))["period_id"] == "2026-W35"
    assert (await store.get_review("MONTHLY", "m1"))["period_id"] == "2026-08"
    assert (await store.get_review("YEARLY", "y1"))["period_id"] == "2026"
    # duplicate writes are idempotent
    await store.store_review("WEEKLY", make_weekly())
    rows = await store.list_period("WEEKLY", "2026-W35")
    assert len(rows) == 1


async def test_hierarchical_review_job_idempotency(database):
    jobs = HierarchicalReviewJobStore(database.session_factory)
    key = "review:weekly:2026-W35"
    await jobs.put(key, "w1", "WEEKLY", "2026-W35", "RUNNING")
    await jobs.put(key, "w1", "WEEKLY", "2026-W35", "DONE")
    loaded = await jobs.get(key)
    assert loaded["status"] == "DONE"
    assert loaded["attempt"] == 1


async def test_hierarchy_lineage_trace(database):
    store = HierarchicalReviewStore(database.session_factory)
    await store.store_review("WEEKLY", make_weekly())
    await store.store_review("MONTHLY", make_monthly())
    await store.store_review("YEARLY", make_yearly())
    yearly = await store.get_review("YEARLY", "y1")
    monthly = await store.get_review("MONTHLY", "m1")
    weekly = await store.get_review("WEEKLY", "w1")
    assert "m1" in yearly.get("monthly_review_ids", [])
    assert "w1" in monthly.get("weekly_review_ids", [])
    assert "d1" in weekly.get("daily_review_ids", [])
