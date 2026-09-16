# ruff: noqa: E501
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from crypto_trader.news.models import (
    ContradictionState,
    Direction,
    EntityLink,
    EventStatus,
    EventType,
    FactClass,
    ImpactHorizon,
    MappingMethod,
    MaterialityTier,
    NewsEventSnapshot,
    NewsEvidence,
    NoveltyState,
    ProviderHealth,
    ProviderState,
    RawNewsItem,
    ReassessmentStatus,
    RelevanceClass,
    SourceClass,
)
from crypto_trader.news.repository import NewsRepository


def _raw(raw_id: str, *, published_at: datetime, first_seen_at: datetime) -> RawNewsItem:
    return RawNewsItem(
        raw_item_id=raw_id,
        provider_id="provider_a",
        provider_item_id="item_1",
        canonical_url="https://example.com/a",
        source_domain="example.com",
        source_name="Example",
        source_type="RSS_NEWS",
        source_class=SourceClass.ESTABLISHED_NEWS,
        title="Bitcoin ETF filing update",
        summary_snippet="A factual summary.",
        raw_language="en",
        published_at=published_at,
        provider_timestamp=published_at,
        first_seen_at=first_seen_at,
        ingested_at=first_seen_at,
        updated_at=None,
        author="reporter",
        source_payload_hash="payload_hash_1",
        normalized_text_hash="normalized_hash_1",
        normalized_text="bitcoin etf filing update a factual summary",
        retrieval_status="OK",
        parse_status="OK",
    )


def _snapshot(version: int, available_at: datetime, *, direction: Direction) -> NewsEventSnapshot:
    return NewsEventSnapshot(
        event_id="newsevt_1",
        event_version=version,
        available_at=available_at,
        event_type=EventType.REGULATORY_FILING,
        fact_class=FactClass.FACT_CONFIRMED,
        canonical_title="Bitcoin ETF filing",
        factual_summary="A regulator published a filing.",
        earliest_published_at=available_at,
        latest_update_at=available_at,
        first_seen_at=available_at,
        event_status=EventStatus.OPEN,
        primary_source_item_id="newsraw_1",
        direction=direction,
        materiality_score=0.62,
        materiality_tier=MaterialityTier.HIGH,
        expires_at=available_at + timedelta(days=7),
    )


async def test_raw_item_idempotent_and_timestamps_preserved(database):
    repository = NewsRepository(database.session_factory)
    published = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    first_seen = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)
    item = _raw("newsraw_1", published_at=published, first_seen_at=first_seen)
    assert await repository.insert_raw_item(item) is True
    assert await repository.insert_raw_item(item) is False
    stored = await repository.get_raw_item("newsraw_1")
    assert stored is not None
    assert stored["published_at"] == published.isoformat()
    assert stored["first_seen_at"] == first_seen.isoformat()
    assert await repository.raw_item_count() == 1


async def test_provider_state_cursor_roundtrip(database):
    repository = NewsRepository(database.session_factory)
    now = datetime.now(UTC)
    state = ProviderState(
        provider_id="provider_a",
        cursor='{"newest_published_at":"2026-09-15T00:00:00+00:00"}',
        last_success_at=now,
        last_attempt_at=now,
        last_item_at=now,
        consecutive_errors=0,
        status=ProviderHealth.HEALTHY,
        items_ingested=4,
    )
    await repository.save_provider_state(state)
    loaded = await repository.get_provider_state("provider_a")
    assert loaded is not None
    assert loaded.cursor == state.cursor
    assert loaded.items_ingested == 4
    assert loaded.status == ProviderHealth.HEALTHY


async def test_event_versions_are_immutable_and_as_of_safe(database):
    repository = NewsRepository(database.session_factory)
    t1 = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    t2 = t1 + timedelta(hours=1)
    await repository.create_event(_snapshot(1, t1, direction=Direction.BULLISH))
    await repository.append_event_version(_snapshot(2, t2, direction=Direction.BEARISH))
    current = await repository.get_event_snapshot("newsevt_1")
    assert current is not None and current.event_version == 2
    historical = await repository.get_event_snapshot("newsevt_1", as_of=t1)
    assert historical is not None and historical.event_version == 1
    assert historical.direction == Direction.BULLISH
    assert current.direction == Direction.BEARISH


