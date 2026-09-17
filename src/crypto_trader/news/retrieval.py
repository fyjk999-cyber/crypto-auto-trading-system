# ruff: noqa: E501
"""Canonical persistent as-of News evidence retrieval.

The SQL tables are the only truth. No vector index is required or trusted.
A zero-hit result is valid and is explicitly represented as unavailable News
rather than invented context.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select

from crypto_trader.news.config import NewsConfig
from crypto_trader.news.models import (
    BROAD_SYMBOL,
    AggregateHealth,
    NewsEventSnapshot,
    ProviderHealth,
    RelevanceClass,
)
from crypto_trader.persistence.models import (
    NewsEventVersionORM,
    NewsEvidenceORM,
    NewsProviderStateORM,
)


class NewsRetriever:
    def __init__(
        self,
        session_factory,
        *,
        top_k: int = 8,
        token_budget: int = 1400,
        include_broad: bool = True,
    ) -> None:
        self.session_factory = session_factory
        self.top_k = max(1, top_k)
        self.token_budget = max(100, token_budget)
        self.include_broad = include_broad

    @classmethod
    def from_config(cls, session_factory, config: NewsConfig) -> NewsRetriever:
        return cls(
            session_factory,
            top_k=config.context_top_k,
            token_budget=config.context_token_budget,
            include_broad=config.context_include_broad,
        )

    async def get_news_context(
        self,
        symbol: str,
        as_of: datetime | None = None,
        position_state: dict | None = None,
        max_items: int | None = None,
        token_budget: int | None = None,
    ) -> dict:
        moment = _aware(as_of or datetime.now(UTC))
        limit = max(1, int(max_items or self.top_k))
        budget = max(100, int(token_budget or self.token_budget))
        async with self.session_factory() as session:
            filters = [
                NewsEvidenceORM.available_at <= moment,
                NewsEvidenceORM.first_seen_at <= moment,
            ]
            symbol_filter = NewsEvidenceORM.symbol == symbol
            if self.include_broad:
                symbol_filter = symbol_filter | (NewsEvidenceORM.symbol == BROAD_SYMBOL)
            filters.append(symbol_filter)
            filters.append(
                (NewsEvidenceORM.expires_at.is_(None)) | (NewsEvidenceORM.expires_at > moment)
            )
            evidence_rows = (
                (
                    await session.execute(
                        select(NewsEvidenceORM)
                        .where(*filters)
                        .order_by(
                            NewsEvidenceORM.materiality_score.desc(),
                            NewsEvidenceORM.available_at.desc(),
                        )
                        .limit(limit * 8)
                    )
                )
                .scalars()
                .all()
            )
            event_rows: dict[tuple[str, int], NewsEventVersionORM] = {}
            for row in evidence_rows:
                key = (row.event_id, row.event_version)
                if key in event_rows:
                    continue
                version_row = (
                    await session.execute(
                        select(NewsEventVersionORM)
                        .where(
                            NewsEventVersionORM.event_id == row.event_id,
                            NewsEventVersionORM.event_version == row.event_version,
                            NewsEventVersionORM.available_at <= moment,
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if version_row is not None:
                    event_rows[key] = version_row
        events: list[dict] = []
        for row in evidence_rows:
            version_row = event_rows.get((row.event_id, row.event_version))
            if version_row is None:
                continue
            relevance = _enum(RelevanceClass, row.relevance_class, RelevanceClass.UNKNOWN)
            score = _retrieval_score(row, relevance, position_state)
            snapshot = _snapshot_from_version(version_row)
            events.append(_context_item(row, snapshot, relevance, score))
        events.sort(key=lambda item: item["retrieval_score"], reverse=True)
        selected: list[dict] = []
        tokens = 0
        for event in events:
            estimate = _estimate_tokens(event)
            if selected and tokens + estimate > budget:
                continue
            if not selected and estimate > budget:
                event["factual_summary"] = event["factual_summary"][:200]
                estimate = _estimate_tokens(event)
            selected.append(event)
            tokens += estimate
            if len(selected) >= limit:
                break
        context_hash = hashlib.sha256(
            json.dumps(
                {
                    "symbol": symbol,
                    "as_of": moment.isoformat(),
                    "events": [
                        {
                            "news_evidence_id": item["news_evidence_id"],
                            "event_id": item["event_id"],
                            "event_version": item["event_version"],
                            "evidence_version": item["evidence_version"],
                        }
                        for item in selected
                    ],
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        health = await self._health()
        return {
            "as_of": moment.isoformat(),
            "symbol": symbol,
            "health": health.value,
            "unavailable": not selected,
            "bounded": True,
            "top_k": limit,
            "token_budget": budget,
            "token_estimate": tokens,
            "events": selected,
            "news_evidence_refs": [
                f"news:{item['news_evidence_id']}:v{item['evidence_version']}" for item in selected
            ],
            "context_hash": context_hash,
            "authority": "EVIDENCE_ONLY",
            "is_order": False,
        }

    async def _health(self) -> AggregateHealth:
        async with self.session_factory() as session:
            rows = (
                await session.execute(select(NewsProviderStateORM.status, NewsProviderStateORM.consecutive_errors))
            ).all()
        if not rows:
            return AggregateHealth.NO_NEWS_AVAILABLE
        statuses = [str(status or "") for status, _errors in rows]
        healthy = [status for status in statuses if status == ProviderHealth.HEALTHY.value]
        if healthy and len(healthy) == len(statuses):
            return AggregateHealth.HEALTHY
        if healthy:
            return AggregateHealth.PARTIAL_NEWS_AVAILABLE
        return AggregateHealth.NO_NEWS_AVAILABLE


def _context_item(row: NewsEvidenceORM, snapshot: NewsEventSnapshot, relevance: RelevanceClass, score: float) -> dict:
    summary = (row.factual_summary or snapshot.factual_summary or "")[:800]
    return {
        "news_evidence_id": row.news_evidence_id,
        "event_id": row.event_id,
        "event_version": row.event_version,
        "evidence_version": row.evidence_version,
        "symbol": row.symbol,
        "event_type": snapshot.event_type.value,
        "fact_class": snapshot.fact_class.value,
        "materiality": row.materiality_tier,
        "materiality_score": row.materiality_score,
        "novelty": row.novelty_state,
        "direction": row.direction,
        "direction_score": row.direction_score,
        "impact_horizon": row.impact_horizon,
        "relevance": relevance.value,
        "relevance_reason": row.relevance_reason,
        "freshness": row.freshness_score,
        "freshness_state": snapshot.freshness_state.value,
        "source_reliability": row.source_reliability_score,
        "corroboration": row.corroboration_score,
        "contradiction": row.contradiction_state,
        "contradiction_score": row.contradiction_score,
        "data_quality": row.data_quality,
        "factual_summary": summary,
        "support_points": list(row.support_points_json or []),
        "counter_points": list(row.counter_points_json or []),
        "uncertainty": list(row.uncertainty_json or []),
        "source_refs": list(row.source_refs_json or []),
        "raw_item_refs": list(row.raw_item_refs_json or []),
        "trigger_eligible": bool(row.trigger_eligible),
        "expires_at": _iso(row.expires_at),
        "available_at": _iso(row.available_at),
        "as_of": _iso(row.available_at),
        "retrieval_score": round(score, 6),
    }


def _retrieval_score(row: NewsEvidenceORM, relevance: RelevanceClass, position_state: dict | None) -> float:
    direct = 1.0 if row.symbol not in {"", BROAD_SYMBOL} else 0.35
    open_position_bonus = 0.0
    if position_state:
        symbol = str(position_state.get("symbol") or "")
        if symbol and row.symbol == symbol:
            open_position_bonus = 0.10
    novelty = _novelty_number(row.novelty_state)
    contradiction_importance = min(0.10, max(0.0, row.contradiction_score) * 0.10)
    relevance_weight = {
        RelevanceClass.DIRECT_SYMBOL: 1.0,
        RelevanceClass.DIRECT_PROJECT: 0.85,
        RelevanceClass.EXCHANGE: 0.65,
        RelevanceClass.MARKET_STRUCTURE: 0.75,
        RelevanceClass.MACRO: 0.70,
        RelevanceClass.SECTOR: 0.45,
        RelevanceClass.PORTFOLIO: 0.60,
        RelevanceClass.UNKNOWN: 0.1,
    }.get(relevance, 0.1)
    return min(
        1.0,
        0.28 * row.materiality_score
        + 0.16 * float(row.freshness_score)
        + 0.14 * novelty
        + 0.12 * relevance_weight
        + 0.10 * float(row.source_reliability_score)
        + 0.08 * float(row.corroboration_score)
        + 0.06 * direct
        + 0.04 * (1.0 - min(1.0, float(row.contradiction_score)))
        + 0.02 * contradiction_importance
        + open_position_bonus,
    )


def _snapshot_from_version(row: NewsEventVersionORM) -> NewsEventSnapshot:
    # Lightweight snapshot decoder for retrieval; import-local to avoid a heavy
    # dependency cross-import.
    import json as _json

    payload = dict(row.payload_json or {})
    if not payload:
        payload = _json.loads(row.payload_json or "{}") if isinstance(row.payload_json, str) else {}
    from crypto_trader.news.models import (
        ContradictionState,
        Direction,
        EventStatus,
        EventType,
        FactClass,
        FreshnessState,
        ImpactHorizon,
        MaterialityTier,
        NoveltyState,
    )

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
        source_count=row.source_count or 0,
        independent_source_count=row.independent_source_count or 0,
        contradiction_state=_enum(ContradictionState, row.contradiction_state, ContradictionState.NONE),
        novelty_state=_enum(NoveltyState, row.novelty_state, NoveltyState.NEW_EVENT),
        freshness_state=_enum(FreshnessState, row.freshness_state, FreshnessState.FRESH),
        materiality_score=row.materiality_score or 0.0,
        materiality_tier=_enum(MaterialityTier, row.materiality_tier, MaterialityTier.NOISE),
        direction=_enum(Direction, row.direction, Direction.UNKNOWN),
        direction_score=row.direction_score or 0.0,
        impact_horizon=_enum(ImpactHorizon, row.impact_horizon, ImpactHorizon.UNKNOWN),
        confidence=row.confidence or 0.0,
        uncertainty_notes=list(row.uncertainty_notes or []),
        payload=payload,
    )


def _estimate_tokens(event: dict) -> int:
    return max(40, len(json.dumps(event, default=str)) // 4)


def _novelty_number(value: str) -> float:
    return {
        "NEW_EVENT": 1.0,
        "MATERIAL_UPDATE": 0.7,
        "CORRECTION": 0.65,
        "RETRACTION": 0.7,
        "MINOR_UPDATE": 0.25,
        "CORROBORATION_ONLY": 0.10,
        "DUPLICATE": 0.0,
        "STALE_DISCOVERY": 0.05,
    }.get(str(value), 0.0)


def _enum(enum_cls, value, default):
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return default


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    aware = _aware(value)
    return aware.isoformat() if aware is not None else None
