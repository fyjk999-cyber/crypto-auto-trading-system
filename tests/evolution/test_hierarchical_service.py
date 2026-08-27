"""Weekly/Monthly/Yearly aggregation service + engine tests.

Covers: period selection, duplicate/missing child handling, lesson lifecycle,
deterministic aggregation, proposal-only outputs, idempotency, restart safety,
failure retry semantics, timezone independence, and no-production-mutation.
"""

import os
import time
from datetime import UTC, datetime

import pytest

from crypto_trader.evolution.hierarchical.contracts import MonthlyReviewResult
from crypto_trader.evolution.hierarchical.engine import (
    RECOMMENDATION_ACTIONS,
    HierarchicalLearningEngine,
    _expected_period_ids,
)
from crypto_trader.evolution.hierarchical.service import HierarchicalReviewService
from crypto_trader.evolution.persistence_backends import (
    HierarchicalReviewJobStore,
    HierarchicalReviewStore,
    SqlEvidenceBackend,
)
from crypto_trader.evolution.time.review_period import previous_monthly, previous_weekly
from crypto_trader.factors.version import FactorSetVersion


def _utc(y, m, d, hh=0, mm=5):
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


# Monday 00:05 UTC after the completed ISO week 2026-W36 (Mon 08-31 .. Sun 09-06).
WEEK_NOW = _utc(2026, 9, 7)
WEEK36_DAYS = (
    "2026-08-31",
    "2026-09-01",
    "2026-09-02",
    "2026-09-03",
    "2026-09-04",
    "2026-09-05",
    "2026-09-06",
)


def make_service(database) -> tuple[HierarchicalReviewService, dict]:
    stores = {
        "evidence": SqlEvidenceBackend(database.session_factory),
        "reviews": HierarchicalReviewStore(database.session_factory),
        "jobs": HierarchicalReviewJobStore(database.session_factory),
    }
    service = HierarchicalReviewService(
        evidence_backend=stores["evidence"],
        review_store=stores["reviews"],
        job_store=stores["jobs"],
    )
    return service, stores


def make_daily(day, *, review_id=None, net_pnl="10", lessons=(), attributions=(),
               error_clusters=(), patterns=(), strategy_quality=None,
               factor_quality=None, regime_summary=None):
    rid = review_id if review_id is not None else f"daily-{day}"
    return {
        "review_id": rid,
        "review_type": "DAILY",
        "period_id": day,
        "starts_at": f"{day}T00:00:00+00:00",
        "ends_at": f"{day}T23:59:59.999999+00:00",
        "created_at_utc": _utc(2026, 9, 7).isoformat(),
        "status": "COMPLETED",
        "trade_count": 2,
        "decision_count": 3,
        "net_pnl": net_pnl,
        "candidate_lessons": list(lessons),
        "patterns": list(patterns),
        "factor_attributions": list(attributions),
        "error_clusters": list(error_clusters),
        "regime_summary": regime_summary or {},
        "strategy_quality": strategy_quality or {},
        "factor_quality": factor_quality or {},
        "data_quality": "OK",
        "warnings": [],
    }


def make_weekly_payload(period_id, *, pnl="-100", drawdown="-50", lessons_confirmed=(),
                        lessons_invalidated=(), strategy_quality=None, factor_quality=None,
                        failures=None, conflicts=None):
    return {
        "review_id": f"review-weekly-{period_id}",
        "period_id": period_id,
        "starts_at": "2026-08-01T00:00:00+00:00",
        "ends_at": "2026-09-06T23:59:59.999999+00:00",
        "created_at_utc": _utc(2026, 9, 7).isoformat(),
        "status": "COMPLETED",
        "weekly_pnl": pnl,
        "weekly_drawdown": drawdown,
        "confirmed_lessons": list(lessons_confirmed),
        "invalidated_lessons": list(lessons_invalidated),
        "candidate_lessons": [],
        "persistent_patterns": [],
        "research_questions": [],
        "strategy_quality_summary": strategy_quality or {},
        "factor_quality_summary": factor_quality or {},
        "factor_quality": factor_quality or {},
        "factor_issue_recurrence": failures or {},
        "factor_conflict_recurrence": conflicts or {},
        "confidence_calibration": {},
        "data_quality": "OK",
        "warnings": [],
    }


