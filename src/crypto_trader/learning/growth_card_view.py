"""Read-only mapping between the canonical card ORM row / snapshot and domain."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from crypto_trader.learning.growth_v2_contracts import (
    STATUS_CANDIDATE,
    AdaptiveExperienceCard,
    ContextSignature,
    TriggerSignature,
)


def row_to_card(row) -> AdaptiveExperienceCard:
    return AdaptiveExperienceCard(
        rule_id=row.rule_id,
        title=row.title,
        content=row.content,
        experience_type=row.experience_type or "COMPRESSED_EXPERIENCE",
        account_id=row.account_id or "default",
        mode=row.mode or "PAPER",
        trigger=TriggerSignature.from_json(row.trigger_signature_json),
        context=ContextSignature.from_json(row.context_signature_json),
        share_scope=row.share_scope or "UNKNOWN",
        scope=dict(row.applicability_scope_json or {}),
        guidance=dict(row.guidance_json or {}),
        factor_refs=list(row.factor_refs_json or []),
        source_episode_ids=list(row.source_episode_ids_json or []),
        supporting_episode_ids=list(row.supporting_episode_ids_json or []),
        contradicting_episode_ids=list(row.contradicting_episode_ids_json or []),
        sample_count=int(row.source_episode_count or 0),
        support_count=int(row.support_count or 0),
        contradiction_count=int(row.contradiction_count or 0),
        confidence=row.confidence or Decimal("0"),
        quality_score=row.quality_score or Decimal("0"),
        decay_score=row.decay_score or Decimal("0"),
        status=row.status or STATUS_CANDIDATE,
        version=int(row.version or 1),
        last_validated_at=row.last_validated_at,
        updated_at=row.updated_at,
        known_at=row.known_at or row.created_at,
        supersedes_rule_id=row.supersedes_rule_id,
        supersedes_version=row.supersedes_version,
        update_reason=row.update_reason,
    )


def card_from_snapshot(snapshot: dict[str, Any]) -> AdaptiveExperienceCard:
    """Rebuild the card view as it existed at a journal version."""
    return AdaptiveExperienceCard(
        rule_id=str(snapshot.get("rule_id", "")),
        title=str(snapshot.get("title", "")),
        content=str(snapshot.get("content", "")),
        experience_type=str(snapshot.get("experience_type") or "ADAPTIVE_CARD"),
        account_id=str(snapshot.get("account_id") or "default"),
        mode=str(snapshot.get("mode") or "PAPER"),
        trigger=TriggerSignature.from_json(snapshot.get("trigger_signature_json")),
        context=ContextSignature.from_json(snapshot.get("context_signature_json")),
        share_scope=str(snapshot.get("share_scope") or "UNKNOWN"),
        scope=dict(snapshot.get("applicability_scope_json") or {}),
        guidance=dict(snapshot.get("guidance_json") or {}),
        factor_refs=list(snapshot.get("factor_refs_json") or []),
        source_episode_ids=list(snapshot.get("source_episode_ids_json") or []),
        supporting_episode_ids=list(snapshot.get("supporting_episode_ids_json") or []),
        contradicting_episode_ids=list(
            snapshot.get("contradicting_episode_ids_json") or []
        ),
        sample_count=int(snapshot.get("sample_count", 0) or 0),
        support_count=int(snapshot.get("support_count", 0) or 0),
        contradiction_count=int(snapshot.get("contradiction_count", 0) or 0),
        confidence=Decimal(str(snapshot.get("confidence", "0") or "0")),
        quality_score=Decimal(str(snapshot.get("quality_score", "0") or "0")),
        decay_score=Decimal(str(snapshot.get("decay_score", "0") or "0")),
        status=str(snapshot.get("status") or STATUS_CANDIDATE),
        version=int(snapshot.get("version", 1) or 1),
        last_validated_at=_parse_dt(snapshot.get("last_validated_at")),
        updated_at=_parse_dt(snapshot.get("updated_at")),
        known_at=_parse_dt(snapshot.get("known_at")),
        update_reason=snapshot.get("update_reason"),
    )


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None
