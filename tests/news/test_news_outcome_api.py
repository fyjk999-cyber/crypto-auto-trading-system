# ruff: noqa: E501
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from crypto_trader.api.app import create_app
from crypto_trader.api.deps import AppState
from crypto_trader.config import Settings
from crypto_trader.ledger.service import LedgerService
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.news.config import NewsConfig
from crypto_trader.news.models import ProviderItem, SourceClass
from crypto_trader.news.outcome import MarketObservation, NewsOutcomeReviewService
from crypto_trader.news.pipeline import NewsPipeline
from crypto_trader.news.repository import NewsRepository
from crypto_trader.observability.audit import AuditService
from crypto_trader.order.manager import OrderManager
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.reconciliation.service import ReconciliationService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.lease import LeaseManager


def _state(database) -> AppState:
    settings = Settings(app_env="test", trading_mode="PAPER", database_url=database.url)
    return AppState(
        settings=settings,
        database=database,
        order_manager=OrderManager(database.session_factory),
        ledger=LedgerService(database.session_factory),
        portfolio=PortfolioService(database.session_factory),
        audit=AuditService(database.session_factory),
        risk=RiskEngine(),
        market_data=MarketDataService(),
        leases=LeaseManager(database.session_factory),
        reconciliation=ReconciliationService(database.session_factory),
    )


def _item(item_id: str, title: str, published_at: datetime) -> ProviderItem:
    return ProviderItem(
        provider_id="p1",
        provider_item_id=item_id,
        canonical_url=f"https://example.com/{item_id}",
        source_domain="example.com",
        source_name="Example",
        source_type="RSS_NEWS",
        source_class=SourceClass.ESTABLISHED_NEWS,
        title=title,
        summary="",
        language="en",
        published_at=published_at,
        provider_timestamp=published_at,
    )


class FakeObservationProvider:
    def __init__(self):
        self.calls = 0

    async def observe(self, *, symbol, horizon, due_at, news_evidence_id):
        self.calls += 1
        return MarketObservation(
            price_return=0.01,
            mfe=0.02,
            mae=-0.005,
            realized_volatility=0.03,
            rvol=1.5,
            spread_change=0.0001,
            oi_change=0.02,
            funding_change=0.0001,
            payload={"counterfactual": True},
        )


async def test_outcome_reviews_schedule_and_do_not_claim_causality(database, tmp_path):
    repository = NewsRepository(database.session_factory)
    pipeline = NewsPipeline(repository, NewsConfig(enabled=True, news_dir=str(tmp_path / "news")))
    now = datetime.now(UTC)
    result = await pipeline.process_item(
        _item("out-1", "Bitcoin ETF filing approved", now), now=now
    )
    assert result.evidence_ids
    counts = await repository.outcome_counts()
    assert counts["total"] >= 7
    assert counts["pending"] >= 7

    provider = FakeObservationProvider()
    service = NewsOutcomeReviewService(database.session_factory, repository=repository)
    metrics = await service.process_due(provider, now=now + timedelta(days=2))
    assert metrics["processed"] >= 7
    assert provider.calls >= 7

    async with database.session_factory() as session:
        from sqlalchemy import select

        from crypto_trader.persistence.models import NewsOutcomeReviewORM

        rows = (
            (
                await session.execute(
                    select(NewsOutcomeReviewORM).where(
                        NewsOutcomeReviewORM.news_evidence_id == result.evidence_ids[0]
                    )
                )
            )
            .scalars()
            .all()
        )
    assert rows
    assert all(row.causal_claim is False for row in rows)
    assert all(row.counterfactual_label == "NON_FACTUAL" for row in rows)


async def test_growth_lineage_reconstructable_for_event(database, tmp_path):
    repository = NewsRepository(database.session_factory)
    pipeline = NewsPipeline(repository, NewsConfig(enabled=True, news_dir=str(tmp_path / "news")))
    now = datetime.now(UTC)
    result = await pipeline.process_item(_item("lin-1", "Bitcoin ETF filing approved", now), now=now)
    await repository.insert_decision_refs(
        decision_id="llm_lineage",
        news_context={
            "as_of": now.isoformat(),
            "context_hash": "hash",
            "events": [
                {
                    "news_evidence_id": result.evidence_ids[0],
                    "event_id": result.event_id,
                    "event_version": result.event_version,
                    "evidence_version": result.event_version,
                    "symbol": "BTCUSDT",
                }
            ],
        },
        state_version="state_1",
        created_at=now,
    )
    refs = await repository.list_event_decision_refs(result.event_id)
    assert refs
    assert refs[0]["decision_id"] == "llm_lineage"
    assert refs[0]["ref"].startswith("news:")


async def test_news_read_only_api_endpoints(database, tmp_path):
    repository = NewsRepository(database.session_factory)
    pipeline = NewsPipeline(repository, NewsConfig(enabled=True, news_dir=str(tmp_path / "news")))
    now = datetime.now(UTC)
    result = await pipeline.process_item(_item("api-1", "Bitcoin ETF filing approved", now), now=now)
    state = _state(database)
    client = TestClient(create_app(state))
    status = client.get("/news/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["raw_items"] == 1
    assert payload["events"] == 1
    assert payload["service"]["authority"] == "EVIDENCE_ONLY"

    events = client.get("/news/events")
    assert events.status_code == 200
    body = events.json()
    assert body["count"] == 1
    assert body["events"][0]["event_id"] == result.event_id
    assert body["events"][0]["is_order"] is False

    detail = client.get(f"/news/events/{result.event_id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["event"]["event_id"] == result.event_id
    assert detail_body["items"]
    assert detail_body["evidence"]

    missing = client.get("/news/events/does-not-exist")
    assert missing.status_code == 404
    assert client.post(f"/news/events/{result.event_id}").status_code == 405