def active_factor_set_state():
    version = FactorSetVersion.active_default()
    return version.factor_set_version, version.status, version.included_factors


# --------------------------------------------------------------------- weekly


async def test_weekly_previous_iso_week_and_monday_boundary(database):
    """Any moment inside the new week reviews exactly the previous ISO week."""
    service, _ = make_service(database)
    for day in WEEK36_DAYS:
        await service.evidence_backend.store_review(make_daily(day))
    for now in (WEEK_NOW, _utc(2026, 9, 8), _utc(2026, 9, 13, 23)):  # Mon..Sun
        payload = await service.run_weekly(now)
        assert payload["period_id"] == "2026-W36"
        assert payload["review_id"] == "review-weekly-2026-W36"
        assert payload["starts_at"].startswith("2026-08-31")
        assert payload["ends_at"].startswith("2026-09-06")
    assert payload["daily_report_count"] == 7


async def test_weekly_missing_daily_reports_warning(database):
    """Stored 3 of 7 days -> warning enumerates the missing UTC dates in order."""
    service, _ = make_service(database)
    for day in WEEK36_DAYS[:3]:
        await service.evidence_backend.store_review(make_daily(day))
    payload = await service.run_weekly(WEEK_NOW)
    missing = [w for w in payload["warnings"] if w.startswith("MISSING_DAILY_REPORTS:")]
    assert missing == ["MISSING_DAILY_REPORTS:" + ",".join(WEEK36_DAYS[3:])]
    assert payload["daily_report_count"] == 3
    assert payload["weekly_pnl"] == "30"


async def test_weekly_duplicate_daily_reports_deduplicated(database):
    """Two reports for the same day count once (first review_id wins)."""
    service, _ = make_service(database)
    dup_a = make_daily(WEEK36_DAYS[1], review_id="dup-a", net_pnl="5")
    dup_b = make_daily(WEEK36_DAYS[1], review_id="dup-b", net_pnl="5")
    await service.evidence_backend.store_review(dup_b)
    await service.evidence_backend.store_review(dup_a)
    for day in (WEEK36_DAYS[0], *WEEK36_DAYS[2:]):
        await service.evidence_backend.store_review(make_daily(day))
    payload = await service.run_weekly(WEEK_NOW)
    assert payload["daily_report_count"] == 7
    assert "dup-a" in payload["daily_review_ids"]
    assert "dup-b" not in payload["daily_review_ids"]


