# ruff: noqa: E501
"""Canonical News ingestion/derivation pipeline.

    provider item -> RawNewsItem -> normalize -> dedup/cluster -> event
    -> entity mapping -> source/freshness/novelty/direction/materiality
    -> NewsEvidence -> optional reassessment request

The only executable effects are SQL inserts into the News-owned tables and an
optional reassessment request row. This module cannot place an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from crypto_trader.domain.identifiers import new_id
from crypto_trader.news.config import NewsConfig
from crypto_trader.news.dedup import classify_duplicate
from crypto_trader.news.entities import map_entities
from crypto_trader.news.materiality import (
    compute_contradiction,
    compute_freshness,
    compute_novelty,
    direction_for,
    event_status_for,
    materiality_score,
    materiality_tier,
    trigger_eligible,
)
from crypto_trader.news.models import (
    BROAD_SYMBOL,
    CLUSTERING_POLICY_VERSION,
    DEDUP_POLICY_VERSION,
    FRESHNESS_POLICY_VERSION,
    MATERIALITY_POLICY_VERSION,
    SOURCE_POLICY_VERSION,
    EntityLink,
    EventType,
    MaterialityTier,
    NewsCycleMetrics,
    NewsEventSnapshot,
    NewsEvidence,
    NoveltyState,
    ProviderItem,
    RawNewsItem,
    RelevanceClass,
)
from crypto_trader.news.normalization import (
    canonicalize_url,
    hash_text,
    normalize_for_compare,
    sanitize_external_text,
    source_payload_hash,
)
from crypto_trader.news.sources import default_profile, source_class_for
from crypto_trader.news.taxonomy import (
    classify_event,
    classify_fact_class,
    is_correction,
    is_retraction,
)


@dataclass(slots=True)
class ProcessResult:
    created: bool = False
    raw_item_id: str | None = None
    event_id: str | None = None
    event_version: int | None = None
    relation: str | None = None
    novelty: NoveltyState | None = None
    materiality_tier: MaterialityTier | None = None
    evidence_ids: list[str] = field(default_factory=list)
    reassessment_request_id: str | None = None
    skipped: bool = False
    stage: str = "DONE"


class NewsPipeline:
    def __init__(self, repository, config: NewsConfig, *, clock=None) -> None:
        self.repository = repository
        self.config = config
        self._clock = clock or (lambda: datetime.now(UTC))
        self.metrics = NewsCycleMetrics()

    async def process_item(self, item: ProviderItem, *, now: datetime | None = None) -> ProcessResult:
        moment = _aware(now or self._clock())
        title = sanitize_external_text(item.title, max_len=2000)
        summary = sanitize_external_text(item.summary, max_len=8000)
        canonical_url = canonicalize_url(item.canonical_url)
        source_class = source_class_for(item.source_domain, item.source_name, item.source_class)
        payload_hash = source_payload_hash(
            item.provider_id,
            item.provider_item_id,
            title,
            summary,
            _iso(item.published_at),
            _iso(item.provider_timestamp),
        )
        raw = RawNewsItem(
            raw_item_id=new_id("newsraw"),
            provider_id=item.provider_id,
            provider_item_id=item.provider_item_id,
            canonical_url=canonical_url,
            source_domain=item.source_domain,
            source_name=item.source_name,
            source_type=item.source_type,
            source_class=source_class,
            title=title,
            summary_snippet=summary,
            raw_language=item.language or "und",
            published_at=_optional_aware(item.published_at),
            provider_timestamp=_optional_aware(item.provider_timestamp),
            first_seen_at=moment,
            ingested_at=moment,
            updated_at=_optional_aware(item.updated_at),
            author=item.author,
            source_payload_hash=payload_hash,
            normalized_text_hash=hash_text(f"{title} {summary}"),
            normalized_text=normalize_for_compare(f"{title} {summary}"),
            retrieval_status="OK",
            parse_status="OK",
            source_metadata=dict(item.metadata or {}),
            raw_payload=dict(item.raw_payload or {}),
        )
        inserted = await self.repository.insert_raw_item(raw)
        if not inserted:
            self.metrics.dropped_or_deferred += 1
            return ProcessResult(created=False, raw_item_id=raw.raw_item_id, skipped=True, stage="DUPLICATE_RAW")
        self.metrics.items_ingested += 1

        event_type = classify_event(title, summary)
        fact_class = classify_fact_class(title, source_class, event_type)
        links = map_entities(title, summary, event_type)
        url_candidate = await self.repository.event_snapshot_for_url(canonical_url)
        candidates = await self.repository.find_recent_event_snapshots(
            symbols=[link.symbol for link in links if link.symbol and not link.ambiguous],
            entities=[
                link.entity_id
                for link in links
                if not link.entity_id.startswith(("unmapped:", "ambiguous:", "broad:"))
            ],
            since=moment - timedelta(seconds=self.config.overlap_seconds),
            limit=80,
        )
        if url_candidate is not None:
            candidates = [url_candidate, *[c for c in candidates if c.event_id != url_candidate.event_id]]
        chosen, relation = _choose_candidate(raw, candidates)
        if chosen is None:
            return await self._create_event(
                raw=raw,
                item=item,
                links=links,
                event_type=event_type,
                fact_class=fact_class,
                now=moment,
            )
        return await self._apply_to_event(
            raw=raw,
            item=item,
            candidate=chosen,
            relation=relation,
            links=links,
            event_type=event_type,
            fact_class=fact_class,
            now=moment,
        )

    # ------------------------------------------------------------ new event
    async def _create_event(
        self,
        *,
        raw: RawNewsItem,
        item: ProviderItem,
        links: list[EntityLink],
        event_type: EventType,
        fact_class,
        now: datetime,
    ) -> ProcessResult:
        source_profile = await self._source_profile(raw)
        direction, direction_score, horizon, support, counter, uncertainty = direction_for(
            event_type=event_type, title=raw.title, summary=raw.summary_snippet, fact_class=fact_class.value
        )
        freshness_state, freshness, expires_at, stale_reason = compute_freshness(
            event_type=event_type,
            reference_at=raw.updated_at or raw.published_at or raw.first_seen_at,
            first_seen_at=raw.first_seen_at,
            now=now,
        )
        correction = is_correction(raw.title, raw.summary_snippet)
        retraction = is_retraction(raw.title, raw.summary_snippet)
        novelty, novelty_score, novelty_notes = compute_novelty(
            existing=None,
            relation="",
            event_type=event_type,
            direction=direction,
            title=raw.title,
            summary=raw.summary_snippet,
            correction=correction,
            retraction=retraction,
            first_seen_at=raw.first_seen_at,
            published_at=raw.published_at,
            now=now,
        )
        contradiction_state, contradiction_score, contradictions = compute_contradiction(
            existing=None,
            event_type=event_type,
            direction=direction,
            title=raw.title,
            summary=raw.summary_snippet,
        )
        if stale_reason:
            uncertainty = [*uncertainty, stale_reason]
        if novelty_notes:
            uncertainty = [*uncertainty, *novelty_notes]
        materiality = materiality_score(
            event_type=event_type,
            relevance_class=_primary_relevance(links),
            source_reliability=source_profile.reliability_score,
            corroboration=1.0 / 3.0,
            novelty=novelty,
            freshness_score=freshness,
            contradiction_score=contradiction_score,
            direction_score=direction_score,
            uncertainty_count=len(uncertainty),
            mapping_confidence=_primary_mapping_confidence(links),
        )
        tier = materiality_tier(materiality)
        eligible = trigger_eligible(
            tier=tier,
            novelty=novelty,
            freshness=freshness_state,
            relevance_class=_primary_relevance(links),
            mapping_confidence=_primary_mapping_confidence(links),
        )
        event_id = new_id("newsevt")
        snapshot = _snapshot(
            event_id=event_id,
            event_version=1,
            now=now,
            event_type=event_type,
            fact_class=fact_class,
            raw=raw,
            links=links,
            direction=direction,
            direction_score=direction_score,
            horizon=horizon,
            source_profile=source_profile,
            freshness_state=freshness_state,
            freshness_score=freshness,
            expires_at=expires_at,
            novelty=novelty,
            contradiction_state=contradiction_state,
            contradictions=contradictions,
            contradiction_score=contradiction_score,
            materiality=materiality,
            tier=tier,
            source_count=1,
            independent_source_count=1,
            support=support,
            counter=counter,
            uncertainty=uncertainty,
            event_status=event_status_for(novelty, event_type),
            correction_of_version=None,
            trigger=eligible,
        )
        await self.repository.create_event(snapshot)
        await self.repository.link_event_item(
            event_id=event_id,
            event_version=1,
            raw_item_id=raw.raw_item_id,
            relation="PRIMARY",
            independent=True,
            source_domain=raw.source_domain,
            created_at=now,
        )
        await self.repository.insert_entity_links(
            event_id=event_id,
            event_version=1,
            raw_item_id=raw.raw_item_id,
            links=links,
            available_at=now,
        )
        evidence_ids, request_id = await self._persist_evidence_and_wake(
            snapshot=snapshot,
            raw=raw,
            links=links,
            source_profile=source_profile,
            now=now,
            trigger=eligible,
        )
        self.metrics.events_created += 1
        if stale_reason:
            self.metrics.stale_discoveries += 1
        if tier in {MaterialityTier.CRITICAL, MaterialityTier.HIGH, MaterialityTier.MEDIUM}:
            self.metrics.material_events += 1
        return ProcessResult(
            created=True,
            raw_item_id=raw.raw_item_id,
            event_id=event_id,
            event_version=1,
            relation="NEW_EVENT",
            novelty=novelty,
            materiality_tier=tier,
            evidence_ids=evidence_ids,
            reassessment_request_id=request_id,
        )

    # --------------------------------------------------------- event update
    async def _apply_to_event(
        self,
        *,
        raw: RawNewsItem,
        item: ProviderItem,
        candidate: NewsEventSnapshot,
        relation: str,
        links: list[EntityLink],
        event_type: EventType,
        fact_class,
        now: datetime,
    ) -> ProcessResult:
        if relation in {"EXACT_DUPLICATE", "NEAR_DUPLICATE", "SYNDICATED_COPY"}:
            independent = relation not in {"EXACT_DUPLICATE", "NEAR_DUPLICATE", "SYNDICATED_COPY"}
            await self.repository.link_event_item(
                event_id=candidate.event_id,
                event_version=candidate.event_version,
                raw_item_id=raw.raw_item_id,
                relation=relation,
                independent=False,
                source_domain=raw.source_domain,
                created_at=now,
            )
            await self.repository.update_event_counters(
                candidate.event_id,
                source_count=candidate.source_count + 1,
                independent_source_count=candidate.independent_source_count + (1 if independent else 0),
                latest_update_at=max_filter(_aware(candidate.latest_update_at), raw.published_at, now),
            )
            if relation == "EXACT_DUPLICATE":
                self.metrics.duplicates_exact += 1
            elif relation == "NEAR_DUPLICATE":
                self.metrics.duplicates_near += 1
            else:
                self.metrics.duplicates_syndicated += 1
            return ProcessResult(
                created=False,
                raw_item_id=raw.raw_item_id,
                event_id=candidate.event_id,
                event_version=candidate.event_version,
                relation=relation,
                novelty=NoveltyState.DUPLICATE if relation == "EXACT_DUPLICATE" else NoveltyState.CORROBORATION_ONLY,
                materiality_tier=candidate.materiality_tier,
                skipped=True,
                stage="DUPLICATE_COLLAPSED",
            )

        source_profile = await self._source_profile(raw)
        independent = relation == "INDEPENDENT_CORROBORATION"
        source_count = candidate.source_count + 1
        independent_count = candidate.independent_source_count + (1 if independent else 0)
        resolved_type = candidate.event_type
        if event_type != EventType.UNKNOWN:
            resolved_type = event_type
        correction = is_correction(raw.title, raw.summary_snippet)
        retraction = is_retraction(raw.title, raw.summary_snippet)
        if retraction:
            resolved_type = EventType.RETRACTION
        elif correction:
            resolved_type = EventType.CORRECTION
        direction, direction_score, horizon, support, counter, uncertainty = direction_for(
            event_type=resolved_type,
            title=raw.title,
            summary=raw.summary_snippet,
            fact_class=fact_class.value,
        )
        reference_at = max_filter(raw.updated_at, raw.published_at, candidate.latest_update_at, now)
        freshness_state, freshness, expires_at, stale_reason = compute_freshness(
            event_type=resolved_type,
            reference_at=reference_at,
            first_seen_at=candidate.first_seen_at,
            now=now,
        )
        novelty, novelty_score, novelty_notes = compute_novelty(
            existing=candidate,
            relation=relation,
            event_type=resolved_type,
            direction=direction,
            title=raw.title,
            summary=raw.summary_snippet,
            correction=correction,
            retraction=retraction,
            first_seen_at=raw.first_seen_at,
            published_at=raw.published_at,
            now=now,
        )
        contradiction_state, contradiction_score, contradictions = compute_contradiction(
            existing=candidate,
            event_type=resolved_type,
            direction=direction,
            title=raw.title,
            summary=raw.summary_snippet,
        )
        corroboration = min(1.0, independent_count / 3.0)
        if stale_reason:
            uncertainty = [*uncertainty, stale_reason]
        if novelty_notes:
            uncertainty = [*uncertainty, *novelty_notes]
        materiality = materiality_score(
            event_type=resolved_type,
            relevance_class=_primary_relevance(links),
            source_reliability=source_profile.reliability_score,
            corroboration=corroboration,
            novelty=novelty,
            freshness_score=freshness,
            contradiction_score=contradiction_score,
            direction_score=direction_score,
            uncertainty_count=len(uncertainty),
            mapping_confidence=_primary_mapping_confidence(links),
        )
        tier = materiality_tier(materiality)
        eligible = trigger_eligible(
            tier=tier,
            novelty=novelty,
            freshness=freshness_state,
            relevance_class=_primary_relevance(links),
            mapping_confidence=_primary_mapping_confidence(links),
        )
        version = candidate.event_version + 1
        snapshot = _snapshot(
            event_id=candidate.event_id,
            event_version=version,
            now=now,
            event_type=resolved_type,
            fact_class=fact_class,
            raw=raw,
            links=links,
            direction=direction,
            direction_score=direction_score,
            horizon=horizon,
            source_profile=source_profile,
            freshness_state=freshness_state,
            freshness_score=freshness,
            expires_at=expires_at,
            novelty=novelty,
            contradiction_state=contradiction_state,
            contradictions=contradictions,
            contradiction_score=contradiction_score,
            materiality=materiality,
            tier=tier,
            source_count=source_count,
            independent_source_count=independent_count,
            support=support,
            counter=counter,
            uncertainty=uncertainty,
            event_status=event_status_for(novelty, resolved_type),
            correction_of_version=candidate.event_version if (correction or retraction) else None,
            trigger=eligible,
            canonical_title=raw.title or candidate.canonical_title,
            factual_summary=raw.summary_snippet or candidate.factual_summary,
            earliest_published_at=min_filter(candidate.earliest_published_at, raw.published_at) or candidate.first_seen_at,
            latest_update_at=max_filter(candidate.latest_update_at, raw.published_at, now),
            primary_source_item_id=raw.raw_item_id,
        )
        await self.repository.append_event_version(snapshot)
        await self.repository.link_event_item(
            event_id=candidate.event_id,
            event_version=version,
            raw_item_id=raw.raw_item_id,
            relation=relation,
            independent=independent,
            source_domain=raw.source_domain,
            created_at=now,
        )
        await self.repository.insert_entity_links(
            event_id=candidate.event_id,
            event_version=version,
            raw_item_id=raw.raw_item_id,
            links=links,
            available_at=now,
        )
        evidence_ids, request_id = await self._persist_evidence_and_wake(
            snapshot=snapshot,
            raw=raw,
            links=links,
            source_profile=source_profile,
            now=now,
            trigger=eligible,
        )
        self.metrics.event_updates += 1
        if retraction:
            self.metrics.retractions += 1
        if correction:
            self.metrics.corrections += 1
        if independent:
            self.metrics.independent_corroborations += 1
        if tier in {MaterialityTier.CRITICAL, MaterialityTier.HIGH, MaterialityTier.MEDIUM}:
            self.metrics.material_events += 1
        return ProcessResult(
            created=True,
            raw_item_id=raw.raw_item_id,
            event_id=candidate.event_id,
            event_version=version,
            relation=relation,
            novelty=novelty,
            materiality_tier=tier,
            evidence_ids=evidence_ids,
            reassessment_request_id=request_id,
        )

    async def _source_profile(self, raw: RawNewsItem):
        existing = await self.repository.get_source_profile(raw.source_domain, SOURCE_POLICY_VERSION)
        if existing is not None:
            return existing
        profile = default_profile(
            source_domain=raw.source_domain,
            source_name=raw.source_name,
            source_class=raw.source_class,
        )
        await self.repository.upsert_source_profile(profile)
        return profile

    async def _persist_evidence_and_wake(
        self,
        *,
        snapshot: NewsEventSnapshot,
        raw: RawNewsItem,
        links: list[EntityLink],
        source_profile,
        now: datetime,
        trigger: bool,
    ) -> tuple[list[str], str | None]:
        source_ref = {
            "provider_id": raw.provider_id,
            "raw_item_id": raw.raw_item_id,
            "canonical_url": raw.canonical_url,
            "source_domain": raw.source_domain,
            "source_name": raw.source_name,
            "source_class": raw.source_class.value,
            "published_at": _iso(raw.published_at),
            "first_seen_at": _iso(raw.first_seen_at),
        }
        evidence_ids: list[str] = []
        request_id: str | None = None
        for symbol, relevance, reason, link in _evidence_specs(links):
            confidence = max(0.0, min(1.0, link.confidence))
            eligible = trigger and confidence >= 0.55
            if snapshot.payload.get("trigger_eligible") and confidence >= 0.55:
                eligible = True
            if not trigger:
                eligible = False
            evidence = NewsEvidence(
                news_evidence_id=new_id("newsev"),
                event_id=snapshot.event_id,
                event_version=snapshot.event_version,
                evidence_version=snapshot.event_version,
                symbol=symbol,
                relevance_class=relevance,
                relevance_score=confidence,
                relevance_reason=reason,
                direction=snapshot.direction,
                direction_score=snapshot.direction_score,
                impact_horizon=snapshot.impact_horizon,
                materiality_score=snapshot.materiality_score,
                materiality_tier=snapshot.materiality_tier,
                novelty_state=snapshot.novelty_state,
                novelty_score=float(snapshot.payload.get("novelty_score") or 0.0),
                source_reliability_score=float(source_profile.reliability_score),
                corroboration_score=min(1.0, snapshot.independent_source_count / 3.0),
                freshness_score=float(snapshot.payload.get("freshness_score") or 0.0),
                contradiction_score=float(snapshot.payload.get("contradiction_score") or 0.0),
                contradiction_state=snapshot.contradiction_state,
                data_quality="FACT_CONFIRMED_OFFICIAL"
                if snapshot.fact_class.value == "FACT_CONFIRMED"
                else "SOURCE_CLAIM",
                factual_summary=snapshot.factual_summary or snapshot.canonical_title,
                support_points=list(snapshot.payload.get("support_points") or []),
                counter_points=list(snapshot.payload.get("counter_points") or []),
                uncertainty=list(snapshot.payload.get("uncertainty") or []),
                source_refs=[source_ref],
                raw_item_refs=[raw.raw_item_id],
                trigger_eligible=eligible,
                available_at=now,
                first_seen_at=snapshot.first_seen_at,
                expires_at=snapshot.expires_at,
                source_policy_version=SOURCE_POLICY_VERSION,
                freshness_policy_version=FRESHNESS_POLICY_VERSION,
                materiality_policy_version=MATERIALITY_POLICY_VERSION,
                dedup_policy_version=DEDUP_POLICY_VERSION,
            )
            await self.repository.insert_evidence(evidence)
            evidence_ids.append(evidence.news_evidence_id)
            if eligible and request_id is None:
                request = await self.repository.request_reassessment(
                    event_id=snapshot.event_id,
                    event_version=snapshot.event_version,
                    news_evidence_id=evidence.news_evidence_id,
                    symbol=symbol,
                    dedup_key=f"{snapshot.event_id}:{snapshot.event_version}:{symbol}:ANY",
                    priority=_priority_for(snapshot.materiality_tier),
                    materiality_tier=snapshot.materiality_tier,
                    reason=f"NEWS:{snapshot.event_type.value}:{snapshot.materiality_tier.value}",
                    requested_at=now,
                    context={
                        "event_id": snapshot.event_id,
                        "event_version": snapshot.event_version,
                        "news_evidence_id": evidence.news_evidence_id,
                        "symbol": symbol,
                        "materiality": snapshot.materiality_tier.value,
                        "novelty": snapshot.novelty_state.value,
                        "direction": snapshot.direction.value,
                        "as_of": _iso(now),
                    },
                )
                if request is None:
                    self.metrics.reassessment_suppressed += 1
                else:
                    request_id = request.request_id
                    self.metrics.reassessment_requests += 1
        self.metrics.evidence_created += len(evidence_ids)
        return evidence_ids, request_id


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def _choose_candidate(
    raw: RawNewsItem, candidates: list[NewsEventSnapshot]
) -> tuple[NewsEventSnapshot | None, str]:
    ranked = {
        "EXACT_DUPLICATE": 6,
        "SOURCE_UPDATE": 5,
        "NEAR_DUPLICATE": 4,
        "SYNDICATED_COPY": 3,
        "INDEPENDENT_CORROBORATION": 2,
        "RELATED_DISTINCT_EVENT": 0,
    }
    best: tuple[int, NewsEventSnapshot | None, str] = (0, None, "NEW_EVENT")
    for candidate in candidates:
        relation = classify_duplicate(raw, candidate).value
        rank = ranked.get(relation, 0)
        if rank > best[0]:
            best = (rank, candidate, relation)
    return best[1], best[2]


def _snapshot(
    *,
    event_id: str,
    event_version: int,
    now: datetime,
    event_type: EventType,
    fact_class,
    raw: RawNewsItem,
    links: list[EntityLink],
    direction,
    direction_score: float,
    horizon,
    source_profile,
    freshness_state,
    freshness_score: float,
    expires_at: datetime | None,
    novelty: NoveltyState,
    contradiction_state,
    contradictions: list[dict],
    contradiction_score: float,
    materiality: float,
    tier: MaterialityTier,
    source_count: int,
    independent_source_count: int,
    support: list[str],
    counter: list[str],
    uncertainty: list[str],
    event_status,
    correction_of_version: int | None,
    trigger: bool,
    canonical_title: str | None = None,
    factual_summary: str | None = None,
    earliest_published_at: datetime | None = None,
    latest_update_at: datetime | None = None,
    primary_source_item_id: str | None = None,
) -> NewsEventSnapshot:
    direct_symbols = sorted(
        {
            link.symbol
            for link in links
            if link.symbol and link.relevance_class == RelevanceClass.DIRECT_SYMBOL and not link.ambiguous
        }
    )
    payload = {
        "primary_source_domain": raw.source_domain,
        "primary_source_class": raw.source_class.value,
        "primary_raw_item_id": raw.raw_item_id,
        "canonical_url": raw.canonical_url,
        "normalized_text_hash": raw.normalized_text_hash,
        "source_count": source_count,
        "independent_source_count": independent_source_count,
        "freshness_score": freshness_score,
        "contradiction_score": contradiction_score,
        "novelty_score": _novelty_score(novelty),
        "trigger_eligible": bool(trigger),
        "support_points": list(support),
        "counter_points": list(counter),
        "uncertainty": list(uncertainty),
        "sources": [
            {
                "provider_id": raw.provider_id,
                "raw_item_id": raw.raw_item_id,
                "source_domain": raw.source_domain,
                "source_class": raw.source_class.value,
                "canonical_url": raw.canonical_url,
                "published_at": _iso(raw.published_at),
                "first_seen_at": _iso(raw.first_seen_at),
            }
        ],
    }
    return NewsEventSnapshot(
        event_id=event_id,
        event_version=event_version,
        available_at=now,
        event_type=event_type,
        fact_class=fact_class,
        canonical_title=canonical_title if canonical_title is not None else raw.title,
        factual_summary=factual_summary if factual_summary is not None else (raw.summary_snippet or raw.title),
        earliest_published_at=earliest_published_at or raw.published_at,
        latest_update_at=latest_update_at or raw.updated_at or raw.published_at or now,
        first_seen_at=raw.first_seen_at,
        event_status=event_status,
        primary_source_item_id=primary_source_item_id or raw.raw_item_id,
        entities=sorted({link.entity_id for link in links}),
        symbols=direct_symbols,
        sectors=sorted(
            {link.entity_id for link in links if link.relevance_class == RelevanceClass.SECTOR}
        ),
        geography=[],
        source_count=source_count,
        independent_source_count=independent_source_count,
        contradiction_state=contradiction_state,
        contradictions=list(contradictions),
        novelty_state=novelty,
        freshness_state=freshness_state,
        materiality_score=materiality,
        materiality_tier=tier,
        direction=direction,
        direction_score=direction_score,
        impact_horizon=horizon,
        confidence=round(max(0.0, min(1.0, source_profile.reliability_score)), 6),
        uncertainty_notes=list(uncertainty),
        correction_of_version=correction_of_version,
        expires_at=expires_at,
        taxonomy_version="news.taxonomy.v1",
        clustering_policy_version=CLUSTERING_POLICY_VERSION,
        materiality_policy_version=MATERIALITY_POLICY_VERSION,
        freshness_policy_version=FRESHNESS_POLICY_VERSION,
        payload=payload,
    )


_RELEVANCE_RANK = {
    RelevanceClass.DIRECT_SYMBOL: 0,
    RelevanceClass.DIRECT_PROJECT: 1,
    RelevanceClass.MARKET_STRUCTURE: 2,
    RelevanceClass.EXCHANGE: 3,
    RelevanceClass.MACRO: 4,
    RelevanceClass.PORTFOLIO: 5,
    RelevanceClass.SECTOR: 6,
    RelevanceClass.UNKNOWN: 7,
}


def _primary_relevance(links: list[EntityLink]) -> RelevanceClass:
    if not links:
        return RelevanceClass.UNKNOWN
    return min(links, key=lambda link: _RELEVANCE_RANK.get(link.relevance_class, 99)).relevance_class


def _primary_mapping_confidence(links: list[EntityLink]) -> float:
    relevance = _primary_relevance(links)
    matches = [link.confidence for link in links if link.relevance_class == relevance]
    return max(matches, default=0.0)


def _evidence_specs(links: list[EntityLink]) -> list[tuple[str, RelevanceClass, str, EntityLink]]:
    grouped: dict[tuple[str, RelevanceClass], tuple[str, EntityLink]] = {}
    for link in links:
        if (
            link.symbol
            and link.relevance_class == RelevanceClass.DIRECT_SYMBOL
            and not link.ambiguous
            and link.confidence >= 0.55
        ):
            key = (link.symbol, link.relevance_class)
        else:
            key = (BROAD_SYMBOL, link.relevance_class)
        if key not in grouped:
            grouped[key] = (link.reason or f"relevance {link.relevance_class.value}", link)
    return [
        (symbol, relevance, reason, link)
        for (symbol, relevance), (reason, link) in grouped.items()
    ]


def _novelty_score(novelty: NoveltyState) -> float:
    return {
        NoveltyState.NEW_EVENT: 1.0,
        NoveltyState.MATERIAL_UPDATE: 0.7,
        NoveltyState.CORRECTION: 0.65,
        NoveltyState.RETRACTION: 0.7,
        NoveltyState.MINOR_UPDATE: 0.25,
        NoveltyState.CORROBORATION_ONLY: 0.1,
        NoveltyState.DUPLICATE: 0.0,
        NoveltyState.STALE_DISCOVERY: 0.05,
    }.get(novelty, 0.0)


def _priority_for(tier: MaterialityTier) -> str:
    if tier == MaterialityTier.CRITICAL:
        return "URGENT"
    if tier == MaterialityTier.HIGH:
        return "HIGH"
    return "NORMAL"


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _optional_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _aware(value).isoformat()


def max_filter(*values: datetime | None) -> datetime | None:
    present = [_aware(value) for value in values if value is not None]
    return max(present) if present else None


def min_filter(*values: datetime | None) -> datetime | None:
    present = [_aware(value) for value in values if value is not None]
    return min(present) if present else None
