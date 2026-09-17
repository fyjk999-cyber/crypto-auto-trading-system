# ruff: noqa: E501
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_trader.news.config import NewsConfig
from crypto_trader.news.models import (
    ProviderItem,
    SourceClass,
)
from crypto_trader.news.pipeline import NewsPipeline
from crypto_trader.news.repository import NewsRepository


def _item(
    provider_id: str,
    item_id: str,
    title: str,
    *,
    url: str | None = None,
    summary: str = "",
    published_at: datetime | None = None,
    source_domain: str = "example.com",
    source_class: SourceClass = SourceClass.ESTABLISHED_NEWS,
) -> ProviderItem:
    return ProviderItem(
        provider_id=provider_id,
        provider_item_id=item_id,
        canonical_url=url or f"https://{source_domain}/{item_id}",
        source_domain=source_domain,
        source_name=source_domain,
        source_type="RSS_NEWS",
        source_class=source_class,
        title=title,
        summary=summary,
        language="en",
        published_at=published_at or datetime.now(UTC),
        provider_timestamp=published_at or datetime.now(UTC),
        raw_payload={"title": title},
    )


async def test_exact_and_tracking_url_duplicate_collapse(database, tmp_path):
    repository = NewsRepository(database.session_factory)
    pipeline = NewsPipeline(repository, NewsConfig(enabled=True, news_dir=str(tmp_path / "news")))
    now = datetime.now(UTC)
    first = await pipeline.process_item(
        _item("p1", "a1", "Bitcoin ETF filing update", url="https://example.com/a?utm_source=x", published_at=now)
    )
    assert first.event_id is not None
    second = await pipeline.process_item(
        _item("p1", "a2", "Bitcoin ETF filing update", url="https://example.com/a?utm_medium=y", published_at=now)
    )
    assert second.skipped is True
    assert second.relation == "EXACT_DUPLICATE"
    counts = await repository.event_counts()
    assert counts["events"] == 1
    snapshot = await repository.get_current_event_snapshot(first.event_id)
    assert snapshot is not None and snapshot.source_count == 2


async def test_near_duplicate_collapses_without_false_event(database, tmp_path):
    repository = NewsRepository(database.session_factory)
    pipeline = NewsPipeline(repository, NewsConfig(enabled=True, news_dir=str(tmp_path / "news")))
    now = datetime.now(UTC)
    first = await pipeline.process_item(
        _item(
            "p1",
            "n1",
            "Bitcoin network upgrade scheduled for next month",
            source_domain="project-a.example",
            source_class=SourceClass.PROJECT_OFFICIAL,
            published_at=now,
        )
    )
    second = await pipeline.process_item(
        _item(
            "p2",
            "n2",
            "Bitcoin network upgrade scheduled next month by developers",
            source_domain="project-b.example",
            source_class=SourceClass.PROJECT_OFFICIAL,
            published_at=now + timedelta(minutes=2),
        )
    )
    assert second.event_id == first.event_id
    assert second.relation in {"NEAR_DUPLICATE", "SOURCE_UPDATE", "INDEPENDENT_CORROBORATION"}
    counts = await repository.event_counts()
    assert counts["events"] == 1


async def test_syndicated_copy_is_not_independent_corroboration(database, tmp_path):
    repository = NewsRepository(database.session_factory)
    pipeline = NewsPipeline(repository, NewsConfig(enabled=True, news_dir=str(tmp_path / "news")))
    now = datetime.now(UTC)
    first = await pipeline.process_item(
        _item(
            "official",
            "s1",
            "Bitcoin exchange service maintenance scheduled",
            source_domain="okx.com",
            source_class=SourceClass.EXCHANGE_OFFICIAL,
            published_at=now,
        )
    )
    second = await pipeline.process_item(
        _item(
            "media",
            "s2",
            "Bitcoin exchange service maintenance scheduled",
            summary="According to okx.com, the exchange will perform maintenance.",
            source_domain="media.example",
            source_class=SourceClass.ESTABLISHED_NEWS,
            published_at=now,
        )
    )
    snapshot = await repository.get_current_event_snapshot(first.event_id)
    assert snapshot is not None
    assert second.relation in {"SYNDICATED_COPY", "NEAR_DUPLICATE", "EXACT_DUPLICATE"}
    assert snapshot.source_count >= 2
    assert snapshot.independent_source_count == 1