async def test_weekly_lesson_recurrence_and_lifecycle(database):
    """Multi-day support confirms; single-day repeats stay candidate;
    contradiction-dominated lessons are rejected; recurrence counts days."""
    service, _ = make_service(database)
    day_a, day_b, day_c, day_d = WEEK36_DAYS[0], WEEK36_DAYS[1], WEEK36_DAYS[2], WEEK36_DAYS[3]
    confirmed_lesson = {
        "lesson_id": "L-confirm", "canonical_statement": "avoid chase entries",
        "evidence_count": 2, "contradictions": 0, "supporting_decisions": 4,
    }
    candidate_once = {
        "lesson_id": "L-cand", "canonical_statement": "size down in chop",
        "evidence_count": 1, "contradictions": 0, "supporting_decisions": 2,
    }
    reject_inst = {
        "lesson_id": "L-reject", "canonical_statement": "short into funding print",
        "evidence_count": 1, "contradictions": 2, "supporting_decisions": 0,
    }
    dailies = [
        make_daily(day_a, lessons=[dict(confirmed_lesson)]),
        # two contradicting instances on one day + one next day: instances(3) > days(2)
        make_daily(day_b, lessons=[
            dict(candidate_once), dict(candidate_once),
            dict(reject_inst), dict(reject_inst),
        ]),
        make_daily(day_c, lessons=[dict(confirmed_lesson), dict(reject_inst)]),
    ]
    # also store the remaining three empty days so no MISSING warnings interfere
    stored_days = {day_a, day_b, day_c, day_d}
    for day in WEEK36_DAYS:
        if day not in stored_days:
            await service.evidence_backend.store_review(make_daily(day))
    for daily in dailies:
        await service.evidence_backend.store_review(daily)

    payload = await service.run_weekly(WEEK_NOW)
    rec = payload["lesson_recurrence"]
    assert rec["avoid chase entries"]["days"] == 2       # distinct-day counting
    assert rec["size down in chop"]["days"] == 1          # same-day repeat ignored

    confirmed_stmts = [item["canonical_statement"] for item in payload["confirmed_lessons"]]
    rejected_stmts = [item["canonical_statement"] for item in payload["invalidated_lessons"]]
    assert confirmed_stmts == ["avoid chase entries"]
    assert rejected_stmts == ["short into funding print"]  # 3 contradicting > 2 presence days
    assert any(
        item["canonical_statement"] == "size down in chop"
        and item["status"] == "CANDIDATE"
        for item in payload["candidate_lessons"]
    )
    confirmed = payload["confirmed_lessons"][0]
    assert confirmed["status"] == "CONFIRMED"


async def test_weekly_service_idempotent_restart_safe_and_job_attempt(database):
    service, stores = make_service(database)
    for day in WEEK36_DAYS:
        await service.evidence_backend.store_review(make_daily(day))

    first = await service.run_weekly(WEEK_NOW)
    again = await service.run_weekly(WEEK_NOW)
    assert again == first
    rows = await stores["reviews"].list_period("WEEKLY", "2026-W36")
    assert len(rows) == 1
    job = await stores["jobs"].get("review:weekly:2026-W36")
    assert job["status"] == "COMPLETED"
    assert job["attempt"] == 0            # cache-hit rerun does not rewrite the job

    # restart safety: brand-new service over the same database finds the report
    restarted, stores2 = make_service(database)
    payload = await restarted.run_weekly(_utc(2026, 9, 10))
    assert payload["review_id"] == "review-weekly-2026-W36"
    assert await stores2["reviews"].list_period("WEEKLY", "2026-W36") == rows
    assert len(await stores2["reviews"].list_period("WEEKLY", "2026-W36")) == 1


async def test_weekly_failure_marks_job_failed_then_retry_succeeds(database):
    service, stores = make_service(database)
    for day in WEEK36_DAYS:
        await service.evidence_backend.store_review(make_daily(day))

    class BoomEngine(HierarchicalLearningEngine):
        def weekly_review(self, **kwargs):
            raise RuntimeError("boom")

    broken = HierarchicalReviewService(
        evidence_backend=service.evidence_backend,
        review_store=stores["reviews"],
        job_store=stores["jobs"],
        engine=BoomEngine(),
    )
    with pytest.raises(RuntimeError, match="boom"):
        await broken.run_weekly(WEEK_NOW)
    failed = await stores["jobs"].get("review:weekly:2026-W36")
    assert failed["status"] == "FAILED"
    assert "boom" in failed["error"]

    recovered = await service.run_weekly(WEEK_NOW)   # FAILED jobs are retryable
    assert recovered["period_id"] == "2026-W36"
    final = await stores["jobs"].get("review:weekly:2026-W36")
    assert final["status"] == "COMPLETED"
    assert final["attempt"] == 1


