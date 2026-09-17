# ruff: noqa: E501
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_trader.news.config import NewsConfig
from crypto_trader.news.materiality import (
    compute_contradiction,
    compute_freshness,
    compute_novelty,
    direction_for,
    materiality_score,
    materiality_tier,
    trigger_eligible,
)
from crypto_trader.news.models import (
    ContradictionState,
    Direction,
    EventType,
    FreshnessState,
    MaterialityTier,
    NewsEventSnapshot,
    NoveltyState,
    ProviderItem,
    RelevanceClass,
    SourceClass,
)
from crypto_trader.news.pipeline import NewsPipeline
from crypto_trader.news.repository import NewsRepository


def _existing(direction: Direction = Direction.BULLISH, version: int = 1) -> NewsEventSnapshot:
    now = datetime.now(UTC)
    return NewsEventSnapshot(
        event_id="evt",
        event_version=version,
        available_at=now,
        event_type=EventType.LISTING,
        fact_class="FACT_CONFIRMED",
        canonical_title="Bitcoin listing",
        factual_summary="A listing.",
        earliest_published_at=now,
        latest_update_at=now,
        first_seen_at=now,
        event_status="OPEN",
        primary_source_item_id="raw",
        direction=direction,
        novelty_state=NoveltyState.NEW_EVENT,
        source_count=1,
        independent_source_count=1,
    )


def test_freshness_depends_on_event_class_and_late_discovery():
    now = datetime.now(UTC)
    state, score, expires, reason = compute_freshness(
        event_type=EventType.EXCHANGE_OUTAGE,
        reference_at=now - timedelta(hours=1),
        first_seen_at=now,
        now=now,
    )
    assert state == FreshnessState.FRESH
    assert score > 0.5
    assert expires is not None

    state, score, _expires, reason = compute_freshness(
        event_type=EventType.EXCHANGE_OUTAGE,
        reference_at=now - timedelta(hours=7),
        first_seen_at=now - timedelta(hours=7),
        now=now,
    )
    assert state == FreshnessState.EXPIRED
    assert score == 0.0
    assert reason

    structural, structural_score, structural_expires, reason = compute_freshness(
        event_type=EventType.TOKEN_UNLOCK,
        reference_at=now - timedelta(days=5),
        first_seen_at=now,
        now=now,
    )
    assert structural in {FreshnessState.FRESH, FreshnessState.AGING}
    assert structural_score > 0.0
    assert structural_expires is not None

    stale, stale_score, _expires, stale_reason = compute_freshness(
        event_type=EventType.EXCHANGE_OUTAGE,
        reference_at=now - timedelta(days=30),
        first_seen_at=now,
        now=now,
    )
    assert stale == FreshnessState.STALE_DISCOVERY
    assert stale_score == 0.0


def test_materiality_tiers_and_noise_suppression():
    high = materiality_score(
        event_type=EventType.EXPLOIT,
        relevance_class=RelevanceClass.DIRECT_SYMBOL,
        source_reliability=0.95,
        corroboration=0.8,
        novelty=NoveltyState.NEW_EVENT,
        freshness_score=1.0,
        contradiction_score=0.0,
        direction_score=-0.6,
        uncertainty_count=1,
        mapping_confidence=0.9,
    )
    noise = materiality_score(
        event_type=EventType.UNKNOWN,
        relevance_class=RelevanceClass.UNKNOWN,
        source_reliability=0.2,
        corroboration=0.0,
        novelty=NoveltyState.MINOR_UPDATE,
        freshness_score=0.1,
        contradiction_score=0.0,
        direction_score=0.0,
        uncertainty_count=6,
        mapping_confidence=0.0,
    )
    assert materiality_tier(high) in {MaterialityTier.CRITICAL, MaterialityTier.HIGH}
    assert materiality_tier(noise) in {MaterialityTier.LOW, MaterialityTier.NOISE}
    assert not trigger_eligible(
        tier=MaterialityTier.HIGH,
        novelty=NoveltyState.CORROBORATION_ONLY,
        freshness=FreshnessState.FRESH,
        relevance_class=RelevanceClass.DIRECT_SYMBOL,
        mapping_confidence=0.9,
    )
    assert not trigger_eligible(
        tier=MaterialityTier.HIGH,
        novelty=NoveltyState.NEW_EVENT,
        freshness=FreshnessState.EXPIRED,
        relevance_class=RelevanceClass.DIRECT_SYMBOL,
        mapping_confidence=0.9,
    )
    assert trigger_eligible(
        tier=MaterialityTier.HIGH,
        novelty=NoveltyState.NEW_EVENT,
        freshness=FreshnessState.FRESH,
        relevance_class=RelevanceClass.DIRECT_SYMBOL,
        mapping_confidence=0.9,
    )