async def test_evidence_decision_refs_and_reassessment_dedup(database):
    repository = NewsRepository(database.session_factory)
    now = datetime.now(UTC)
    await repository.create_event(_snapshot(1, now, direction=Direction.BEARISH))
    await repository.insert_entity_links(
        event_id="newsevt_1",
        event_version=1,
        raw_item_id="newsraw_1",
        links=[
            EntityLink(
                entity_id="crypto:BTC",
                entity_type="TOKEN",
                symbol="BTCUSDT",
                relevance_class=RelevanceClass.DIRECT_SYMBOL,
                confidence=0.9,
                mapping_method=MappingMethod.EXACT_ALIAS,
            )
        ],
        available_at=now,
    )
    evidence = NewsEvidence(
        news_evidence_id="newsev_1",
        event_id="newsevt_1",
        event_version=1,
        evidence_version=1,
        symbol="BTCUSDT",
        relevance_class=RelevanceClass.DIRECT_SYMBOL,
        relevance_score=0.9,
        relevance_reason="explicit alias",
        direction=Direction.BEARISH,
        direction_score=-0.6,
        impact_horizon=ImpactHorizon.MULTIDAY,
        materiality_score=0.62,
        materiality_tier=MaterialityTier.HIGH,
        novelty_state=NoveltyState.NEW_EVENT,
        novelty_score=1.0,
        source_reliability_score=0.8,
        corroboration_score=0.33,
        freshness_score=0.9,
        contradiction_score=0.0,
        contradiction_state=ContradictionState.NONE,
        data_quality="FACT_CONFIRMED_OFFICIAL",
        factual_summary="Regulator filed.",
        trigger_eligible=True,
        available_at=now,
        first_seen_at=now,
        expires_at=now + timedelta(days=7),
    )
    await repository.insert_evidence(evidence)
    assert await repository.evidence_count() == 1

    inserted = await repository.insert_decision_refs(
        decision_id="llm_1",
        news_context={
            "as_of": now.isoformat(),
            "context_hash": "hash",
            "events": [
                {
                    "news_evidence_id": evidence.news_evidence_id,
                    "event_id": evidence.event_id,
                    "event_version": evidence.event_version,
                    "evidence_version": evidence.evidence_version,
                    "symbol": evidence.symbol,
                }
            ],
        },
        state_version="state_1",
        created_at=now,
    )
    assert inserted == 1
    refs = await repository.list_decision_refs("llm_1")
    assert refs[0]["ref"] == "news:newsev_1:v1"

    request = await repository.request_reassessment(
        event_id="newsevt_1",
        event_version=1,
        news_evidence_id="newsev_1",
        symbol="BTCUSDT",
        dedup_key="newsevt_1:1:BTCUSDT:ANY",
        priority="HIGH",
        materiality_tier=MaterialityTier.HIGH,
        reason="NEWS:TEST",
        requested_at=now,
    )
    assert request is not None
    duplicate = await repository.request_reassessment(
        event_id="newsevt_1",
        event_version=1,
        news_evidence_id="newsev_1",
        symbol="BTCUSDT",
        dedup_key="newsevt_1:1:BTCUSDT:ANY",
        priority="HIGH",
        materiality_tier=MaterialityTier.HIGH,
        reason="NEWS:TEST",
        requested_at=now,
    )
    assert duplicate is None
    assert await repository.claim_reassessment(request.request_id, leg_id="leg_1", state_version="s1")
    await repository.finish_reassessment(request.request_id, status=ReassessmentStatus.COMPLETED)


def test_migration_chain_creates_news_tables(tmp_path):
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path}/news_migrate.db")
    command.upgrade(cfg, "head")
    db_path = tmp_path / "news_migrate.db"
    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    for table in (
        "news_raw_items",
        "news_events",
        "news_event_versions",
        "news_event_items",
        "news_entity_links",
        "news_evidence",
        "news_provider_state",
        "news_source_profiles",
        "news_reassessment_events",
        "news_decision_refs",
        "news_outcome_reviews",
    ):
        assert table in tables