async def test_weekly_run_does_not_mutate_production_factor_state(database):
    before_version, _, before_weights = active_factor_set_state()
    service, _ = make_service(database)
    for day in WEEK36_DAYS:
        await service.evidence_backend.store_review(make_daily(day))
    weekly = await service.run_weekly(WEEK_NOW)

    assert FactorSetVersion.active_default().status == "ACTIVE"
    assert active_factor_set_state() == (
        before_version, "ACTIVE", before_weights,
    )
    mutation_keys = {"factor_weights", "activate", "promotion", "active_version"}
    assert not mutation_keys & set(weekly)


# -------------------------------------------------------------------- monthly


async def test_monthly_period_boundary_february_and_leap_year():
    august = previous_monthly(_utc(2026, 9, 1))
    assert august.period_id == "2026-08"

    feb = previous_monthly(_utc(2026, 3, 1))
    assert feb.period_id == "2026-02"
    weeks = _expected_period_ids(feb.starts_at.isoformat(), feb.ends_at.isoformat(), "week")
    assert len(weeks) == 5                       # W05..W09 touch February 2026
    days = _expected_period_ids(feb.starts_at.isoformat(), feb.ends_at.isoformat(), "day")
    assert len(days) == 28

    leap = previous_monthly(_utc(2028, 3, 1))
    assert leap.period_id == "2028-02"
    leap_days = _expected_period_ids(leap.starts_at.isoformat(), leap.ends_at.isoformat(), "day")
    assert len(leap_days) == 29                  # leap-year February


async def test_monthly_engine_exact_duplicate_weekly_reports():
    """Engine-level safety net: byte-identical duplicates collapse to one."""
    engine = HierarchicalLearningEngine()
    w31 = make_weekly_payload("2026-W31", pnl="100", drawdown="-20")
    w32 = make_weekly_payload("2026-W32", pnl="-40", drawdown="-60")
    result = engine.monthly_review(
        review_id="review-monthly-2026-08",
        period_id="2026-08",
        starts_at="2026-08-01T00:00:00+00:00",
        ends_at="2026-08-31T23:59:59.999999+00:00",
        weekly_reviews=[w31, dict(w31), w32],
    )
    assert result.weekly_review_ids.count("review-weekly-2026-W31") == 1
    missing = [w for w in result.warnings if w.startswith("MISSING_WEEKLY_REPORTS:")]
    assert missing == ["MISSING_WEEKLY_REPORTS:" + ",".join(
        ("2026-W33", "2026-W34", "2026-W35", "2026-W36")
    )]
    assert result.monthly_pnl == "60"            # 100 - 40, counted once


async def test_monthly_engine_deterministic_aggregation():
    engine = HierarchicalLearningEngine()
    weeklies = [
        make_weekly_payload(label, pnl=str(i * 10 - 20), drawdown=f"-{i + 1}",
                            strategy_quality={"llm-strategy": i - 1},
                            factor_quality={"momentum": 1},
                            failures={"momentum": {"total": i}},
                            conflicts={"trend": {"total": 1}})
        for i, label in enumerate(("2026-W31", "2026-W32", "2026-W33"), start=1)
    ]
    kwargs = dict(
        period_id="2026-08",
        starts_at="2026-08-01T00:00:00+00:00",
        ends_at="2026-08-31T23:59:59.999999+00:00",
    )
    first = engine.monthly_review(review_id="r1", weekly_reviews=list(weeklies), **kwargs)
    second = engine.monthly_review(review_id="r1", weekly_reviews=list(weeklies), **kwargs)
    a, b = first.to_dict(), second.to_dict()
    a.pop("created_at_utc"), b.pop("created_at_utc")
    assert a == b                                # order-insensitive dict equality
    missing_labels = b["warnings"][0].split(":", 1)[1].split(",")
    assert missing_labels == ["2026-W34", "2026-W35", "2026-W36"]


