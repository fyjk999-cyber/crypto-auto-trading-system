"""G09/G12: canonical Adaptive Experience Card store and evolution operations.

Canonical current state: ``ai_compressed_experience`` (extended in place).
History journal: ``growth_card_versions`` (append-only, one snapshot per
operation).  This module is the only write path for cards; runtime retrieval
must never import it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select

from crypto_trader.learning.growth_card_view import row_to_card
from crypto_trader.learning.growth_contracts import canonical_json, sha256_text
from crypto_trader.learning.growth_models import GrowthCardVersionORM, utcnow
from crypto_trader.learning.growth_v2_contracts import (
    CARD_OPERATIONS,
    OP_CREATE,
    OP_KEEP,
    OP_MERGE,
    OP_RETIRE,
    OP_SPLIT,
    OP_UPDATE,
    OP_WATCH,
    STATUS_ACTIVE,
    STATUS_CANDIDATE,
    STATUS_RETIRED,
    STATUS_WATCH,
    UNKNOWN,
    CardUpdateProposal,
    ContextSignature,
    TriggerSignature,
    context_payload_equal,
    guidance_compatible,
    trigger_payload_equal,
)
from crypto_trader.persistence.models import AICompressedExperienceORM

Fence = Callable[[], Awaitable[bool]]


@dataclass
class CardMutationResult:
    rule_id: str
    version: int
    operation: str
    status: str
    idempotent: bool = False
    created_rule_ids: list[str] = field(default_factory=list)
    retired_rule_ids: list[str] = field(default_factory=list)
    reason: str = ""


class ClaimLostError(RuntimeError):
    pass


def card_rule_id(
    *,
    experience_type: str,
    trigger: TriggerSignature | None,
    context: ContextSignature | None,
    guidance: dict[str, Any],
) -> str:
    payload = {
        "experience_type": experience_type,
        "trigger": trigger.to_json() if trigger else None,
        "context": context.to_json() if context else None,
        "guidance": guidance,
    }
    return f"card_{sha256_text(canonical_json(payload))[:40]}"


def _snapshot(card_values: dict[str, Any]) -> dict[str, Any]:
    return dict(card_values)


class AdaptiveCardStore:
    """Write-side store; only Daily Review / low-frequency learners may call it."""

    def __init__(self, session_factory, *, min_samples_for_active: int = 3) -> None:
        self.session_factory = session_factory
        self.min_samples_for_active = max(1, min_samples_for_active)

    # ------------------------------------------------------------------
    async def get_card(self, rule_id: str):
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(AICompressedExperienceORM).where(
                        AICompressedExperienceORM.rule_id == rule_id
                    )
                )
            ).scalar_one_or_none()
            return row_to_card(row) if row is not None else None

    async def history(self, rule_id: str) -> list[GrowthCardVersionORM]:
        async with self.session_factory() as session:
            return list(
                (
                    await session.execute(
                        select(GrowthCardVersionORM)
                        .where(GrowthCardVersionORM.card_rule_id == rule_id)
                        .order_by(
                            GrowthCardVersionORM.version.asc(),
                            GrowthCardVersionORM.created_at.asc(),
                        )
                    )
                )
                .scalars()
                .all()
            )

    async def _journal_exists(self, proposal_hash: str) -> bool:
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(GrowthCardVersionORM.id).where(
                        GrowthCardVersionORM.proposal_hash == proposal_hash
                    )
                )
            ).first() is not None

    async def _journal_exists_result(self, proposal_hash: str) -> CardMutationResult | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(GrowthCardVersionORM).where(
                        GrowthCardVersionORM.proposal_hash == proposal_hash
                    )
                )
            ).scalar_one_or_none()
        if row is None:
            return None
        return CardMutationResult(
            rule_id=row.card_rule_id,
            version=row.version,
            operation=row.operation,
            status=row.status or STATUS_CANDIDATE,
            idempotent=True,
            reason="DUPLICATE_PROPOSAL_HASH",
        )

    # ------------------------------------------------------------------
    async def apply(
        self,
        proposal: CardUpdateProposal,
        *,
        fence: Fence | None = None,
        now: datetime | None = None,
    ) -> CardMutationResult:
        effective_now = now or utcnow()
        if proposal.operation not in CARD_OPERATIONS:
            raise ValueError(f"unsupported card operation: {proposal.operation}")
        proposal.finalize()
        existing = await self._journal_exists_result(proposal.proposal_hash)
        if existing is not None:
            return existing
        if fence is not None and not await fence():
            raise ClaimLostError("claim lost before card mutation")

        if proposal.operation == OP_CREATE:
            return await self._create(proposal, now=effective_now)
        if proposal.operation == OP_UPDATE:
            return await self._update(proposal, now=effective_now)
        if proposal.operation == OP_KEEP:
            return await self._keep(proposal, now=effective_now)
        if proposal.operation in {OP_WATCH, OP_RETIRE}:
            return await self._status_change(proposal, now=effective_now)
        if proposal.operation == OP_SPLIT:
            return await self._split(proposal, now=effective_now)
        if proposal.operation == OP_MERGE:
            return await self._merge(proposal, now=effective_now)
        raise ValueError(f"unhandled card operation: {proposal.operation}")

    # ------------------------------------------------------------------
    async def _create(
        self, proposal: CardUpdateProposal, *, now: datetime
    ) -> CardMutationResult:
        trigger = TriggerSignature.from_json(proposal.proposed_trigger)
        context = ContextSignature.from_json(proposal.proposed_context)
        guidance = dict(proposal.proposed_guidance or {})
        rule_id = proposal.card_rule_id or card_rule_id(
            experience_type="ADAPTIVE_CARD",
            trigger=trigger,
            context=context,
            guidance=guidance,
        )
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(AICompressedExperienceORM).where(
                        AICompressedExperienceORM.rule_id == rule_id
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                # Same identity already exists: never create a duplicate card.
                proposal.operation = OP_UPDATE
                proposal.proposed_status = proposal.proposed_status or existing.status
                await session.rollback()
                return await self._update(proposal)
            source_ids = sorted(set(proposal.source_episode_ids))
            row = AICompressedExperienceORM(
                rule_id=rule_id,
                symbol=context.symbol if context and context.symbol != UNKNOWN else None,
                title=f"Adaptive Experience {rule_id[-8:]}",
                content=str(guidance.get("summary") or guidance.get("statement") or ""),
                source_episode_count=len(source_ids),
                version=1,
                applicability_scope_json=context.to_json() if context else {},
                experience_type="ADAPTIVE_CARD",
                account_id=proposal.account_id or "default",
                mode=proposal.mode or "PAPER",
                share_scope=proposal.share_scope or "ACCOUNT_MODE",
                trigger_signature_json=trigger.to_json() if trigger else None,
                context_signature_json=context.to_json() if context else None,
                factor_refs_json=[
                    factor.factor_id for factor in (trigger.factors if trigger else ())
                ],
                guidance_json=guidance,
                source_episode_ids_json=source_ids,
                supporting_episode_ids_json=sorted(set(proposal.supporting_episode_ids)),
                contradicting_episode_ids_json=sorted(set(proposal.contradicting_episode_ids)),
                support_count=len(set(proposal.supporting_episode_ids)),
                contradiction_count=len(set(proposal.contradicting_episode_ids)),
                status=proposal.proposed_status or STATUS_CANDIDATE,
                known_at=now,
                updated_at=now,
                last_validated_at=now,
                update_reason=proposal.rationale[:255],
                supersedes_rule_id=proposal.supersedes_rule_id,
                supersedes_version=proposal.supersedes_version,
            )
            session.add(row)
            await session.flush()
            snapshot = self._row_snapshot(row)
            session.add(
                GrowthCardVersionORM(
                    card_rule_id=rule_id,
                    version=1,
                    operation=OP_CREATE,
                    snapshot_json=snapshot,
                    proposal_hash=proposal.proposal_hash,
                    source_episode_ids_json=source_ids,
                    trigger_signature_json=trigger.to_json() if trigger else None,
                    context_signature_json=context.to_json() if context else None,
                    support_count=row.support_count,
                    contradiction_count=row.contradiction_count,
                    quality_score=row.quality_score,
                    decay_score=row.decay_score,
                    status=row.status,
                    update_reason=proposal.rationale[:255],
                )
            )
            await session.commit()
            return CardMutationResult(
                rule_id=rule_id,
                version=1,
                operation=OP_CREATE,
                status=row.status,
                created_rule_ids=[rule_id],
                reason=proposal.rationale,
            )

    async def _update(
        self, proposal: CardUpdateProposal, *, now: datetime
    ) -> CardMutationResult:
        rule_id = proposal.card_rule_id
        if not rule_id:
            raise ValueError("UPDATE requires card_rule_id")
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(AICompressedExperienceORM).where(
                        AICompressedExperienceORM.rule_id == rule_id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                proposal.operation = OP_CREATE
                await session.rollback()
                return await self._create(proposal)
            old_version = int(row.version or 1)
            source = set(row.source_episode_ids_json or []) | set(
                proposal.source_episode_ids
            )
            support = set(row.supporting_episode_ids_json or []) | set(
                proposal.supporting_episode_ids
            )
            contrary = set(row.contradicting_episode_ids_json or []) | set(
                proposal.contradicting_episode_ids
            )
            row.version = old_version + 1
            row.source_episode_ids_json = sorted(source)
            row.source_episode_count = len(source)
            row.supporting_episode_ids_json = sorted(support - contrary)
            row.contradicting_episode_ids_json = sorted(contrary)
            row.support_count = len(support - contrary)
            row.contradiction_count = len(contrary)
            if proposal.proposed_guidance:
                row.guidance_json = dict(proposal.proposed_guidance)
                row.content = str(
                    row.guidance_json.get("summary")
                    or row.guidance_json.get("statement")
                    or row.content
                )
            if proposal.proposed_trigger:
                trigger = TriggerSignature.from_json(proposal.proposed_trigger)
                row.trigger_signature_json = (
                    trigger.to_json() if trigger else row.trigger_signature_json
                )
                row.factor_refs_json = [
                    factor.factor_id for factor in (trigger.factors if trigger else ())
                ]
            if proposal.proposed_status:
                row.status = proposal.proposed_status
            if proposal.share_scope:
                row.share_scope = proposal.share_scope
            if proposal.supersedes_rule_id:
                row.supersedes_rule_id = proposal.supersedes_rule_id
                row.supersedes_version = proposal.supersedes_version
            row.updated_at = now
            row.last_validated_at = now
            row.update_reason = proposal.rationale[:255]
            session.add(
                GrowthCardVersionORM(
                    card_rule_id=rule_id,
                    version=row.version,
                    operation=OP_UPDATE,
                    snapshot_json=self._row_snapshot(row),
                    proposal_hash=proposal.proposal_hash,
                    source_episode_ids_json=sorted(source),
                    trigger_signature_json=row.trigger_signature_json,
                    context_signature_json=row.context_signature_json,
                    support_count=row.support_count,
                    contradiction_count=row.contradiction_count,
                    quality_score=row.quality_score,
                    decay_score=row.decay_score,
                    status=row.status,
                    update_reason=proposal.rationale[:255],
                    supersedes_rule_id=rule_id,
                    supersedes_version=old_version,
                )
            )
            await session.commit()
            return CardMutationResult(
                rule_id=rule_id,
                version=row.version,
                operation=OP_UPDATE,
                status=row.status,
                reason=proposal.rationale,
            )

    async def _keep(
        self, proposal: CardUpdateProposal, *, now: datetime
    ) -> CardMutationResult:
        rule_id = proposal.card_rule_id
        if not rule_id:
            raise ValueError("KEEP requires card_rule_id")
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(AICompressedExperienceORM).where(
                        AICompressedExperienceORM.rule_id == rule_id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                raise ValueError(f"unknown card {rule_id}")
            row.last_validated_at = now
            row.updated_at = now
            row.update_reason = proposal.rationale[:255]
            session.add(
                GrowthCardVersionORM(
                    card_rule_id=rule_id,
                    version=int(row.version or 1),
                    operation=OP_KEEP,
                    snapshot_json=self._row_snapshot(row),
                    proposal_hash=proposal.proposal_hash,
                    source_episode_ids_json=list(row.source_episode_ids_json or []),
                    trigger_signature_json=row.trigger_signature_json,
                    context_signature_json=row.context_signature_json,
                    support_count=row.support_count,
                    contradiction_count=row.contradiction_count,
                    quality_score=row.quality_score,
                    decay_score=row.decay_score,
                    status=row.status,
                    update_reason=proposal.rationale[:255],
                )
            )
            await session.commit()
            return CardMutationResult(
                rule_id=rule_id,
                version=int(row.version or 1),
                operation=OP_KEEP,
                status=row.status,
                reason="NO_NEW_INFORMATION",
            )

    async def _status_change(
        self, proposal: CardUpdateProposal, *, now: datetime
    ) -> CardMutationResult:
        rule_id = proposal.card_rule_id
        if not rule_id:
            raise ValueError(f"{proposal.operation} requires card_rule_id")
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(AICompressedExperienceORM).where(
                        AICompressedExperienceORM.rule_id == rule_id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                raise ValueError(f"unknown card {rule_id}")
            new_status = proposal.proposed_status or (
                STATUS_RETIRED if proposal.operation == OP_RETIRE else STATUS_WATCH
            )
            row.version = int(row.version or 1) + 1
            row.status = new_status
            row.updated_at = now
            row.update_reason = proposal.rationale[:255]
            if new_status == STATUS_ACTIVE:
                row.last_validated_at = now
            session.add(
                GrowthCardVersionORM(
                    card_rule_id=rule_id,
                    version=row.version,
                    operation=proposal.operation,
                    snapshot_json=self._row_snapshot(row),
                    proposal_hash=proposal.proposal_hash,
                    source_episode_ids_json=list(row.source_episode_ids_json or []),
                    trigger_signature_json=row.trigger_signature_json,
                    context_signature_json=row.context_signature_json,
                    support_count=row.support_count,
                    contradiction_count=row.contradiction_count,
                    quality_score=row.quality_score,
                    decay_score=row.decay_score,
                    status=row.status,
                    update_reason=proposal.rationale[:255],
                )
            )
            await session.commit()
            return CardMutationResult(
                rule_id=rule_id,
                version=row.version,
                operation=proposal.operation,
                status=row.status,
                reason=proposal.rationale,
            )

    async def _split(
        self, proposal: CardUpdateProposal, *, now: datetime
    ) -> CardMutationResult:
        rule_id = proposal.card_rule_id
        if not rule_id or not proposal.split_contexts:
            raise ValueError("SPLIT requires card_rule_id and split_contexts")
        parent = await self.get_card(rule_id)
        if parent is None:
            raise ValueError(f"unknown card {rule_id}")
        created: list[str] = []
        for context_payload in proposal.split_contexts:
            child_context = ContextSignature.from_json(context_payload)
            child_proposal = CardUpdateProposal(
                operation=OP_CREATE,
                rationale=f"SPLIT from {rule_id}: {proposal.rationale}"[:255],
                source_episode_ids=list(parent.source_episode_ids),
                supporting_episode_ids=list(parent.supporting_episode_ids),
                contradicting_episode_ids=list(parent.contradicting_episode_ids),
                evidence_refs=list(proposal.evidence_refs),
                proposed_guidance=dict(parent.guidance),
                proposed_trigger=parent.trigger.to_json() if parent.trigger else None,
                proposed_context=child_context.to_json() if child_context else None,
                proposed_status=STATUS_CANDIDATE,
                supersedes_rule_id=rule_id,
                supersedes_version=parent.version,
            ).finalize()
            result = await self._create(child_proposal, now=now)
            created.append(result.rule_id)
        retire = CardUpdateProposal(
            operation=OP_RETIRE,
            rationale=f"SPLIT into {created}",
            card_rule_id=rule_id,
            proposed_status=STATUS_RETIRED,
        ).finalize()
        await self._status_change(retire, now=now)
        return CardMutationResult(
            rule_id=rule_id,
            version=(await self.get_card(rule_id)).version,
            operation=OP_SPLIT,
            status=STATUS_RETIRED,
            created_rule_ids=created,
            reason=proposal.rationale,
        )

    async def _merge(
        self, proposal: CardUpdateProposal, *, now: datetime
    ) -> CardMutationResult:
        target_id = proposal.card_rule_id
        sources = list(proposal.merge_target_rule_ids)
        if not target_id or not sources:
            raise ValueError("MERGE requires card_rule_id (target) and merge_target_rule_ids")
        cards = [await self.get_card(rule_id) for rule_id in [target_id, *sources]]
        if any(card is None for card in cards):
            raise ValueError("MERGE references an unknown card")
        target, *source_cards = cards
        if target is None or any(card is None for card in source_cards):
            raise ValueError("MERGE references an unknown card")
        for source in source_cards:
            if not trigger_payload_equal(
                target.trigger.to_json() if target.trigger else None,
                source.trigger.to_json() if source.trigger else None,
            ):
                raise ValueError("MERGE requires compatible triggers")
            if not context_payload_equal(
                target.context.to_json() if target.context else None,
                source.context.to_json() if source.context else None,
            ):
                raise ValueError("MERGE requires compatible context")
            if not guidance_compatible(target.guidance, source.guidance):
                raise ValueError("MERGE refuses conflicting guidance")
        merged = CardUpdateProposal(
            operation=OP_UPDATE,
            rationale=f"MERGE sources={sources}: {proposal.rationale}"[:255],
            card_rule_id=target_id,
            source_episode_ids=sorted(
                set().union(
                    *[set(card.source_episode_ids) for card in cards if card is not None]
                )
            ),
            supporting_episode_ids=sorted(
                set().union(
                    *[set(card.supporting_episode_ids) for card in cards if card is not None]
                )
            ),
            contradicting_episode_ids=sorted(
                set().union(
                    *[set(card.contradicting_episode_ids) for card in cards if card is not None]
                )
            ),
            evidence_refs=list(proposal.evidence_refs),
        ).finalize()
        result = await self._update(merged, now=now)
        retired: list[str] = []
        for source in source_cards:
            if source is None:
                continue
            retire = CardUpdateProposal(
                operation=OP_RETIRE,
                rationale=f"MERGED into {target_id}",
                card_rule_id=source.rule_id,
                proposed_status=STATUS_RETIRED,
                merge_target_rule_ids=[target_id],
            ).finalize()
            await self._status_change(retire, now=now)
            retired.append(source.rule_id)
        result.operation = OP_MERGE
        result.retired_rule_ids = retired
        return result

    @staticmethod
    def _row_snapshot(row: AICompressedExperienceORM) -> dict[str, Any]:
        return {
            "rule_id": row.rule_id,
            "title": row.title,
            "content": row.content,
            "experience_type": row.experience_type,
            "account_id": row.account_id,
            "mode": row.mode,
            "share_scope": row.share_scope,
            "applicability_scope_json": row.applicability_scope_json,
            "trigger_signature_json": row.trigger_signature_json,
            "context_signature_json": row.context_signature_json,
            "guidance_json": row.guidance_json,
            "factor_refs_json": row.factor_refs_json,
            "source_episode_ids_json": row.source_episode_ids_json,
            "supporting_episode_ids_json": row.supporting_episode_ids_json,
            "contradicting_episode_ids_json": row.contradicting_episode_ids_json,
            "sample_count": int(row.source_episode_count or 0),
            "support_count": int(row.support_count or 0),
            "contradiction_count": int(row.contradiction_count or 0),
            "confidence": str(row.confidence or "0"),
            "quality_score": str(row.quality_score or "0"),
            "decay_score": str(row.decay_score or "0"),
            "status": row.status,
            "version": int(row.version or 1),
            "last_validated_at": (
                row.last_validated_at.isoformat() if row.last_validated_at else None
            ),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "known_at": row.known_at.isoformat() if row.known_at else None,
            "update_reason": row.update_reason,
        }
