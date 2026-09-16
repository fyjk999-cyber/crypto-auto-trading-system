"""N8.1/N9.1 autonomous outcome-review closure tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from crypto_trader.news.config import NewsConfig
from crypto_trader.news.models import NewsOutcomeReview
from crypto_trader.news.outcome import (
    MarketObservation,
    NewsObservationResult,
    NewsOutcomeReviewService,
)
from crypto_trader.news.outcome_observation import NewsMarketObservationProvider
from crypto_trader.news.repository import NewsRepository
from crypto_trader.news.worker import NewsWorker
from crypto_trader.persistence.models import NewsOutcomeReviewORM

TARGET = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def _candle_row(at: datetime, close: float, *, volume: float = 100.0) -> list[str]:
    ts = int(at.timestamp() * 1000)
    return [str(ts), str(close - 0.5), str(close + 1.0), str(close - 1.0), str(close),
            str(volume), str(volume), str(volume), "1"]


def _btc_rows() -> list[list[str]]:
    rows = []
    for minute in range(10, 0, -1):
        at = TARGET - timedelta(minutes=minute)
        rows.append(_candle_row(at, 100.0 + (10 - minute), volume=100.0))
    # Future bars must be excluded by the provider.
    rows.append(_candle_row(TARGET, 999.0, volume=999.0))
    rows.append(_candle_row(TARGET + timedelta(minutes=1), 1000.0, volume=999.0))
    return rows


class FakeCandleClient:
    def __init__(self, rows: list[list[str]], *, fail: bool = False) -> None:
        self.rows = rows
        self.fail = fail
        self.calls: list[tuple] = []

    async def get_candles(self, inst_id, bar, limit=300, *, after=None, before=None):
        self.calls.append((inst_id, bar, after, before))
        if self.fail:
            raise RuntimeError("source down")
        candidates = [row for row in self.rows if int(row[0]) < int(after or 0)]
        candidates.sort(key=lambda row: int(row[0]), reverse=True)
        return candidates[:limit]


class FakeOutcomeProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def observe(self, *, symbol, horizon, due_at, news_evidence_id):
        self.calls += 1
        if self.fail:
            raise RuntimeError("observation unavailable")
        return NewsObservationResult(
            status="COMPLETED",
            observation=MarketObservation(price_return=0.01, mfe=0.02, mae=-0.005),
            source="FAKE_FACTUAL",
            endpoint="/test/candles",
            target_at=TARGET,
            alignment_quality="EXACT",
            bars_used=3,
        )


async def _insert_review(
    repository: NewsRepository,
    *,
    review_id: str,
    due_at: datetime = TARGET,
    symbol: str = "BTCUSDT",
    horizon: str = "+5m",
) -> str:
    await repository.insert_outcome_review(
        NewsOutcomeReview(
            review_id=review_id,
            news_evidence_id=f"news_ev_{review_id}",
            event_id=f"event_{review_id}",
            event_version=1,
            symbol=symbol,
            horizon=horizon,
            due_at=due_at,
        )
    )
    return review_id


async def _get_review_row(database, review_id: str) -> NewsOutcomeReviewORM | None:
    async with database.session_factory() as session:
        return (
            await session.execute(
                select(NewsOutcomeReviewORM).where(
                    NewsOutcomeReviewORM.review_id == review_id
                )
            )
        ).scalar_one_or_none()


async def test_provider_uses_only_closed_horizon_candles_and_no_future(database):
    provider = NewsMarketObservationProvider(FakeCandleClient(_btc_rows()))
    result = await provider.observe(
        symbol="BTCUSDT", horizon="+5m", due_at=TARGET, news_evidence_id="ev1"
    )
    assert result.status == "COMPLETED"
    assert result.source == "OKX_PUBLIC_CANDLES"
    assert result.target_at == TARGET
    assert result.observation is not None
    observation = result.observation
    assert observation.price_return is not None
    assert observation.mfe is not None and observation.mfe >= 0
    assert observation.mae is not None
    assert observation.spread_change is None
    assert observation.oi_change is None
    assert observation.funding_change is None
    assert observation.payload["future_candles_excluded"] >= 1
    assert observation.price_return is not None and observation.price_return < 0.1
    assert result.bars_used <= 5
    assert result.observed_end_at <= TARGET


async def test_due_review_completes_with_factual_observation(database):
    repository = NewsRepository(database.session_factory)
    review_id = await _insert_review(repository, review_id="out_happy")
    service = NewsOutcomeReviewService(database.session_factory, repository=repository)
    provider = NewsMarketObservationProvider(FakeCandleClient(_btc_rows()))
    metrics = await service.process_due(provider, now=TARGET, limit=10)
    assert metrics["processed"] == 1
    row = await _get_review_row(database, review_id)
    assert row is not None and row.status == "COMPLETED"
    assert row.observed_at is not None
    assert row.price_return is not None
    payload = row.payload_json or {}
    assert payload["target_at"] == TARGET.isoformat()
    assert payload["source"] == "OKX_PUBLIC_CANDLES"
    assert payload["alignment_quality"] in {"EXACT", "PARTIAL"}
    assert payload["causal_claim"] is False


async def test_transient_source_error_is_retryable_then_completes(database):
    repository = NewsRepository(database.session_factory)
    review_id = await _insert_review(repository, review_id="out_retry")
    service = NewsOutcomeReviewService(database.session_factory, repository=repository)
    client = FakeCandleClient(_btc_rows(), fail=True)
    provider = NewsMarketObservationProvider(client)
    first = await service.process_due(provider, now=TARGET)
    assert first["transient"] == 1
    row = await _get_review_row(database, review_id)
    assert row is not None and row.status == "TRANSIENT_SOURCE_ERROR"
    due = await repository.due_outcome_reviews(now=TARGET, limit=10)
    assert any(item["review_id"] == review_id for item in due)

    client.fail = False
    second = await service.process_due(provider, now=TARGET)
    assert second["processed"] == 1
    completed = await _get_review_row(database, review_id)
    assert completed is not None and completed.status == "COMPLETED"


async def test_data_gap_records_inconclusive_and_due_query_does_not_retry(database):
    repository = NewsRepository(database.session_factory)
    review_id = await _insert_review(repository, review_id="out_gap")
    service = NewsOutcomeReviewService(database.session_factory, repository=repository)
    provider = NewsMarketObservationProvider(FakeCandleClient([], fail=False))
    metrics = await service.process_due(provider, now=TARGET)
    assert metrics["inconclusive"] == 1
    row = await _get_review_row(database, review_id)
    assert row is not None and row.status == "INCONCLUSIVE_DATA_GAP"
    due = await repository.due_outcome_reviews(now=TARGET + timedelta(days=1), limit=10)
    assert all(item["review_id"] != review_id for item in due)


async def test_completed_review_is_immutable_and_idempotent(database):
    repository = NewsRepository(database.session_factory)
    review_id = await _insert_review(repository, review_id="out_idem")
    service = NewsOutcomeReviewService(database.session_factory, repository=repository)
    provider = FakeOutcomeProvider()
    first = await service.process_due(provider, now=TARGET)
    second = await service.process_due(provider, now=TARGET)
    assert first["processed"] == 1
    assert second["due"] == 0
    updated_again = await repository.update_outcome_review(
        review_id, status="COMPLETED", payload={"price_return": 9.9}
    )
    assert updated_again is False
    row = await _get_review_row(database, review_id)
    assert row is not None and row.status == "COMPLETED"
    assert row.price_return == 0.01


async def test_restart_safe_pending_review_resumes_after_restart(database):
    repository = NewsRepository(database.session_factory)
    review_id = await _insert_review(repository, review_id="out_restart")
    config = NewsConfig(enabled=True, max_outcome_reviews_per_cycle=5)
    first_worker = NewsWorker(
        database.session_factory, config, providers=[], repository=repository,
        outcome_provider=FakeOutcomeProvider(),
    )
    first = await first_worker.run_once()
    assert first["outcome_completed"] == 1
    second_worker = NewsWorker(
        database.session_factory, config, providers=[], repository=repository,
        outcome_provider=FakeOutcomeProvider(),
    )
    second = await second_worker.run_once()
    assert second["outcome_completed"] == 0
    row = await _get_review_row(database, review_id)
    assert row is not None and row.status == "COMPLETED"
    async with database.session_factory() as session:
        count = len(
            (
                await session.execute(
                    select(NewsOutcomeReviewORM).where(
                        NewsOutcomeReviewORM.review_id == review_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert count == 1


async def test_worker_bounds_due_reviews_per_cycle(database):
    repository = NewsRepository(database.session_factory)
    for index in range(3):
        await _insert_review(repository, review_id=f"out_bound_{index}")
    provider = FakeOutcomeProvider()
    config = NewsConfig(enabled=True, max_outcome_reviews_per_cycle=2)
    worker = NewsWorker(
        database.session_factory, config, providers=[], repository=repository,
        outcome_provider=provider,
    )
    metrics = await worker.run_once()
    assert provider.calls == 2
    assert metrics["outcome_due"] == 2
    assert metrics["outcome_completed"] == 2


async def test_worker_survives_outcome_provider_failure(database, tmp_path):
    repository = NewsRepository(database.session_factory)
    await _insert_review(repository, review_id="out_fail")
    config = NewsConfig(enabled=True, news_dir=str(tmp_path / "news"))
    worker = NewsWorker(
        database.session_factory, config, providers=[], repository=repository,
        outcome_provider=FakeOutcomeProvider(fail=True),
    )
    metrics = await worker.run_once()
    assert metrics["outcome_transient"] == 1
    assert (tmp_path / "news" / "news_heartbeat.json").exists()
    row = await _get_review_row(database, "out_fail")
    assert row is not None and row.status == "TRANSIENT_SOURCE_ERROR"