async def test_monthly_proposals_are_proposal_only_with_known_actions():
    engine = HierarchicalLearningEngine()
    stable = make_weekly_payload(
        "2026-W31", pnl="120", drawdown="-10",
        strategy_quality={"llm-strategy": 1},
        factor_quality={"momentum": 1, "vwap": 0.5},
    )
    flaky = make_weekly_payload(
        "2026-W32", pnl="-15", drawdown="-90",
        factor_quality={"momentum": 1, "chop": 0},
        failures={"chop": {"total": 4}},
        conflicts={"chop": {"total": 4}},
    )
    result = engine.monthly_review(
        review_id="review-monthly-2026-08",
        period_id="2026-08",
        starts_at="2026-08-01T00:00:00+00:00",
        ends_at="2026-08-31T23:59:59.999999+00:00",
        weekly_reviews=[stable, flaky],
    )
    proposals = result.factor_proposals + result.strategy_proposals
    assert proposals                              # both dimensions emit proposals
    for proposal in proposals:
        assert proposal["proposal_only"] is True
        assert proposal["recommendation"] in RECOMMENDATION_ACTIONS
    by_factor = {p["factor"]: p["recommendation"] for p in result.factor_proposals}
    assert by_factor["momentum"] == "INCREASE_WEIGHT_CANDIDATE"   # full-window, clean
    assert by_factor["vwap"] == "KEEP"            # used < window, no failures recorded
    assert by_factor["chop"] == "RETIRE_CANDIDATE"                # failures >= usage weeks
    strategy_actions = [p["recommendation"] for p in result.strategy_proposals]
    assert set(strategy_actions) <= set(RECOMMENDATION_ACTIONS)
    assert "llm-strategy" in {p["strategy"] for p in result.strategy_proposals}


async def test_monthly_optional_fields_absent_marked_not_available():
    engine = HierarchicalLearningEngine()
    bare = make_weekly_payload("2026-W33", pnl="25")   # no fees/funding/latency fields
    result = engine.monthly_review(
        review_id="review-monthly-2026-08",
        period_id="2026-08",
        starts_at="2026-08-01T00:00:00+00:00",
        ends_at="2026-08-31T23:59:59.999999+00:00",
        weekly_reviews=[bare],
    )
    assert result.execution_costs["fees"]["availability"] == "NOT_AVAILABLE"
    assert result.calculation_latency["availability"] == "NOT_AVAILABLE"
    # sharpe still degenerates gracefully on a single weekly point
    assert result.risk_adjusted["monthly_pnl"] == "25"


async def test_service_monthly_from_stored_weeklies_is_idempotent(database):
    service, stores = make_service(database)
    month_weeks = ("2026-W31", "2026-W32", "2026-W33", "2026-W34", "2026-W35", "2026-W36")
    pnls = {"2026-W31": "100", "2026-W32": "-30", "2026-W33": "20",
            "2026-W34": "40", "2026-W35": "-10", "2026-W36": "60"}
    for label in month_weeks:
        await stores["reviews"].store_review(
            "WEEKLY",
            make_weekly_payload(
                label, pnl=pnls[label], drawdown="-25",
                lessons_confirmed=[{"lesson_id": f"L-{label}"}],
                strategy_quality={"llm-strategy": 1},
                factor_quality={"momentum": 1},
                failures={"momentum": {"total": 0}, "orderflow": {"total": 2}},
                conflicts={},
            ),
        )

    monthly_now = _utc(2026, 9, 1)              # Sep 1 -> reviews 2026-08
    payload = await service.run_monthly(monthly_now)
    assert payload["period_id"] == "2026-08"
    assert payload["weekly_review_ids"] == [f"review-weekly-{label}" for label in month_weeks]
    assert payload["monthly_pnl"] == str(sum(int(v) for v in pnls.values()))
    assert float(payload["risk_adjusted"]["sharpe_weekly"]) > 0   # mixed series, positive mean
    assert payload["max_drawdown"] == "-25"
    assert payload["factor_usage"]["momentum"] == 6
    assert payload["factor_failure_frequency"]["orderflow"] == 12   # per-week total summed
    assert payload["confirmed_lessons"][0]["lesson_id"].startswith("L-2026-W31")

    rerun = await service.run_monthly(monthly_now)
    assert rerun == payload
    assert len(await stores["reviews"].list_period("MONTHLY", "2026-08")) == 1


