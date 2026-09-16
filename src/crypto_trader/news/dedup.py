# ruff: noqa: E501
"""Layered duplicate / syndication / corroboration classifier.

The critical rule is enforced here: twenty copies of one article are not
twenty independent confirmations.
"""

from __future__ import annotations

from datetime import UTC, timedelta

from crypto_trader.news.models import (
    DuplicateRelation,
    NewsEventSnapshot,
    RawNewsItem,
    SourceClass,
)
from crypto_trader.news.normalization import (
    contains_source_attribution,
    jaccard,
    title_similarity,
    token_set,
)


def classify_duplicate(
    new_item: RawNewsItem,
    candidate: NewsEventSnapshot,
    *,
    overlap_seconds: int = 12 * 3600,
    near_title_threshold: float = 0.86,
    syndication_title_threshold: float = 0.78,
) -> DuplicateRelation:
    candidate_primary_domain = str(candidate.payload.get("primary_source_domain") or "")
    candidate_title = candidate.canonical_title
    new_text = f"{new_item.title} {new_item.summary_snippet}"
    similarity = title_similarity(new_item.title, candidate_title)
    entity_overlap = _entity_overlap(new_item, candidate)
    close_in_time = _close_in_time(new_item, candidate, overlap_seconds)

    if new_item.canonical_url and candidate.payload.get("canonical_url"):
        if new_item.canonical_url == candidate.payload.get("canonical_url"):
            return DuplicateRelation.EXACT_DUPLICATE
    if new_item.normalized_text_hash == candidate.payload.get("normalized_text_hash"):
        return DuplicateRelation.EXACT_DUPLICATE

    if not close_in_time and similarity < near_title_threshold:
        return DuplicateRelation.RELATED_DISTINCT_EVENT

    if candidate_primary_domain and new_item.source_domain != candidate_primary_domain:
        if contains_source_attribution(new_text, candidate_primary_domain):
            return DuplicateRelation.SYNDICATED_COPY
        if candidate.source_count > 0 and _is_media(new_item.source_class) and similarity >= 0.65:
            return DuplicateRelation.SYNDICATED_COPY

    if similarity >= 0.97 and entity_overlap >= 0.5:
        if new_item.source_domain == candidate_primary_domain:
            return DuplicateRelation.SOURCE_UPDATE
        return DuplicateRelation.NEAR_DUPLICATE

    if similarity >= syndication_title_threshold and _is_media(new_item.source_class):
        return DuplicateRelation.SYNDICATED_COPY

    if (
        candidate_primary_domain
        and new_item.source_domain != candidate_primary_domain
        and not _is_media(new_item.source_class)
        and not _is_media(candidate_primary_class(candidate))
        and similarity < syndication_title_threshold
        and entity_overlap > 0
    ):
        return DuplicateRelation.INDEPENDENT_CORROBORATION

    if (
        new_item.source_domain != candidate_primary_domain
        and not _is_media(new_item.source_class)
        and not _is_media(candidate_primary_class(candidate))
        and 0.40 <= similarity < syndication_title_threshold
    ):
        return DuplicateRelation.INDEPENDENT_CORROBORATION

    if entity_overlap > 0 and similarity >= 0.40:
        return DuplicateRelation.SOURCE_UPDATE

    return DuplicateRelation.RELATED_DISTINCT_EVENT


def candidate_primary_class(candidate: NewsEventSnapshot) -> SourceClass:
    raw = str(candidate.payload.get("primary_source_class") or "UNKNOWN")
    try:
        return SourceClass(raw)
    except ValueError:
        return SourceClass.UNKNOWN


def _is_media(source_class: SourceClass) -> bool:
    return source_class in {
        SourceClass.ESTABLISHED_NEWS,
        SourceClass.SECONDARY_MEDIA,
        SourceClass.SOCIAL_UNVERIFIED,
        SourceClass.UNKNOWN,
    }


def _is_official(source_class: SourceClass) -> bool:
    return source_class in {
        SourceClass.PRIMARY_OFFICIAL,
        SourceClass.REGULATORY_OFFICIAL,
        SourceClass.EXCHANGE_OFFICIAL,
        SourceClass.PROJECT_OFFICIAL,
        SourceClass.STRUCTURED_DATA_PROVIDER,
    }


def _entity_overlap(new_item: RawNewsItem, candidate: NewsEventSnapshot) -> float:
    # Raw items do not carry canonical links here; likely symbols in text are a
    # safe conservative proxy for the classifier only.
    text_tokens = token_set(f"{new_item.title} {new_item.summary_snippet}")
    candidate_tokens = token_set(
        " ".join([candidate.canonical_title, candidate.factual_summary, " ".join(candidate.symbols or [])])
    )
    return jaccard(text_tokens, candidate_tokens)


def _close_in_time(
    new_item: RawNewsItem, candidate: NewsEventSnapshot, overlap_seconds: int
) -> bool:
    new_at = new_item.published_at or new_item.first_seen_at
    candidate_at = candidate.latest_update_at or candidate.earliest_published_at or candidate.first_seen_at
    if new_at is None or candidate_at is None:
        return True
    if new_at.tzinfo is None:
        new_at = new_at.replace(tzinfo=UTC)
    if candidate_at.tzinfo is None:
        candidate_at = candidate_at.replace(tzinfo=UTC)
    return abs(new_at - candidate_at) <= timedelta(seconds=overlap_seconds)
