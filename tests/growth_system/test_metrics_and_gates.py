"""G07: stage-separated metrics and gate helpers (TEST_ONLY)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.learning.growth_metrics import (
    collect_growth_metrics,
    next_utc_review_time,
)
from crypto_trader.learning.growth_models import (
    GrowthCompressionORM,
    GrowthLearningJobORM,
    GrowthLessonORM,
    GrowthPatternORM,
    GrowthReviewAttemptORM,
    GrowthToolSelectionORM,
    create_growth_schema,
)
from crypto_trader.persistence.models import DailyReviewRunORM, TradeEpisodeORM

NOW = datetime(2026, 9, 11, 8, 0, tzinfo=UTC)


def test_next_utc_review_time_rolls_to_next_day():
    assert next_utc_review_time("00:00", now=datetime(2026, 9, 11, 8, 0, tzinfo=UTC)) == datetime(
        2026, 9, 12, 0, 0, tzinfo=UTC
    )
    assert next_utc_review_time("09:00", now=datetime(2026, 9, 11, 8, 0, tzinfo=UTC)) == datetime(
        2026, 9, 11, 9, 0, tzinfo=UTC
    )


async def _seed_metrics_rows(database) -> None:
    await create_growth_schema(database.engine)
    async with database.session_factory() as session:
        closed = NOW - timedelta(days=3)
        for index, status in enumerate(("PENDING", "PENDING", "REVIEWED")):
            session.add(
                TradeEpisodeORM(
                    episode_id=f"metric_ep_{index}",
                    trade_plan_id=f"metric_plan_{index}",
                    symbol="BTCUSDT",
                    direction="LONG",
                    entry_decision_id=f"entry_{index}",
                    exit_decision_id=f"exit_{index}",
                    entry_price=Decimal("100"),
                    exit_price=Decimal("101"),
                    opened_quantity=Decimal("1"),
                    closed_quantity=Decimal("1"),
                    leverage=Decimal("1"),
                    fees=Decimal("0"),
                    funding_pnl=Decimal("0"),
                    gross_pnl=Decimal("1"),
                    net_pnl=Decimal("1"),
                    holding_time_seconds=60,
                    entry_market_regime="TREND",
                    terminal_reason="EXIT",
                    factual=True,
                    review_status=status,
                    opened_at=closed - timedelta(hours=1),
                    closed_at=closed + timedelta(minutes=index),
                )
            )
        session.add(
            DailyReviewRunORM(
                review_date="2026-09-09",
                status="SUCCEEDED",
                trade_count=1,
                output_ref="daily_review:2026-09-09",
            )
        )
        session.add_all(
            [
                GrowthLearningJobORM(
                    job_key="job_metrics",
                    account_id="default",
                    mode="PAPER",
                    review_date="2026-09-10",
                    source_revision="src",
                    profile_version="p1",
                    revision=1,
                    input_hash="h1",
                    stats_status="SUCCEEDED",
                    review_status="SUCCEEDED",
                    publish_status="PENDING",
                    attempt_count=2,
                    claim_deadline_at=NOW + timedelta(minutes=10),
                    created_at=closed,
                ),
                GrowthReviewAttemptORM(
                    attempt_id="attempt_ok",
                    review_date="2026-09-10",
                    episode_id="metric_ep_0",
                    account_id="default",
                    mode="PAPER",
                    symbol="BTCUSDT",
                    direction="LONG",
                    profile_version="p1",
                    prompt_version="v1",
                    schema_version="v1",
                    provider="deepseek",
                    input_hash="h1",
                    prompt_hash="ph",
                    schema_hash="sh",
                    status="SUCCEEDED",
                    usage_status="KNOWN",
                    usage_json={"prompt_tokens": 40, "completion_tokens": 60},
                ),
                GrowthReviewAttemptORM(
                    attempt_id="attempt_failed",
                    review_date="2026-09-10",
                    episode_id="metric_ep_1",
                    account_id="default",
                    mode="PAPER",
                    symbol="BTCUSDT",
                    direction="LONG",
                    profile_version="p1",
                    prompt_version="v1",
                    schema_version="v1",
                    provider="deepseek",
                    input_hash="h2",
                    prompt_hash="ph2",
                    schema_hash="sh",
                    status="FAILED",
                    error_type="PROVIDER_HTTP_500",
                    usage_status="UNKNOWN",
                    usage_json=None,
                ),
                GrowthLessonORM(
                    lesson_id="lesson_metric",
                    version=1,
                    source_id="metric_ep_0",
                    episode_id="metric_ep_0",
                    account_id="default",
                    mode="PAPER",
                    symbol="BTCUSDT",
                    direction="LONG",
                    regime="TREND",
                    statement="A testable statement.",
                    status="VALIDATED",
                    sample_count=3,
                    known_at=closed,
                ),
                GrowthPatternORM(
                    pattern_id="pattern_metric",
                    version=1,
                    account_id="default",
                    mode="PAPER",
                    symbol="BTCUSDT",
                    regime="TREND",
                    direction="LONG",
                    pattern_key="default:PAPER:BTCUSDT:TREND:LONG",
                    sample_count=3,
                    independent_sample_count=3,
                    status="VALIDATED",
                    known_at=closed,
                ),
                GrowthCompressionORM(
                    compression_id="compression_metric",
                    version=1,
                    account_id="default",
                    mode="PAPER",
                    title="Conditional",
                    content="A conditional hypothesis.",
                    source_set_hash="s",
                    sample_count=3,
                    status="PUBLISHED",
                    known_at=closed,
                ),
                GrowthToolSelectionORM(
                    selection_id="selection_metric",
                    account_id="default",
                    mode="PAPER",
                    context_id="ctx-1",
                    decision_id="decision_1",
                    as_of=closed,
                    selected_tools_json=["memory_search"],
                    returned_refs_json=["lesson:lesson_metric:v1"],
                    evidence_package_json={"source_refs": ["lesson:lesson_metric:v1"]},
                    prompt_hash="ph",
                ),
            ]
        )
        await session.commit()


async def test_metrics_report_stages_separately_and_never_zero_fill_usage(database):
    await _seed_metrics_rows(database)
    metrics = await collect_growth_metrics(
        database.session_factory, now=NOW, review_time_utc="00:00"
    )
    assert metrics.factual_episodes == 3
    assert metrics.episodes_pending == 2
    assert metrics.episodes_reviewed == 1
    assert metrics.stats_complete == 1
    assert metrics.llm_reviewed == 1
    assert metrics.knowledge_published == 0  # publish is still PENDING
    assert metrics.jobs_failed == 0
    assert metrics.jobs_retried == 1
    assert metrics.review_attempts_succeeded == 1
    assert metrics.review_attempts_failed == 1
    assert metrics.usage_known_tokens == 100
    assert metrics.usage_unknown_attempts == 1
    assert metrics.lessons_published == 1
    assert metrics.patterns_published == 1
    assert metrics.compressions_published == 1
    assert metrics.tool_selections == 1
    assert metrics.retrieved_refs == 1
    assert metrics.cited_refs == 1
    assert metrics.last_succeeded_review_date == "2026-09-09"
    assert metrics.oldest_pending_closed_at is not None
    assert metrics.oldest_backlog_days and metrics.oldest_backlog_days > 2
    assert metrics.claim_active == 1
    assert metrics.next_utc_review_at == datetime(2026, 9, 12, 0, 0, tzinfo=UTC)
    assert any("UNKNOWN usage" in note for note in metrics.notes)


async def test_growth_schema_is_additive_and_compiles_for_both_dialects(database):
    from crypto_trader.learning.growth_models import (
        GROWTH_TABLES,
        GrowthBase,
        create_growth_schema,
        growth_schema_sql,
    )
    from crypto_trader.persistence.models import Base

    assert set(GrowthBase.metadata.tables).isdisjoint(set(Base.metadata.tables))
    assert len(GROWTH_TABLES) == 10
    sqlite_sql = growth_schema_sql("sqlite")
    postgres_sql = growth_schema_sql("postgresql")
    assert len(sqlite_sql) == len(postgres_sql) == len(GROWTH_TABLES)
    assert all(statement.startswith("CREATE TABLE") for statement in sqlite_sql)
    assert any("growth_learning_jobs" in statement for statement in postgres_sql)
    # create_all is idempotent on an already-migrated test database.
    await create_growth_schema(database.engine)
    await create_growth_schema(database.engine)