async def test_service_monthly_run_does_not_touch_active_factor_set(database):
    service, _ = make_service(database)
    for label in ("2026-W31", "2026-W34"):
        await service.review_store.store_review("WEEKLY", make_weekly_payload(label))
    payload = await service.run_monthly(_utc(2026, 9, 1))

    version, status, weights = active_factor_set_state()
    assert status == "ACTIVE"
    assert version == "factorset-v1" and len(weights) == 7
    mutation_keys = {"factor_weights", "activate", "promotion", "active_version"}
    assert not mutation_keys & set(payload)


async def test_service_monthly_timezone_independent_period_selection(database):
    """Previous-completed-month selection does not depend on local machine TZ."""
    old_tz = os.environ.get("TZ")
    try:
        for tz in ("UTC", "Asia/Shanghai", "America/Los_Angeles"):
            os.environ["TZ"] = tz
            try:
                time.tzset()
            except AttributeError:  # pragma: no cover - non-unix
                pass
            assert previous_monthly(_utc(2026, 9, 1)).period_id == "2026-08"
            assert previous_weekly(_utc(2026, 9, 7)).period_id == "2026-W36"
            assert previous_weekly(_utc(2026, 9, 8)).starts_at.day == 31
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        try:
            time.tzset()
        except AttributeError:  # pragma: no cover
            pass


# --------------------------------------------------------------------- yearly


def make_monthly_payload(period_id, *, pnl="10", drawdown="-5", lessons_confirmed=(),
                         lessons_invalidated=(), extra=None):
    payload = {
        "review_id": f"review-monthly-{period_id}",
        "period_id": period_id,
        "starts_at": f"{period_id}-01T00:00:00+00:00",
        "ends_at": f"{period_id}-28T23:59:59.999999+00:00",
        "created_at_utc": _utc(2026, 1, 1).isoformat(),
        "status": "COMPLETED",
        "monthly_pnl": pnl,
        "max_drawdown": drawdown,
        "confirmed_lessons": list(lessons_confirmed),
        "invalidated_lessons": list(lessons_invalidated),
        "strategy_evaluations": [{"llm-strategy": 1}],
        "factor_evaluations": [{"momentum": 1}],
        "factor_failure_frequency": {},
        "factor_conflict_frequency": {},
        "redundancy_indicators": {},
        "sharpe_weekly": "1.000",
        "calmar": "1.000",
    }
    if extra:
        payload.update(extra)
    return payload


async def test_yearly_engine_metrics_exact_values():
    engine = HierarchicalLearningEngine()
    months = [
        make_monthly_payload("2025-01", pnl="10", drawdown="-8"),
        make_monthly_payload("2025-02", pnl="-10", drawdown="-10"),
    ]
    result = engine.yearly_review(
        review_id="review-yearly-2025",
        period_id="2025",
        starts_at="2025-01-01T00:00:00+00:00",
        ends_at="2025-12-31T23:59:59.999999+00:00",
        monthly_reviews=months,
    )
    assert result.annual_return == "0"           # 10 - 10
    assert result.max_drawdown == "-10"          # min of monthly drawdowns
    assert result.tail_risk == "-10.000"         # worst month quantized
    assert result.metric_availability["annual_return"] == "AVAILABLE"
    assert result.metric_availability["tail_risk"] == "AVAILABLE"
    assert result.metric_availability["calmar"] == "AVAILABLE"
    # mean==0 -> sharpe/sortino exactly zero, still AVAILABLE
    assert result.sharpe == "0.000"
    assert result.sortino == "0.000"
    assert result.calmar == "0.000"