def test_novelty_material_update_correction_and_duplicate():
    now = datetime.now(UTC)
    existing = _existing()
    duplicate, _score, _notes = compute_novelty(
        existing=existing,
        relation="EXACT_DUPLICATE",
        event_type=EventType.LISTING,
        direction=Direction.BULLISH,
        title="same",
        summary="same",
        correction=False,
        retraction=False,
        first_seen_at=now,
        published_at=now,
        now=now,
    )
    assert duplicate == NoveltyState.DUPLICATE

    material, _score, _notes = compute_novelty(
        existing=existing,
        relation="SOURCE_UPDATE",
        event_type=EventType.CORRECTION,
        direction=Direction.MIXED,
        title="correction",
        summary="changed",
        correction=False,
        retraction=False,
        first_seen_at=now,
        published_at=now,
        now=now,
    )
    assert material == NoveltyState.MATERIAL_UPDATE

    correction, _score, _notes = compute_novelty(
        existing=existing,
        relation="SOURCE_UPDATE",
        event_type=EventType.CORRECTION,
        direction=Direction.MIXED,
        title="Correction: report was inaccurate",
        summary="changed",
        correction=True,
        retraction=False,
        first_seen_at=now,
        published_at=now,
        now=now,
    )
    assert correction == NoveltyState.CORRECTION


def test_direction_is_not_article_tone_and_contradiction_preserved():
    direction, score, horizon, support, counter, uncertainty = direction_for(
        event_type=EventType.PATCH_RECOVERY,
        title="Exploit recovery: funds restored after security incident",
        summary="A negative-tone recap.",
    )
    assert direction in {Direction.BULLISH, Direction.MIXED}
    assert direction != Direction.BEARISH
    assert support and counter and uncertainty

    existing = _existing(direction=Direction.BULLISH)
    state, contradiction_score, notes = compute_contradiction(
        existing=existing,
        event_type=EventType.REGULATORY_REJECTION,
        direction=Direction.BEARISH,
        title="Regulator rejects filing",
        summary="Officials denied the proposal.",
    )
    assert state == ContradictionState.CONFLICT
    assert contradiction_score > 0
    assert notes


async def test_pipeline_evidence_keeps_support_and_counter_points(database, tmp_path):
    repository = NewsRepository(database.session_factory)
    pipeline = NewsPipeline(repository, NewsConfig(enabled=True, news_dir=str(tmp_path / "news")))
    now = datetime.now(UTC)
    item = ProviderItem(
        provider_id="p1",
        provider_item_id="mat-1",
        canonical_url="https://example.com/mat-1",
        source_domain="example.com",
        source_name="Example",
        source_type="RSS_NEWS",
        source_class=SourceClass.ESTABLISHED_NEWS,
        title="Bitcoin exchange hack funds drained",
        summary="Factual report of an exploit.",
        language="en",
        published_at=now,
        provider_timestamp=now,
    )
    result = await pipeline.process_item(item)
    assert result.evidence_ids
    async with database.session_factory() as session:
        from sqlalchemy import select

        from crypto_trader.persistence.models import NewsEvidenceORM

        row = (await session.execute(select(NewsEvidenceORM).where(NewsEvidenceORM.news_evidence_id == result.evidence_ids[0]))).scalar_one()
    assert row.support_points_json
    assert row.counter_points_json
    assert row.materiality_tier in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "NOISE"}