async def test_independent_official_corroboration_increases_count(database, tmp_path):
    repository = NewsRepository(database.session_factory)
    pipeline = NewsPipeline(repository, NewsConfig(enabled=True, news_dir=str(tmp_path / "news")))
    now = datetime.now(UTC)
    first = await pipeline.process_item(
        _item(
            "official-a",
            "i1",
            "Bitcoin protocol upgrade announced by core developers",
            source_domain="project-a.example",
            source_class=SourceClass.PROJECT_OFFICIAL,
            published_at=now,
        )
    )
    second = await pipeline.process_item(
        _item(
            "official-b",
            "i2",
            "Developers confirm Bitcoin network upgrade plan",
            source_domain="project-b.example",
            source_class=SourceClass.PROJECT_OFFICIAL,
            published_at=now + timedelta(minutes=5),
        )
    )
    snapshot = await repository.get_current_event_snapshot(first.event_id)
    assert snapshot is not None
    assert second.event_id == first.event_id
    assert second.relation == "INDEPENDENT_CORROBORATION"
    assert snapshot.independent_source_count == 2
    assert snapshot.source_count == 2


async def test_material_update_creates_new_event_version(database, tmp_path):
    repository = NewsRepository(database.session_factory)
    pipeline = NewsPipeline(repository, NewsConfig(enabled=True, news_dir=str(tmp_path / "news")))
    now = datetime.now(UTC)
    first = await pipeline.process_item(
        _item(
            "exchange",
            "m1",
            "OKX exchange outage reported",
            source_domain="okx.com",
            source_class=SourceClass.EXCHANGE_OFFICIAL,
            published_at=now,
        )
    )
    second = await pipeline.process_item(
        _item(
            "exchange",
            "m2",
            "OKX exchange outage resolved and services restored",
            source_domain="okx.com",
            source_class=SourceClass.EXCHANGE_OFFICIAL,
            published_at=now + timedelta(minutes=20),
        )
    )
    assert second.event_id == first.event_id
    assert second.event_version == 2
    snapshot = await repository.get_current_event_snapshot(first.event_id)
    assert snapshot is not None
    assert snapshot.event_version == 2
    assert snapshot.novelty_state.value in {"MATERIAL_UPDATE", "MINOR_UPDATE"}


async def test_correction_and_retraction_preserve_lineage(database, tmp_path):
    repository = NewsRepository(database.session_factory)
    pipeline = NewsPipeline(repository, NewsConfig(enabled=True, news_dir=str(tmp_path / "news")))
    now = datetime.now(UTC)
    first = await pipeline.process_item(
        _item("media", "c1", "Bitcoin ETF filing reported approved", source_domain="media.example", published_at=now)
    )
    correction = await pipeline.process_item(
        _item(
            "media",
            "c2",
            "Correction: Bitcoin ETF filing report was inaccurate",
            source_domain="media.example",
            published_at=now + timedelta(hours=1),
        )
    )
    assert correction.event_id == first.event_id
    assert correction.event_version == 2
    v1 = await repository.get_event_snapshot(first.event_id, version=1)
    assert v1 is not None and v1.event_version == 1
    v2 = await repository.get_current_event_snapshot(first.event_id)
    assert v2 is not None and v2.event_version == 2
    assert v2.correction_of_version == 1
    assert v2.event_type.value == "CORRECTION"

    retraction = await pipeline.process_item(
        _item(
            "media",
            "c3",
            "Retraction: Bitcoin ETF filing report was withdrawn",
            source_domain="media.example",
            published_at=now + timedelta(hours=2),
        )
    )
    assert retraction.event_id == first.event_id
    assert retraction.event_version == 3
    v3 = await repository.get_current_event_snapshot(first.event_id)
    assert v3 is not None and v3.event_type.value == "RETRACTION"
    assert v3.correction_of_version == 2


async def test_translated_copy_with_same_url_is_duplicate(database, tmp_path):
    repository = NewsRepository(database.session_factory)
    pipeline = NewsPipeline(repository, NewsConfig(enabled=True, news_dir=str(tmp_path / "news")))
    now = datetime.now(UTC)
    first = await pipeline.process_item(
        _item("p1", "t1", "Bitcoin ETF filing update", url="https://example.com/shared", published_at=now)
    )
    translated = await pipeline.process_item(
        _item(
            "p2",
            "t2",
            "Bitcoin ETF filing update",
            url="https://example.com/shared",
            source_domain="translated.example",
            source_class=SourceClass.SECONDARY_MEDIA,
            published_at=now + timedelta(minutes=10),
        )
    )
    assert translated.event_id == first.event_id
    assert translated.relation == "EXACT_DUPLICATE"
    assert (await repository.event_counts())["events"] == 1