async def test_yearly_engine_insufficient_evidence_markers():
    engine = HierarchicalLearningEngine()
    lone_month = make_monthly_payload("2025-06", pnl="5")
    result = engine.yearly_review(
        review_id="review-yearly-2025",
        period_id="2025",
        starts_at="2025-01-01T00:00:00+00:00",
        ends_at="2025-12-31T23:59:59.999999+00:00",
        monthly_reviews=[lone_month],
    )
    assert result.sharpe == "NOT_AVAILABLE"
    assert result.metric_availability["sharpe"] == "INSUFFICIENT_EVIDENCE"
    assert result.lesson_confirmation_rate == "INSUFFICIENT_EVIDENCE"
    assert result.lesson_rejection_rate == "INSUFFICIENT_EVIDENCE"
    stats = result.evolution_pipeline_stats
    assert stats and all(value == "NOT_AVAILABLE" for value in stats.values())
    assert result.metric_availability["evolution_pipeline_stats"] == "NOT_AVAILABLE"


async def test_yearly_engine_lesson_rates_and_lineage():
    engine = HierarchicalLearningEngine()
    months = [
        make_monthly_payload(
            "2025-03", pnl="12", drawdown="-3",
            lessons_confirmed=[{"lesson_id": "L1"}],
            lessons_invalidated=[{"lesson_id": "L2"}, {"lesson_id": "L3"}],
            extra={
                "strategy_version": "strategy-v3",
                "factor_set_version": "factorset-v2",
                "model_version": "model-7",
                "prompt_version": "prompt-4",
            },
        ),
    ]
    result = engine.yearly_review(
        review_id="review-yearly-2025",
        period_id="2025",
        starts_at="2025-01-01T00:00:00+00:00",
        ends_at="2025-12-31T23:59:59.999999+00:00",
        monthly_reviews=months,
    )
    assert result.lesson_confirmation_rate == "0.333"   # 1 / 3
    assert result.lesson_rejection_rate == "0.667"      # 2 / 3
    assert result.version_lineage == [{
        "month": "2025-03",
        "strategy_version": "strategy-v3",
        "factor_set_version": "factorset-v2",
        "model_version": "model-7",
        "prompt_version": "prompt-4",
    }]
    lifespan = result.strategy_lifespan[0]
    assert lifespan["strategy"] == "llm-strategy"
    assert lifespan["months"] == 1


async def test_service_yearly_from_stored_monthlies(database):
    service, stores = make_service(database)
    for i, month in enumerate(("2025-01", "2025-02", "2025-03")):
        await stores["reviews"].store_review(
            "MONTHLY",
            make_monthly_payload(month, pnl=str((i + 1) * 5), drawdown=f"-{i + 2}",
                                 lessons_confirmed=[{"lesson_id": f"L{i}"}]),
        )
    payload = await service.run_yearly(_utc(2026, 1, 1))
    assert payload["period_id"] == "2025"
    assert payload["monthly_review_ids"] == [
        "review-monthly-2025-01", "review-monthly-2025-02", "review-monthly-2025-03",
    ]
    assert payload["annual_return"] == "30"
    assert payload["metric_availability"]["max_drawdown"] == "AVAILABLE"
    assert payload["metric_availability"]["evolution_pipeline_stats"] == "NOT_AVAILABLE"
    assert payload["strategy_lifespan"][0]["months"] == 3

    rerun = await service.run_yearly(_utc(2026, 1, 2))
    assert rerun == payload
    assert len(await stores["reviews"].list_period("YEARLY", "2025")) == 1


async def test_service_rejects_unsupported_period_type(database):
    service, _ = make_service(database)
    with pytest.raises(ValueError):
        await service.run("BIWEEKLY", _utc(2026, 9, 7))


def test_monthly_contract_execution_summary_is_list():
    """Regression lock: execution_summary serialized as list (not legacy dict)."""
    result = MonthlyReviewResult(
        review_id="m", period_id="2026-08",
        starts_at="", ends_at="", weekly_review_ids=[],
    )
    assert isinstance(result.to_dict()["execution_summary"], list)
