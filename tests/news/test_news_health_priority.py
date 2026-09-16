"""Provider health truth and bounded news priority ordering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from crypto_trader.news.config import NewsConfig, NewsProviderConfig
from crypto_trader.news.models import (
    AggregateHealth,
    ProviderHealth,
    ProviderItem,
    ProviderState,
    SourceClass,
)
from crypto_trader.news.providers import FetchResult, NewsProvider
from crypto_trader.news.repository import NewsRepository
from crypto_trader.news.status import _aggregate_health
from crypto_trader.news.worker import NewsWorker, _item_priority
from crypto_trader.persistence.models import NewsRawItemORM


def _status_row(status: ProviderHealth) -> dict:
    return {"status": status.value}


def test_all_providers_down_is_no_news_even_with_cached_events():
    assert _aggregate_health([], 10) == AggregateHealth.NO_NEWS_AVAILABLE
    assert _aggregate_health(
        [_status_row(ProviderHealth.NETWORK_ERROR), _status_row(ProviderHealth.DISABLED)], 10
    ) == AggregateHealth.NO_NEWS_AVAILABLE


def test_one_provider_down_is_partial_and_all_healthy_is_healthy():
    assert _aggregate_health(
        [_status_row(ProviderHealth.HEALTHY), _status_row(ProviderHealth.NETWORK_ERROR)], 10
    ) == AggregateHealth.PARTIAL_NEWS_AVAILABLE
    assert _aggregate_health(
        [_status_row(ProviderHealth.HEALTHY), _status_row(ProviderHealth.HEALTHY)], 0
    ) == AggregateHealth.HEALTHY


def test_priority_orders_critical_official_direct_then_noise():
    now = datetime.now(UTC)
    critical = SimpleNamespace(
        source_class=SourceClass.REGULATORY_OFFICIAL,
        title="SEC enforcement action against exchange",
        summary="security incident and halt",
        published_at=now - timedelta(hours=2),
    )
    direct = SimpleNamespace(
        source_class=SourceClass.EXCHANGE_OFFICIAL,
        title="Bitcoin ETF filing update",
        summary="",
        published_at=now,
    )
    noise = SimpleNamespace(
        source_class=SourceClass.ESTABLISHED_NEWS,
        title="Quarterly newsletter published",
        summary="",
        published_at=now,
    )
    ordered = sorted([noise, direct, critical], key=_item_priority)
    assert ordered[0] is critical
    assert ordered[1] is direct
    assert ordered[2] is noise


class _FakeProvider(NewsProvider):
    kind = "FAKE"

    def __init__(self, config, items) -> None:
        super().__init__(config)
        self.items = list(items)

    async def fetch_since(self, cursor):
        return FetchResult(
            items=list(self.items),
            cursor="cursor-1",
            fetched_at=datetime.now(UTC),
            health=ProviderHealth.HEALTHY,
        )


def _provider_config(provider_id: str = "priority") -> NewsProviderConfig:
    return NewsProviderConfig(
        provider_id=provider_id,
        kind="FAKE",
        url="https://example.com/feed",
        source_name="Example",
        source_domain="example.com",
        source_type="RSS_NEWS",
        source_class=SourceClass.ESTABLISHED_NEWS,
    )


def _item(
    item_id: str, title: str, source_class: SourceClass, published_at: datetime
) -> ProviderItem:
    return ProviderItem(
        provider_id="priority",
        provider_item_id=item_id,
        canonical_url=f"https://example.com/{item_id}",
        source_domain="example.com",
        source_name="Example",
        source_type="RSS_NEWS",
        source_class=source_class,
        title=title,
        summary="",
        language="en",
        published_at=published_at,
        provider_timestamp=published_at,
    )


async def test_worker_backpressure_picks_critical_item_first(database, tmp_path):
    now = datetime.now(UTC)
    repository = NewsRepository(database.session_factory)
    items = [
        _item("noise", "Quarterly newsletter published", SourceClass.ESTABLISHED_NEWS, now),
        _item(
            "direct",
            "Bitcoin ETF filing update",
            SourceClass.EXCHANGE_OFFICIAL,
            now,
        ),
        _item(
            "critical",
            "SEC enforcement action and exchange halt",
            SourceClass.REGULATORY_OFFICIAL,
            now - timedelta(hours=2),
        ),
    ]
    config = NewsConfig(
        enabled=True,
        news_dir=str(tmp_path / "news"),
        max_items_per_cycle=1,
        outcome_reviews_enabled=False,
    )
    worker = NewsWorker(
        database.session_factory,
        config,
        providers=[_FakeProvider(_provider_config(), items)],
        repository=repository,
    )
    await worker.run_once()
    async with database.session_factory() as session:
        rows = (await session.execute(select(NewsRawItemORM))).scalars().all()
    assert [row.provider_item_id for row in rows] == ["critical"]


async def test_retriever_health_is_no_news_when_all_providers_fail(database):
    repository = NewsRepository(database.session_factory)
    await repository.save_provider_state(
        ProviderState(provider_id="p1", status=ProviderHealth.NETWORK_ERROR)
    )
    await repository.save_provider_state(
        ProviderState(provider_id="p2", status=ProviderHealth.DISABLED)
    )
    from crypto_trader.news.retrieval import NewsRetriever

    health = await NewsRetriever(database.session_factory)._health()
    assert health == AggregateHealth.NO_NEWS_AVAILABLE
