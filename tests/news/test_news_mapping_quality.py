# ruff: noqa: E501
from __future__ import annotations

from datetime import UTC, datetime

from crypto_trader.news.config import NewsConfig
from crypto_trader.news.entities import direct_symbol_links, map_entities
from crypto_trader.news.models import (
    BROAD_SYMBOL,
    EventType,
    FactClass,
    ProviderItem,
    RelevanceClass,
    SourceClass,
)
from crypto_trader.news.pipeline import NewsPipeline
from crypto_trader.news.repository import NewsRepository
from crypto_trader.news.sources import default_profile, source_class_for
from crypto_trader.news.taxonomy import classify_event, classify_fact_class


def test_direct_asset_mapping_and_ambiguous_ticker_safety():
    links = map_entities("Bitcoin ETF filing update", event_type=EventType.REGULATORY_FILING)
    direct = direct_symbol_links(links)
    assert any(link.symbol == "BTCUSDT" for link in direct)
    assert all(link.confidence >= 0.55 for link in direct)

    ambiguous = map_entities("OP token listing update", event_type=EventType.LISTING)
    ambiguous_links = [link for link in ambiguous if link.ambiguous]
    assert ambiguous_links
    assert ambiguous_links[0].symbol == "OPUSDT"
    assert ambiguous_links[0].confidence < 0.55


def test_broad_exchange_and_macro_relevance_do_not_fake_direct_symbols():
    exchange_links = map_entities("OKX exchange outage", event_type=EventType.EXCHANGE_OUTAGE)
    exchange_broad = [link for link in exchange_links if link.relevance_class == RelevanceClass.EXCHANGE]
    assert exchange_broad
    assert not direct_symbol_links(exchange_links)

    macro_links = map_entities("Fed rate decision and CPI release", event_type=EventType.RATE_DECISION)
    macro_broad = [link for link in macro_links if link.relevance_class == RelevanceClass.MACRO]
    assert macro_broad
    assert macro_broad[0].symbol is None
    assert not direct_symbol_links(macro_links)


def test_taxonomy_unknown_stays_unknown_and_fact_claim_separation():
    assert classify_event("Quarterly newsletter published") == EventType.UNKNOWN
    assert classify_event("Bitcoin exchange outage reported") == EventType.EXCHANGE_OUTAGE
    official = classify_fact_class("Exchange reports outage", SourceClass.EXCHANGE_OFFICIAL, EventType.EXCHANGE_OUTAGE)
    media = classify_fact_class("Exchange reportedly reports outage", SourceClass.ESTABLISHED_NEWS, EventType.RUMOR)
    assert official == FactClass.FACT_CONFIRMED
    assert media == FactClass.SOURCE_CLAIM


def test_versioned_source_profiles():
    assert source_class_for("okx.com") == SourceClass.EXCHANGE_OFFICIAL
    profile = default_profile(
        source_domain="okx.com",
        source_name="OKX",
        source_class=SourceClass.EXCHANGE_OFFICIAL,
    )
    assert profile.source_policy_version
    assert 0.0 <= profile.reliability_score <= 1.0


async def test_macro_news_evidence_uses_broad_universe_not_fake_symbol(database, tmp_path):
    repository = NewsRepository(database.session_factory)
    pipeline = NewsPipeline(repository, NewsConfig(enabled=True, news_dir=str(tmp_path / "news")))
    now = datetime.now(UTC)
    item = ProviderItem(
        provider_id="p1",
        provider_item_id="macro-1",
        canonical_url="https://example.com/macro-1",
        source_domain="example.com",
        source_name="Example",
        source_type="RSS_NEWS",
        source_class=SourceClass.ESTABLISHED_NEWS,
        title="Fed rate decision and CPI release",
        summary="Macro calendar facts.",
        language="en",
        published_at=now,
        provider_timestamp=now,
    )
    result = await pipeline.process_item(item)
    snapshot = await repository.get_current_event_snapshot(result.event_id)
    assert snapshot is not None
    assert "BTCUSDT" not in snapshot.symbols
    links = await repository.list_entity_links(result.event_id, 1)
    assert any(link["relevance_class"] == RelevanceClass.MACRO.value for link in links)
    assert not any(link["relevance_class"] == RelevanceClass.DIRECT_SYMBOL.value for link in links)
    # Evidence must still be persisted for the broad universe; no direct fake claim.
    from crypto_trader.news.retrieval import NewsRetriever

    retriever = NewsRetriever(database.session_factory, include_broad=True)
    context = await retriever.get_news_context("BTCUSDT", as_of=datetime.now(UTC))
    assert context["events"]
    assert all(event["symbol"] == BROAD_SYMBOL for event in context["events"])


async def test_source_profile_persistence_roundtrip(database):
    repository = NewsRepository(database.session_factory)
    profile = default_profile(
        source_domain="cointelegraph.com",
        source_name="Cointelegraph",
        source_class=SourceClass.ESTABLISHED_NEWS,
    )
    await repository.upsert_source_profile(profile)
    loaded = await repository.get_source_profile("cointelegraph.com", profile.source_policy_version)
    assert loaded is not None
    assert loaded.reliability_score == profile.reliability_score
    assert loaded.source_policy_version == profile.source_policy_version
