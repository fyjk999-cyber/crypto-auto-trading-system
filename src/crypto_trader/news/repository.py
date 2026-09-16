"""Async persistence gateway for the canonical News tables.

This module is a storage adapter only. It contains no trading, Risk or
Execution authority. All writes are idempotent under provider/item/version
uniqueness keys so a worker restart cannot create duplicate canonical rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select, update

from crypto_trader.domain.identifiers import new_id
from crypto_trader.news.models import (
    ContradictionState,
    Direction,
    EntityLink,
    EventStatus,
    EventType,
    FactClass,
    FreshnessState,
    ImpactHorizon,
    MaterialityTier,
    NewsEventSnapshot,
    NewsEvidence,
    NewsOutcomeReview,
    NewsReassessmentRequest,
    NoveltyState,
    ProviderHealth,
    ProviderState,
    RawNewsItem,
    ReassessmentStatus,
    SourceClass,
    SourceProfile,
)
from crypto_trader.persistence.models import (
    NewsDecisionRefORM,
    NewsEntityLinkORM,
    NewsEventItemORM,
    NewsEventORM,
    NewsEventVersionORM,
    NewsEvidenceORM,
    NewsOutcomeReviewORM,
    NewsProviderStateORM,
    NewsRawItemORM,
    NewsReassessmentEventORM,
    NewsSourceProfileORM,
)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    aware = _aware(value)
    return aware.isoformat() if aware is not None else None


def _enum(enum_cls, value, default):
    if value is None:
        return default
    try:
        return enum_cls(value)
    except ValueError:
        return default


class NewsRepository:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    # ------------------------------------------------------------------ raw
    async def insert_raw_item(self, item: RawNewsItem) -> bool:
        """Insert a factual raw item once. Returns True when newly created."""
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(NewsRawItemORM.raw_item_id).where(
                        NewsRawItemORM.provider_id == item.provider_id,
                        NewsRawItemORM.provider_item_id == item.provider_item_id,
                        NewsRawItemORM.source_payload_hash == item.source_payload_hash,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return False
            session.add(
                NewsRawItemORM(
                    raw_item_id=item.raw_item_id,
                    provider_id=item.provider_id,
                    provider_item_id=item.provider_item_id,
                    canonical_url=item.canonical_url,
                    source_domain=item.source_domain,
                    source_name=item.source_name,
                    source_type=item.source_type,
                    source_class=item.source_class.value,
                    title=item.title,
                    summary_snippet=item.summary_snippet,
                    raw_language=item.raw_language,
                    published_at=item.published_at,
                    provider_timestamp=item.provider_timestamp,
                    first_seen_at=item.first_seen_at,
                    ingested_at=item.ingested_at,
                    updated_at=item.updated_at,
                    author=item.author,
                    source_payload_hash=item.source_payload_hash,
                    normalized_text_hash=item.normalized_text_hash,
                    retrieval_status=item.retrieval_status,
                    parse_status=item.parse_status,
                    source_metadata_json=item.source_metadata,
                    raw_payload_json=item.raw_payload,
                    schema_version=item.schema_version,
                )
            )
            await session.commit()
            return True

    async def get_raw_item(self, raw_item_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            row = await session.get(NewsRawItemORM, raw_item_id)
            return _raw_dict(row) if row is not None else None

    async def raw_item_count(self) -> int:
        async with self.session_factory() as session:
            return int(
                (await session.execute(select(func.count()).select_from(NewsRawItemORM))).scalar()
                or 0
            )

    # ---------------------------------------------------------------- event
    async def create_event(self, snapshot: NewsEventSnapshot) -> None:
        async with self.session_factory() as session:
            session.add(_event_orm(snapshot))
            session.add(_event_version_orm(snapshot))
            await session.commit()

    async def append_event_version(self, snapshot: NewsEventSnapshot) -> None:
        async with self.session_factory() as session:
            session.add(_event_version_orm(snapshot))
            await session.execute(
                update(NewsEventORM)
                .where(NewsEventORM.event_id == snapshot.event_id)
                .values(
                    current_version=snapshot.event_version,
                    event_type=snapshot.event_type.value,
                    canonical_title=snapshot.canonical_title,
                    factual_summary=snapshot.factual_summary,
                    earliest_published_at=snapshot.earliest_published_at,
                    latest_update_at=snapshot.latest_update_at,
                    last_updated_at=snapshot.available_at,
                    event_status=snapshot.event_status.value,
                    primary_source_item_id=snapshot.primary_source_item_id,
                    source_count=snapshot.source_count,
                    independent_source_count=snapshot.independent_source_count,
                    contradiction_state=snapshot.contradiction_state.value,
                    novelty_state=snapshot.novelty_state.value,
                    freshness_state=snapshot.freshness_state.value,
                    materiality_score=snapshot.materiality_score,
                    materiality_tier=snapshot.materiality_tier.value,
                    direction=snapshot.direction.value,
                    updated_at=snapshot.available_at,
                    payload_json=snapshot.payload,
                )
            )
            await session.commit()

    async def update_event_counters(
        self,
        event_id: str,
        *,
        source_count: int,
        independent_source_count: int,
        latest_update_at: datetime,
        primary_source_item_id: str | None = None,
    ) -> None:
        async with self.session_factory() as session:
            values: dict[str, Any] = {
                "source_count": source_count,
                "independent_source_count": independent_source_count,
                "latest_update_at": latest_update_at,
                "updated_at": datetime.now(UTC),
            }
            if primary_source_item_id is not None:
                values["primary_source_item_id"] = primary_source_item_id
            await session.execute(
                update(NewsEventORM).where(NewsEventORM.event_id == event_id).values(**values)
            )
            await session.commit()

    async def get_event_snapshot(
        self, event_id: str, *, version: int | None = None, as_of: datetime | None = None
    ) -> NewsEventSnapshot | None:
        async with self.session_factory() as session:
            stmt = select(NewsEventVersionORM).where(NewsEventVersionORM.event_id == event_id)
            if version is not None:
                stmt = stmt.where(NewsEventVersionORM.event_version == version)
            if as_of is not None:
                stmt = stmt.where(NewsEventVersionORM.available_at <= as_of)
            stmt = stmt.order_by(NewsEventVersionORM.event_version.desc()).limit(1)
            row = (await session.execute(stmt)).scalars().first()
            return _snapshot_from_row(row) if row is not None else None

    async def get_current_event_snapshot(self, event_id: str) -> NewsEventSnapshot | None:
        return await self.get_event_snapshot(event_id)

    async def find_recent_event_snapshots(
        self,
        *,
        symbols: list[str] | None = None,
        entities: list[str] | None = None,
        since: datetime | None = None,
        limit: int = 80,
    ) -> list[NewsEventSnapshot]:
        symbols = [s for s in (symbols or []) if s]
        entities = [e for e in (entities or []) if e]
        async with self.session_factory() as session:
            filters = []
            if symbols:
                filters.append(NewsEntityLinkORM.symbol.in_(symbols))
            if entities:
                filters.append(NewsEntityLinkORM.entity_id.in_(entities))
            if not filters:
                return []
            stmt = select(NewsEntityLinkORM.event_id).where(
                filters[0] if len(filters) == 1 else (filters[0] | filters[1])
            )
            if since is not None:
                stmt = stmt.where(NewsEntityLinkORM.available_at >= since)
            stmt = stmt.order_by(NewsEntityLinkORM.available_at.desc()).limit(limit * 3)
            event_ids = list(dict.fromkeys((await session.execute(stmt)).scalars().all()))[:limit]
        snapshots = []
        for event_id in event_ids:
            snapshot = await self.get_current_event_snapshot(event_id)
            if snapshot is not None:
                snapshots.append(snapshot)
        return snapshots

    async def link_event_item(
        self,
        *,
        event_id: str,
        event_version: int,
        raw_item_id: str,
        relation: str,
        independent: bool,
        source_domain: str,
        created_at: datetime,
    ) -> None:
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(NewsEventItemORM.id).where(
                        NewsEventItemORM.event_id == event_id,
                        NewsEventItemORM.event_version == event_version,
                        NewsEventItemORM.raw_item_id == raw_item_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return
            session.add(
                NewsEventItemORM(
                    event_id=event_id,
                    event_version=event_version,
                    raw_item_id=raw_item_id,
                    relation=relation,
                    independent=independent,
                    source_domain=source_domain,
                    created_at=created_at,
                )
            )
            await session.commit()

    async def list_event_items(self, event_id: str, version: int | None = None) -> list[dict]:
        async with self.session_factory() as session:
            stmt = select(NewsEventItemORM).where(NewsEventItemORM.event_id == event_id)
            if version is not None:
                stmt = stmt.where(NewsEventItemORM.event_version == version)
            stmt = stmt.order_by(NewsEventItemORM.id)
            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "event_id": row.event_id,
                    "event_version": row.event_version,
                    "raw_item_id": row.raw_item_id,
                    "relation": row.relation,
                    "independent": row.independent,
                    "source_domain": row.source_domain,
                }
                for row in rows
            ]

    async def event_counts(self) -> dict[str, int]:
        async with self.session_factory() as session:
            total = int(
                (
                    await session.execute(select(func.count()).select_from(NewsEventORM))
                ).scalar()
                or 0
            )
            active = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(NewsEventORM)
                        .where(
                            NewsEventORM.event_status.in_(
                                [
                                    EventStatus.OPEN.value,
                                    EventStatus.UPDATED.value,
                                    EventStatus.RECOVERING.value,
                                ]
                            )
                        )
                    )
                ).scalar()
                or 0
            )
            material = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(NewsEventORM)
                        .where(NewsEventORM.materiality_tier.in_(["CRITICAL", "HIGH", "MEDIUM"]))
                    )
                ).scalar()
                or 0
            )
        return {"events": total, "active_events": active, "material_events": material}

    # ------------------------------------------------------------- evidence
    async def insert_entity_links(
        self,
        *,
        event_id: str,
        event_version: int,
        raw_item_id: str | None,
        links: list[EntityLink],
        available_at: datetime,
    ) -> None:
        async with self.session_factory() as session:
            for link in links:
                existing = (
                    await session.execute(
                        select(NewsEntityLinkORM.id).where(
                            NewsEntityLinkORM.event_id == event_id,
                            NewsEntityLinkORM.event_version == event_version,
                            NewsEntityLinkORM.entity_id == link.entity_id,
                            NewsEntityLinkORM.symbol == link.symbol,
                            NewsEntityLinkORM.relevance_class == link.relevance_class.value,
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    continue
                session.add(
                    NewsEntityLinkORM(
                        event_id=event_id,
                        event_version=event_version,
                        raw_item_id=raw_item_id,
                        entity_id=link.entity_id,
                        entity_type=link.entity_type,
                        symbol=link.symbol,
                        relevance_class=link.relevance_class.value,
                        confidence=link.confidence,
                        mapping_method=link.mapping_method.value,
                        ambiguous=link.ambiguous,
                        evidence_span=link.evidence_span,
                        reason=link.reason,
                        mapping_policy_version=link.mapping_policy_version,
                        available_at=available_at,
                        created_at=available_at,
                    )
                )
            await session.commit()

    async def list_entity_links(
        self, event_id: str, version: int | None = None
    ) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            stmt = select(NewsEntityLinkORM).where(NewsEntityLinkORM.event_id == event_id)
            if version is not None:
                stmt = stmt.where(NewsEntityLinkORM.event_version == version)
            stmt = stmt.order_by(NewsEntityLinkORM.id)
            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "entity_id": row.entity_id,
                    "entity_type": row.entity_type,
                    "symbol": row.symbol,
                    "relevance_class": row.relevance_class,
                    "confidence": row.confidence,
                    "mapping_method": row.mapping_method,
                    "ambiguous": row.ambiguous,
                    "reason": row.reason,
                }
                for row in rows
            ]

    async def insert_evidence(self, evidence: NewsEvidence) -> None:
        available_at = evidence.available_at or datetime.now(UTC)
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(NewsEvidenceORM.news_evidence_id).where(
                        NewsEvidenceORM.event_id == evidence.event_id,
                        NewsEvidenceORM.event_version == evidence.event_version,
                        NewsEvidenceORM.symbol == evidence.symbol,
                        NewsEvidenceORM.evidence_version == evidence.evidence_version,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return
            session.add(
                NewsEvidenceORM(
                    news_evidence_id=evidence.news_evidence_id,
                    event_id=evidence.event_id,
                    event_version=evidence.event_version,
                    evidence_version=evidence.evidence_version,
                    symbol=evidence.symbol,
                    relevance_class=evidence.relevance_class.value,
                    relevance_score=evidence.relevance_score,
                    relevance_reason=evidence.relevance_reason,
                    direction=evidence.direction.value,
                    direction_score=evidence.direction_score,
                    impact_horizon=evidence.impact_horizon.value,
                    materiality_score=evidence.materiality_score,
                    materiality_tier=evidence.materiality_tier.value,
                    novelty_state=evidence.novelty_state.value,
                    novelty_score=evidence.novelty_score,
                    source_reliability_score=evidence.source_reliability_score,
                    corroboration_score=evidence.corroboration_score,
                    freshness_score=evidence.freshness_score,
                    contradiction_score=evidence.contradiction_score,
                    contradiction_state=evidence.contradiction_state.value,
                    data_quality=evidence.data_quality,
                    factual_summary=evidence.factual_summary,
                    support_points_json=evidence.support_points,
                    counter_points_json=evidence.counter_points,
                    uncertainty_json=evidence.uncertainty,
                    source_refs_json=evidence.source_refs,
                    raw_item_refs_json=evidence.raw_item_refs,
                    trigger_eligible=evidence.trigger_eligible,
                    available_at=available_at,
                    first_seen_at=evidence.first_seen_at or available_at,
                    expires_at=evidence.expires_at,
                    source_policy_version=evidence.source_policy_version,
                    freshness_policy_version=evidence.freshness_policy_version,
                    materiality_policy_version=evidence.materiality_policy_version,
                    dedup_policy_version=evidence.dedup_policy_version,
                    created_at=available_at,
                )
            )
            await session.commit()

    async def evidence_count(self) -> int:
        async with self.session_factory() as session:
            return int(
                (await session.execute(select(func.count()).select_from(NewsEvidenceORM))).scalar()
                or 0
            )

    # ---------------------------------------------------------- provider state
    async def get_provider_state(self, provider_id: str) -> ProviderState | None:
        async with self.session_factory() as session:
            row = await session.get(NewsProviderStateORM, provider_id)
            if row is None:
                return None
            return ProviderState(
                provider_id=row.provider_id,
                cursor=row.cursor,
                last_success_at=_aware(row.last_success_at),
                last_attempt_at=_aware(row.last_attempt_at),
                last_item_at=_aware(row.last_item_at),
                consecutive_errors=row.consecutive_errors or 0,
                next_retry_at=_aware(row.next_retry_at),
                checkpoint_version=row.checkpoint_version or 1,
                status=_enum(ProviderHealth, row.status, ProviderHealth.HEALTHY),
                last_error=row.last_error,
                last_latency_ms=row.last_latency_ms,
                items_ingested=row.items_ingested or 0,
                rate_limit_state=dict(row.rate_limit_state_json or {}),
            )

    async def save_provider_state(self, state: ProviderState) -> None:
        async with self.session_factory() as session:
            row = await session.get(NewsProviderStateORM, state.provider_id)
            if row is None:
                row = NewsProviderStateORM(provider_id=state.provider_id)
                session.add(row)
            row.cursor = state.cursor
            row.last_success_at = state.last_success_at
            row.last_attempt_at = state.last_attempt_at
            row.last_item_at = state.last_item_at
            row.consecutive_errors = state.consecutive_errors
            row.next_retry_at = state.next_retry_at
            row.checkpoint_version = state.checkpoint_version
            row.status = state.status.value
            row.last_error = state.last_error
            row.last_latency_ms = state.last_latency_ms
            row.items_ingested = state.items_ingested
            row.rate_limit_state_json = state.rate_limit_state
            row.updated_at = datetime.now(UTC)
            await session.commit()

    # ------------------------------------------------------- source profiles
    async def get_source_profile(
        self, source_domain: str, source_policy_version: str
    ) -> SourceProfile | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(NewsSourceProfileORM).where(
                        NewsSourceProfileORM.source_domain == source_domain,
                        NewsSourceProfileORM.source_policy_version == source_policy_version,
                    )
                )
            ).scalar_one_or_none()
            return _profile_from_row(row) if row is not None else None

    async def upsert_source_profile(self, profile: SourceProfile) -> None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(NewsSourceProfileORM).where(
                        NewsSourceProfileORM.source_domain == profile.source_domain,
                        NewsSourceProfileORM.source_policy_version
                        == profile.source_policy_version,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = NewsSourceProfileORM(
                    source_domain=profile.source_domain,
                    source_policy_version=profile.source_policy_version,
                )
                session.add(row)
            row.source_name = profile.source_name
            row.source_class = profile.source_class.value
            row.provenance_quality = profile.provenance_quality
            row.timestamp_quality = profile.timestamp_quality
            row.correction_rate = profile.correction_rate
            row.duplicate_rate = profile.duplicate_rate
            row.corroboration_tendency = profile.corroboration_tendency
            row.machine_readability = profile.machine_readability
            row.factual_error_indicator = profile.factual_error_indicator
            row.notes = profile.notes
            row.created_at = row.created_at or datetime.now(UTC)
            await session.commit()

    # ------------------------------------------------------------- reassess
    async def request_reassessment(
        self,
        *,
        event_id: str,
        event_version: int,
        news_evidence_id: str,
        symbol: str | None,
        dedup_key: str,
        priority: str,
        materiality_tier: MaterialityTier,
        reason: str,
        requested_at: datetime,
        context: dict[str, Any] | None = None,
    ) -> NewsReassessmentRequest | None:
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(NewsReassessmentEventORM).where(
                        NewsReassessmentEventORM.dedup_key == dedup_key
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return None
            request_id = new_id("newsreq")
            session.add(
                NewsReassessmentEventORM(
                    request_id=request_id,
                    event_id=event_id,
                    event_version=event_version,
                    news_evidence_id=news_evidence_id,
                    symbol=symbol,
                    dedup_key=dedup_key,
                    status=ReassessmentStatus.PENDING.value,
                    priority=priority,
                    materiality_tier=materiality_tier.value,
                    reason=reason,
                    position_state="UNKNOWN",
                    requested_at=requested_at,
                    context_json=context or {},
                )
            )
            await session.commit()
            return NewsReassessmentRequest(
                request_id=request_id,
                event_id=event_id,
                event_version=event_version,
                news_evidence_id=news_evidence_id,
                symbol=symbol,
                dedup_key=dedup_key,
                priority=priority,
                materiality_tier=materiality_tier,
                reason=reason,
                position_state="UNKNOWN",
                requested_at=requested_at,
                context=context or {},
            )

    async def list_pending_reassessments(self, *, limit: int = 20) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            tier_rank = case(
                (NewsReassessmentEventORM.materiality_tier == MaterialityTier.CRITICAL.value, 0),
                (NewsReassessmentEventORM.materiality_tier == MaterialityTier.HIGH.value, 1),
                (NewsReassessmentEventORM.materiality_tier == MaterialityTier.MEDIUM.value, 2),
                else_=3,
            )
            rows = (
                (
                    await session.execute(
                        select(NewsReassessmentEventORM)
                        .where(NewsReassessmentEventORM.status == ReassessmentStatus.PENDING.value)
                        .order_by(tier_rank, NewsReassessmentEventORM.requested_at)
                        .limit(max(1, min(limit, 200)))
                    )
                )
                .scalars()
                .all()
            )
            return [_reassessment_dict(row) for row in rows]

    async def claim_reassessment(
        self, request_id: str, *, leg_id: str | None, state_version: str | None
    ) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(NewsReassessmentEventORM)
                .where(
                    NewsReassessmentEventORM.request_id == request_id,
                    NewsReassessmentEventORM.status == ReassessmentStatus.PENDING.value,
                )
                .values(
                    status=ReassessmentStatus.ACTIVE.value,
                    claimed_at=datetime.now(UTC),
                    leg_id=leg_id,
                    state_version=state_version,
                    attempts=NewsReassessmentEventORM.attempts + 1,
                )
            )
            await session.commit()
            return bool(result.rowcount)

    async def finish_reassessment(
        self,
        request_id: str,
        *,
        status: ReassessmentStatus,
        error: str | None = None,
    ) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(NewsReassessmentEventORM)
                .where(NewsReassessmentEventORM.request_id == request_id)
                .values(
                    status=status.value,
                    completed_at=datetime.now(UTC),
                    last_error=error[:500] if error else None,
                )
            )
            await session.commit()

    # --------------------------------------------------------- decision refs
    async def insert_decision_refs(
        self,
        *,
        decision_id: str,
        news_context: dict[str, Any],
        state_version: str | None,
        created_at: datetime,
    ) -> int:
        events = list(news_context.get("events") or [])
        as_of_raw = news_context.get("as_of")
        if isinstance(as_of_raw, str):
            try:
                as_of = datetime.fromisoformat(as_of_raw.replace("Z", "+00:00"))
            except ValueError:
                as_of = created_at
        elif isinstance(as_of_raw, datetime):
            as_of = as_of_raw
        else:
            as_of = created_at
        context_hash = str(news_context.get("context_hash") or "")
        inserted = 0
        async with self.session_factory() as session:
            for event in events:
                evidence_id = str(event.get("news_evidence_id") or event.get("id") or "")
                if not evidence_id:
                    continue
                event_id = str(event.get("event_id") or "")
                event_version = int(event.get("event_version") or 1)
                symbol = str(event.get("symbol") or "")
                ref = f"news:{evidence_id}:v{int(event.get('evidence_version') or 1)}"
                existing = (
                    await session.execute(
                        select(NewsDecisionRefORM.id).where(
                            NewsDecisionRefORM.decision_id == decision_id,
                            NewsDecisionRefORM.news_evidence_id == evidence_id,
                            NewsDecisionRefORM.event_version == event_version,
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    continue
                session.add(
                    NewsDecisionRefORM(
                        decision_id=decision_id,
                        news_evidence_id=evidence_id,
                        event_id=event_id,
                        event_version=event_version,
                        symbol=symbol,
                        ref=ref,
                        as_of=as_of,
                        state_version=state_version,
                        context_hash=context_hash,
                        created_at=created_at,
                    )
                )
                inserted += 1
            await session.commit()
        return inserted

    async def list_decision_refs(self, decision_id: str) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(NewsDecisionRefORM)
                        .where(NewsDecisionRefORM.decision_id == decision_id)
                        .order_by(NewsDecisionRefORM.id)
                    )
                )
                .scalars()
                .all()
            )
            return [
                {
                    "ref": row.ref,
                    "news_evidence_id": row.news_evidence_id,
                    "event_id": row.event_id,
                    "event_version": row.event_version,
                    "symbol": row.symbol,
                    "as_of": _iso(row.as_of),
                    "state_version": row.state_version,
                    "context_hash": row.context_hash,
                }
                for row in rows
            ]

    # -------------------------------------------------------------- outcome
    async def insert_outcome_review(self, review: NewsOutcomeReview) -> None:
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(NewsOutcomeReviewORM.review_id).where(
                        NewsOutcomeReviewORM.news_evidence_id == review.news_evidence_id,
                        NewsOutcomeReviewORM.horizon == review.horizon,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return
            session.add(
                NewsOutcomeReviewORM(
                    review_id=review.review_id,
                    news_evidence_id=review.news_evidence_id,
                    event_id=review.event_id,
                    event_version=review.event_version,
                    symbol=review.symbol,
                    horizon=review.horizon,
                    due_at=review.due_at,
                    status=review.status,
                    observed_at=review.observed_at,
                    price_return=review.price_return,
                    mfe=review.mfe,
                    mae=review.mae,
                    realized_volatility=review.realized_volatility,
                    rvol=review.rvol,
                    spread_change=review.spread_change,
                    oi_change=review.oi_change,
                    funding_change=review.funding_change,
                    llm_called=review.llm_called,
                    decision_id=review.decision_id,
                    trade_plan_id=review.trade_plan_id,
                    position_existed=review.position_existed,
                    post_cost_result=review.post_cost_result,
                    causal_claim=False,
                    counterfactual_label=review.counterfactual_label,
                    payload_json=review.payload,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def due_outcome_reviews(self, *, now: datetime, limit: int = 100) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(NewsOutcomeReviewORM)
                        .where(
                            NewsOutcomeReviewORM.status == "PENDING",
                            NewsOutcomeReviewORM.due_at <= now,
                        )
                        .order_by(NewsOutcomeReviewORM.due_at)
                        .limit(max(1, min(limit, 500)))
                    )
                )
                .scalars()
                .all()
            )
            return [_outcome_dict(row) for row in rows]

    async def update_outcome_review(
        self, review_id: str, *, status: str, payload: dict[str, Any]
    ) -> None:
        async with self.session_factory() as session:
            row = await session.get(NewsOutcomeReviewORM, review_id)
            if row is None:
                return
            row.status = status
            row.observed_at = datetime.now(UTC)
            row.updated_at = datetime.now(UTC)
            for key in (
                "price_return",
                "mfe",
                "mae",
                "realized_volatility",
                "rvol",
                "spread_change",
                "oi_change",
                "funding_change",
                "post_cost_result",
            ):
                if key in payload:
                    setattr(row, key, payload[key])
            for key in ("llm_called", "position_existed", "decision_id", "trade_plan_id"):
                if key in payload:
                    setattr(row, key, payload[key])
            row.payload_json = payload
            await session.commit()

    # ---------------------------------------------------------------- status
    async def provider_status_rows(self) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(NewsProviderStateORM))).scalars().all()
            return [
                {
                    "provider_id": row.provider_id,
                    "status": row.status,
                    "last_attempt_at": _iso(row.last_attempt_at),
                    "last_success_at": _iso(row.last_success_at),
                    "last_item_at": _iso(row.last_item_at),
                    "consecutive_errors": row.consecutive_errors,
                    "next_retry_at": _iso(row.next_retry_at),
                    "last_error": row.last_error,
                    "items_ingested": row.items_ingested,
                    "cursor": row.cursor,
                }
                for row in rows
            ]

    async def reassessment_counts(self) -> dict[str, int]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        NewsReassessmentEventORM.status,
                        func.count(),
                    ).group_by(NewsReassessmentEventORM.status)
                )
            ).all()
            out = {str(status): int(count) for status, count in rows}
            out.setdefault("total", sum(out.values()))
            return out


    async def event_snapshot_for_url(self, canonical_url: str | None) -> NewsEventSnapshot | None:
        if not canonical_url:
            return None
        async with self.session_factory() as session:
            raw_ids = (
                (
                    await session.execute(
                        select(NewsRawItemORM.raw_item_id).where(
                            NewsRawItemORM.canonical_url == canonical_url
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not raw_ids:
                return None
            event_id = (
                await session.execute(
                    select(NewsEventItemORM.event_id)
                    .where(NewsEventItemORM.raw_item_id.in_(raw_ids))
                    .order_by(NewsEventItemORM.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if event_id is None:
            return None
        return await self.get_current_event_snapshot(event_id)


# ---------------------------------------------------------------------------
# row -> domain helpers
# ---------------------------------------------------------------------------


def _raw_dict(row: NewsRawItemORM) -> dict[str, Any]:
    return {
        "raw_item_id": row.raw_item_id,
        "provider_id": row.provider_id,
        "provider_item_id": row.provider_item_id,
        "canonical_url": row.canonical_url,
        "source_domain": row.source_domain,
        "source_name": row.source_name,
        "source_type": row.source_type,
        "source_class": row.source_class,
        "title": row.title,
        "summary_snippet": row.summary_snippet,
        "raw_language": row.raw_language,
        "published_at": _iso(row.published_at),
        "provider_timestamp": _iso(row.provider_timestamp),
        "first_seen_at": _iso(row.first_seen_at),
        "ingested_at": _iso(row.ingested_at),
        "updated_at": _iso(row.updated_at),
        "author": row.author,
        "source_payload_hash": row.source_payload_hash,
        "normalized_text_hash": row.normalized_text_hash,
        "retrieval_status": row.retrieval_status,
        "parse_status": row.parse_status,
        "schema_version": row.schema_version,
    }


def _event_orm(snapshot: NewsEventSnapshot) -> NewsEventORM:
    return NewsEventORM(
        event_id=snapshot.event_id,
        current_version=snapshot.event_version,
        event_type=snapshot.event_type.value,
        canonical_title=snapshot.canonical_title,
        factual_summary=snapshot.factual_summary,
        earliest_published_at=snapshot.earliest_published_at,
        latest_update_at=snapshot.latest_update_at,
        first_seen_at=snapshot.first_seen_at,
        last_updated_at=snapshot.available_at,
        event_status=snapshot.event_status.value,
        primary_source_item_id=snapshot.primary_source_item_id,
        source_count=snapshot.source_count,
        independent_source_count=snapshot.independent_source_count,
        contradiction_state=snapshot.contradiction_state.value,
        novelty_state=snapshot.novelty_state.value,
        freshness_state=snapshot.freshness_state.value,
        materiality_score=snapshot.materiality_score,
        materiality_tier=snapshot.materiality_tier.value,
        direction=snapshot.direction.value,
        created_at=snapshot.available_at,
        updated_at=snapshot.available_at,
        payload_json=snapshot.payload,
    )


def _event_version_orm(snapshot: NewsEventSnapshot) -> NewsEventVersionORM:
    return NewsEventVersionORM(
        event_id=snapshot.event_id,
        event_version=snapshot.event_version,
        available_at=snapshot.available_at,
        event_type=snapshot.event_type.value,
        fact_class=snapshot.fact_class.value,
        canonical_title=snapshot.canonical_title,
        factual_summary=snapshot.factual_summary,
        earliest_published_at=snapshot.earliest_published_at,
        latest_update_at=snapshot.latest_update_at,
        first_seen_at=snapshot.first_seen_at,
        event_status=snapshot.event_status.value,
        primary_source_item_id=snapshot.primary_source_item_id,
        entities_json=snapshot.entities,
        symbols_json=snapshot.symbols,
        sectors_json=snapshot.sectors,
        geography_json=snapshot.geography,
        source_count=snapshot.source_count,
        independent_source_count=snapshot.independent_source_count,
        contradiction_state=snapshot.contradiction_state.value,
        contradictions_json=snapshot.contradictions,
        novelty_state=snapshot.novelty_state.value,
        freshness_state=snapshot.freshness_state.value,
        materiality_score=snapshot.materiality_score,
        materiality_tier=snapshot.materiality_tier.value,
        direction=snapshot.direction.value,
        direction_score=snapshot.direction_score,
        impact_horizon=snapshot.impact_horizon.value,
        confidence=snapshot.confidence,
        uncertainty_notes=snapshot.uncertainty_notes,
        correction_of_version=snapshot.correction_of_version,
        expires_at=snapshot.expires_at,
        taxonomy_version=snapshot.taxonomy_version,
        clustering_policy_version=snapshot.clustering_policy_version,
        materiality_policy_version=snapshot.materiality_policy_version,
        freshness_policy_version=snapshot.freshness_policy_version,
        payload_json=snapshot.payload,
        created_at=snapshot.available_at,
    )


def _snapshot_from_row(row: NewsEventVersionORM) -> NewsEventSnapshot:
    return NewsEventSnapshot(
        event_id=row.event_id,
        event_version=row.event_version,
        available_at=_aware(row.available_at) or datetime.now(UTC),
        event_type=_enum(EventType, row.event_type, EventType.UNKNOWN),
        fact_class=_enum(FactClass, row.fact_class, FactClass.SOURCE_CLAIM),
        canonical_title=row.canonical_title,
        factual_summary=row.factual_summary,
        earliest_published_at=_aware(row.earliest_published_at),
        latest_update_at=_aware(row.latest_update_at),
        first_seen_at=_aware(row.first_seen_at) or datetime.now(UTC),
        event_status=_enum(EventStatus, row.event_status, EventStatus.OPEN),
        primary_source_item_id=row.primary_source_item_id,
        entities=list(row.entities_json or []),
        symbols=list(row.symbols_json or []),
        sectors=list(row.sectors_json or []),
        geography=list(row.geography_json or []),
        source_count=row.source_count or 0,
        independent_source_count=row.independent_source_count or 0,
        contradiction_state=_enum(
            ContradictionState, row.contradiction_state, ContradictionState.NONE
        ),
        contradictions=list(row.contradictions_json or []),
        novelty_state=_enum(NoveltyState, row.novelty_state, NoveltyState.NEW_EVENT),
        freshness_state=_enum(FreshnessState, row.freshness_state, FreshnessState.FRESH),
        materiality_score=row.materiality_score or 0.0,
        materiality_tier=_enum(
            MaterialityTier, row.materiality_tier, MaterialityTier.NOISE
        ),
        direction=_enum(Direction, row.direction, Direction.UNKNOWN),
        direction_score=row.direction_score or 0.0,
        impact_horizon=_enum(ImpactHorizon, row.impact_horizon, ImpactHorizon.UNKNOWN),
        confidence=row.confidence or 0.0,
        uncertainty_notes=list(row.uncertainty_notes or []),
        correction_of_version=row.correction_of_version,
        expires_at=_aware(row.expires_at),
        taxonomy_version=row.taxonomy_version,
        clustering_policy_version=row.clustering_policy_version,
        materiality_policy_version=row.materiality_policy_version,
        freshness_policy_version=row.freshness_policy_version,
        payload=dict(row.payload_json or {}),
    )


def _profile_from_row(row: NewsSourceProfileORM) -> SourceProfile:
    return SourceProfile(
        source_domain=row.source_domain,
        source_name=row.source_name,
        source_class=_enum(SourceClass, row.source_class, SourceClass.UNKNOWN),
        source_policy_version=row.source_policy_version,
        provenance_quality=row.provenance_quality,
        timestamp_quality=row.timestamp_quality,
        correction_rate=row.correction_rate,
        duplicate_rate=row.duplicate_rate,
        corroboration_tendency=row.corroboration_tendency,
        machine_readability=row.machine_readability,
        factual_error_indicator=row.factual_error_indicator,
        notes=row.notes,
    )


def _reassessment_dict(row: NewsReassessmentEventORM) -> dict[str, Any]:
    return {
        "request_id": row.request_id,
        "event_id": row.event_id,
        "event_version": row.event_version,
        "news_evidence_id": row.news_evidence_id,
        "symbol": row.symbol,
        "dedup_key": row.dedup_key,
        "status": row.status,
        "priority": row.priority,
        "materiality_tier": row.materiality_tier,
        "reason": row.reason,
        "position_state": row.position_state,
        "leg_id": row.leg_id,
        "state_version": row.state_version,
        "requested_at": _iso(row.requested_at),
        "claimed_at": _iso(row.claimed_at),
        "completed_at": _iso(row.completed_at),
        "attempts": row.attempts,
        "last_error": row.last_error,
        "context": dict(row.context_json or {}),
    }


def _outcome_dict(row: NewsOutcomeReviewORM) -> dict[str, Any]:
    return {
        "review_id": row.review_id,
        "news_evidence_id": row.news_evidence_id,
        "event_id": row.event_id,
        "event_version": row.event_version,
        "symbol": row.symbol,
        "horizon": row.horizon,
        "due_at": _iso(row.due_at),
        "status": row.status,
        "observed_at": _iso(row.observed_at),
        "price_return": row.price_return,
        "mfe": row.mfe,
        "mae": row.mae,
        "realized_volatility": row.realized_volatility,
        "rvol": row.rvol,
        "spread_change": row.spread_change,
        "oi_change": row.oi_change,
        "funding_change": row.funding_change,
        "llm_called": row.llm_called,
        "decision_id": row.decision_id,
        "position_existed": row.position_existed,
        "post_cost_result": row.post_cost_result,
        "counterfactual_label": row.counterfactual_label,
    }
