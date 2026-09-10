"""P8: daily review ownership, restart recovery, late revision, idempotency."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from crypto_trader.governance.daily_review import DailyReviewStats
from crypto_trader.governance.memory_persistence import MemoryPersistence
from crypto_trader.governance.scheduler import DailyReviewScheduler
from crypto_trader.persistence.models import (
    AIMarketPatternORM,
    AITradeReviewORM,
    DailyReviewRunORM,
    TradeEpisodeORM,
)

REVIEW_DATE = "2026-09-09"
CLOSED_AT = datetime(2026, 9, 9, 12, tzinfo=UTC)


def _episode(index: int, *, closed_at: datetime = CLOSED_AT) -> TradeEpisodeORM:
    return TradeEpisodeORM(
        episode_id=f"p8_ep_{index}",
        trade_plan_id=f"p8_plan_{index}",
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
        holding_time_seconds=1.0,
        entry_market_regime="TREND",
        terminal_reason="EXIT",
        factual=True,
        review_status="PENDING",
        opened_at=closed_at - timedelta(hours=1),
        closed_at=closed_at,
    )


async def _insert_episodes(database, count: int, *, closed_at: datetime = CLOSED_AT) -> None:
    async with database.session_factory() as session:
        session.add_all([_episode(i, closed_at=closed_at) for i in range(count)])
        await session.commit()


def _stats(date: str = REVIEW_DATE) -> DailyReviewStats:
    return DailyReviewStats(date=date, daily_pnl=Decimal("10"))


async def _expire_review_claim(database, date: str = REVIEW_DATE) -> None:
    from datetime import timedelta

    async with database.session_factory() as session:
        row = (
            await session.execute(
                select(DailyReviewRunORM).where(DailyReviewRunORM.review_date == date)
            )
        ).scalar_one()
        row.claim_deadline_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()


async def _review_row(database, date: str = REVIEW_DATE) -> DailyReviewRunORM:
    async with database.session_factory() as session:
        return (
            await session.execute(
                select(DailyReviewRunORM).where(DailyReviewRunORM.review_date == date)
            )
        ).scalar_one()


async def test_two_workers_claim_once_and_old_token_cannot_publish(database):
    persistence = MemoryPersistence(database.session_factory)
    start = datetime(2026, 9, 9, tzinfo=UTC)
    end = datetime(2026, 9, 10, tzinfo=UTC)
    first, second = await asyncio.gather(
        persistence.begin_daily_review(
            REVIEW_DATE, start, end, owner="worker-a", lease_seconds=60
        ),
        persistence.begin_daily_review(
            REVIEW_DATE, start, end, owner="worker-b", lease_seconds=60
        ),
    )
    tokens = [token for token in (first, second) if token is not None]
    assert len(tokens) == 1
    old_token = tokens[0]
    assert await persistence.heartbeat_daily_review(
        REVIEW_DATE, old_token, owner="worker-a"
    ) in {True}

    # Simulate the old worker's deadline expiring after a restart.
    async with database.session_factory() as session:
        row = (
            await session.execute(
                select(DailyReviewRunORM).where(
                    DailyReviewRunORM.review_date == REVIEW_DATE
                )
            )
        ).scalar_one()
        row.claim_deadline_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    new_token = await persistence.begin_daily_review(
        REVIEW_DATE, start, end, owner="worker-c", lease_seconds=60
    )
    assert new_token is not None and new_token != old_token

    assert not await persistence.heartbeat_daily_review(REVIEW_DATE, old_token)
    assert not await persistence.fail_daily_review(
        REVIEW_DATE, "OLD", "stale token", claim_token=old_token
    )
    assert not await persistence.save_daily_review(
        REVIEW_DATE, _stats(), claim_token=old_token
    )
    row = await _review_row(database)
    assert row.status == "RUNNING"
    assert row.claim_token == new_token
    assert row.attempt_count == 2
    assert await persistence.save_daily_review(
        REVIEW_DATE, _stats(), claim_token=new_token
    )
    row = await _review_row(database)
    assert row.status == "SUCCEEDED"
    # Old token still cannot overwrite the published result.
    assert not await persistence.save_daily_review(
        REVIEW_DATE,
        DailyReviewStats(date=REVIEW_DATE, daily_pnl=Decimal("999")),
        claim_token=old_token,
    )
    row = await _review_row(database)
    assert row.daily_pnl == Decimal("10")


@pytest.mark.parametrize("count", [1001, 2501])
async def test_large_episode_day_and_same_closed_at_are_fully_reviewed(database, count):
    await _insert_episodes(database, count)
    scheduler = DailyReviewScheduler(database.session_factory, canonical_only=True)
    result = await scheduler.run_once(REVIEW_DATE)
    assert result["status"] == "SUCCEEDED"
    assert result["episode_count"] == count
    assert result["reviewed_this_attempt"] == count
    async with database.session_factory() as session:
        episodes = (
            await session.execute(select(TradeEpisodeORM))
        ).scalars().all()
        reviews = (await session.execute(select(AITradeReviewORM))).scalars().all()
        pattern = (await session.execute(select(AIMarketPatternORM))).scalar_one()
    assert len(episodes) == count
    assert all(episode.review_status == "REVIEWED" for episode in episodes)
    assert len(reviews) == count
    assert pattern.sample_count == count
    # A second run is a no-op and never duplicates learning.
    second = await scheduler.run_once(REVIEW_DATE)
    assert second.get("idempotent") is True
    async with database.session_factory() as session:
        assert (
            await session.execute(select(AITradeReviewORM))
        ).scalars().all().__len__() == count


async def test_late_episode_revision_reviews_only_the_late_episode(database):
    await _insert_episodes(database, 1)
    scheduler = DailyReviewScheduler(database.session_factory, canonical_only=True)
    first = await scheduler.run_once(REVIEW_DATE)
    assert first["status"] == "SUCCEEDED"
    # A late factual episode for the same closed day appears afterwards.
    late = _episode(9999, closed_at=CLOSED_AT)
    late.episode_id = "p8_ep_late"
    late.trade_plan_id = "p8_plan_late"
    async with database.session_factory() as session:
        session.add(late)
        await session.commit()
    # The first successful claim still owns the mark lease; only an expired
    # (abandoned) claim may be revised.
    blocked = await scheduler.run_once(REVIEW_DATE)
    assert blocked is not None and blocked.get("idempotent") is True
    await _expire_review_claim(database)

    revised = await scheduler.run_once(REVIEW_DATE)
    assert revised["status"] == "SUCCEEDED"
    assert revised["episode_count"] == 2
    assert revised["reviewed_this_attempt"] == 1
    async with database.session_factory() as session:
        reviews = (await session.execute(select(AITradeReviewORM))).scalars().all()
        pattern = (await session.execute(select(AIMarketPatternORM))).scalar_one()
    assert len(reviews) == 2
    assert pattern.sample_count == 2
    row = await _review_row(database)
    assert row.attempt_count == 2
    # Late revision publishes the same SUCCEEDED state once; no third run.
    third = await scheduler.run_once(REVIEW_DATE)
    assert third.get("idempotent") is True


async def test_failure_after_learning_retries_without_duplicates(database, monkeypatch):
    await _insert_episodes(database, 1)
    scheduler = DailyReviewScheduler(database.session_factory, canonical_only=True)
    calls = {"mark": 0}

    async def flaky_mark(*_args, **_kwargs):
        calls["mark"] += 1
        raise RuntimeError("simulated crash before mark_reviewed")

    real_fenced = scheduler.episodes.mark_reviewed_fenced
    monkeypatch.setattr(
        scheduler.episodes, "mark_reviewed_fenced", flaky_mark
    )
    with pytest.raises(RuntimeError):
        await scheduler.run_once(REVIEW_DATE)
    row = await _review_row(database)
    # SUCCEEDED was already fenced/published; only episode marking failed.
    assert row.status == "SUCCEEDED"
    async with database.session_factory() as session:
        episode = (await session.execute(select(TradeEpisodeORM))).scalar_one()
    assert episode.review_status == "PENDING"
    # Retry as a late revision without duplicating review data.
    await _expire_review_claim(database)
    monkeypatch.setattr(
        scheduler.episodes,
        "mark_reviewed_fenced",
        real_fenced,
    )
    result = await scheduler.run_once(REVIEW_DATE)
    assert result["status"] == "SUCCEEDED"
    assert result["reviewed_this_attempt"] == 1
    async with database.session_factory() as session:
        reviews = (await session.execute(select(AITradeReviewORM))).scalars().all()
        pattern = (await session.execute(select(AIMarketPatternORM))).scalar_one()
    assert len(reviews) == 1
    assert pattern.sample_count == 1


async def test_failure_before_publish_never_marks_episode(database, monkeypatch):
    await _insert_episodes(database, 1)
    scheduler = DailyReviewScheduler(database.session_factory, canonical_only=True)
    original_save = scheduler.persistence.save_daily_review
    calls = {"save": 0}
    mark_calls = {"count": 0}

    async def flaky_save(*args, **kwargs):
        calls["save"] += 1
        if calls["save"] == 1:
            raise RuntimeError("simulated crash before SUCCEEDED")
        return await original_save(*args, **kwargs)

    async def spy_mark(*_args, **_kwargs):
        mark_calls["count"] += 1
        return True

    monkeypatch.setattr(scheduler.persistence, "save_daily_review", flaky_save)
    monkeypatch.setattr(scheduler.episodes, "mark_reviewed_fenced", spy_mark)
    with pytest.raises(RuntimeError):
        await scheduler.run_once(REVIEW_DATE)
    row = await _review_row(database)
    assert row.status == "FAILED"
    # Publishing the fenced SUCCEEDED failed, so episodes must stay PENDING.
    async with database.session_factory() as session:
        episode = (await session.execute(select(TradeEpisodeORM))).scalar_one()
    assert episode.review_status == "PENDING"
    assert mark_calls["count"] == 0

    result = await scheduler.run_once(REVIEW_DATE)
    assert result["status"] == "SUCCEEDED"
    assert result["reviewed_this_attempt"] == 1
    async with database.session_factory() as session:
        reviews = (await session.execute(select(AITradeReviewORM))).scalars().all()
        pattern = (await session.execute(select(AIMarketPatternORM))).scalar_one()
    assert len(reviews) == 1
    assert pattern.sample_count == 1


async def test_middle_day_failure_does_not_block_other_days(database, monkeypatch):
    await _insert_episodes(
        database, 1, closed_at=datetime(2026, 9, 8, 12, tzinfo=UTC)
    )
    scheduler = DailyReviewScheduler(database.session_factory, canonical_only=True)

    async def always_fail(episodes):
        if not episodes:
            return
        raise RuntimeError("middle day failure")

    monkeypatch.setattr(scheduler.learning, "review_many", always_fail)
    results = await scheduler.run_missed_days("2026-09-08", "2026-09-09")
    assert results[0] == {"date": "2026-09-08", "failed": True}
    assert results[1]["status"] == "SUCCEEDED"
    first = await _review_row(database, "2026-09-08")
    assert first.status == "FAILED"
