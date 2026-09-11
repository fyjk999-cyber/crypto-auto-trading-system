"""G12: attribution and card evolution on the Daily Review write path.

The runtime never imports this module.  Outcome association is explicitly
``OUTCOME_ASSOCIATED``; a WIN never bumps every used card and a LOSS never
invalidates a card.  Operations are limited to
KEEP/UPDATE/CREATE/SPLIT/MERGE/WATCH/RETIRE.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from crypto_trader.learning.growth_card_quality import (
    CardQualityPolicy,
    assess_card_quality,
)
from crypto_trader.learning.growth_experience import (
    AdaptiveCardStore,
    CardMutationResult,
    ClaimLostError,
)
from crypto_trader.learning.growth_models import (
    GrowthCardDecisionTraceORM,
    GrowthPatternORM,
    GrowthReviewAttemptORM,
)
from crypto_trader.learning.growth_review import STATUS_SUCCEEDED, ReviewAttempt
from crypto_trader.learning.growth_v2_contracts import (
    CAUSALITY_ASSOCIATED,
    OP_CREATE,
    OP_KEEP,
    OP_MERGE,
    OP_RETIRE,
    OP_SPLIT,
    OP_UPDATE,
    STATUS_ACTIVE,
    STATUS_CANDIDATE,
    STATUS_RETIRED,
    STATUS_WATCH,
    UNKNOWN,
    AdaptiveExperienceCard,
    AttributionReport,
    AxisAssessment,
    CardUpdateProposal,
    ContextSignature,
    TriggerSignature,
    context_payload_equal,
    guidance_compatible,
    trigger_payload_equal,
)
from crypto_trader.persistence.models import TradeEpisodeORM

Fence = Callable[[], Awaitable[bool]]


@dataclass
class LearnerReport:
    review_date: str
    considered: int = 0
    attributed: int = 0
    mutations: list[CardMutationResult] = field(default_factory=list)
    claim_lost: bool = False
    skipped_reason: str | None = None


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class CardAttributionEngine:
    """Turns one factual outcome + structured review + decision trace into a proposal."""

    def __init__(
        self,
        *,
        quality_policy: CardQualityPolicy | None = None,
        allow_retire_on_contradiction: bool = False,
    ) -> None:
        self.quality_policy = quality_policy or CardQualityPolicy()
        self.allow_retire_on_contradiction = allow_retire_on_contradiction

    def attribute(
        self,
        *,
        episode: TradeEpisodeORM,
        review: ReviewAttempt | None,
        trace: GrowthCardDecisionTraceORM | None,
        card: AdaptiveExperienceCard,
        now: datetime,
        data_quality: str = "UNKNOWN",
    ) -> AttributionReport:
        selected_refs = list((trace.selected_card_refs_json if trace else []) or [])
        used = any(ref.startswith(f"card:{card.rule_id}:") for ref in selected_refs)
        axes = self._axes(episode, review, data_quality=data_quality)
        if not used:
            proposal = CardUpdateProposal(
                operation=OP_KEEP,
                rationale="CARD_NOT_USED_IN_DECISION",
                card_rule_id=card.rule_id,
                source_episode_ids=[episode.episode_id],
            )
            return AttributionReport(
                episode_id=episode.episode_id,
                card_rule_id=card.rule_id,
                card_version=card.version,
                axes=axes,
                rationale="card not selected by the decision; no attribution",
                proposal=proposal.finalize(),
            )

        review_refs: set[str] = set()
        if review and review.review:
            for lesson in review.review.testable_lessons:
                review_refs.update(lesson.evidence_refs or [])
                review_refs.update(lesson.contrary_refs or [])
        card_refs = set(card.source_episode_ids) | set(card.factor_refs)
        supporting_refs = sorted(
            ref for ref in review_refs if ref.split(":")[-1] in card_refs
        )
        contrary_refs = sorted(
            ref
            for ref in review_refs
            if any(
                ref in (lesson.contrary_refs or [])
                for lesson in (review.review.testable_lessons if review and review.review else [])
            )
        )
        axes["prediction_correctness"] = AxisAssessment(
            value=(
                "CONTRADICTED"
                if contrary_refs
                else "SUPPORTED_ASSOCIATION"
                if supporting_refs
                else UNKNOWN
            ),
            status="PROVEN" if (supporting_refs or contrary_refs) else "UNKNOWN",
            evidence_refs=(contrary_refs or supporting_refs)[:5],
            note="association from review evidence refs; not a PnL verdict",
        )

        source_ids = sorted(set(card.source_episode_ids) | {episode.episode_id})
        if contrary_refs:
            proposal = self._contradiction_proposal(
                card, episode, contrary_refs, source_ids
            )
            rationale = "contradiction evidence associated with selected card"
        elif supporting_refs:
            proposal = self._support_proposal(card, episode, supporting_refs, source_ids)
            rationale = "supporting review evidence associated with selected card"
        else:
            proposal = CardUpdateProposal(
                operation=OP_KEEP,
                rationale="NO_NEW_CARD_RELEVANT_EVIDENCE",
                card_rule_id=card.rule_id,
                source_episode_ids=source_ids,
                evidence_refs=[],
            )
            rationale = "used card, but no new supportive/contrary evidence"
        proposal.finalize()
        return AttributionReport(
            episode_id=episode.episode_id,
            card_rule_id=card.rule_id,
            card_version=card.version,
            axes=axes,
            causality=CAUSALITY_ASSOCIATED,
            proposal=proposal,
            rationale=rationale,
        )

    def _support_proposal(
        self,
        card: AdaptiveExperienceCard,
        episode: TradeEpisodeORM,
        refs: list[str],
        source_ids: list[str],
    ) -> CardUpdateProposal:
        support = len(set(card.supporting_episode_ids) | {episode.episode_id})
        contrary = len(set(card.contradicting_episode_ids))
        sample = len(set(source_ids))
        quality = assess_card_quality(
            knowledge_id=card.rule_id,
            sample_count=sample,
            support_count=support,
            contradiction_count=contrary,
            trigger_complete=bool(card.trigger and card.trigger.complete),
            regime_known=bool(card.context and card.context.regime != UNKNOWN),
            evidence_quality=1.0 if refs else 0.0,
            regime_consistency=1.0 if card.context and card.context.regime != UNKNOWN else 0.0,
            repeatability=support / max(1, sample),
            confidence_input=float(card.confidence or Decimal("0")),
            now=datetime.now(UTC),
            last_validated_at=card.last_validated_at,
            policy=self.quality_policy,
        )
        if quality.promotion_ready and card.contradiction_count == 0:
            proposed_status = STATUS_ACTIVE
        elif card.status == STATUS_WATCH:
            # Unresolved contradiction keeps the card on WATCH; support alone
            # must not silently re-promote it.
            proposed_status = STATUS_WATCH
        elif card.status == STATUS_CANDIDATE:
            proposed_status = STATUS_CANDIDATE
        else:
            proposed_status = card.status
        return CardUpdateProposal(
            operation=OP_UPDATE,
            rationale=f"SUPPORT_ASSOCIATED refs={len(refs)} quality={quality.quality_score}",
            card_rule_id=card.rule_id,
            source_episode_ids=source_ids,
            supporting_episode_ids=[episode.episode_id],
            evidence_refs=refs[:5],
            proposed_status=proposed_status,
        )

    def _contradiction_proposal(
        self,
        card: AdaptiveExperienceCard,
        episode: TradeEpisodeORM,
        refs: list[str],
        source_ids: list[str],
    ) -> CardUpdateProposal:
        contrary = len(set(card.contradicting_episode_ids) | {episode.episode_id})
        support = len(set(card.supporting_episode_ids))
        if self.allow_retire_on_contradiction and contrary > support:
            operation = OP_RETIRE
            status = STATUS_RETIRED
        else:
            operation = OP_UPDATE
            status = STATUS_WATCH
        return CardUpdateProposal(
            operation=operation,
            rationale=(
                "CONTRADICTION_ASSOCIATED "
                f"refs={len(refs)} support={support} contrary={contrary}"
            ),
            card_rule_id=card.rule_id,
            source_episode_ids=source_ids,
            contradicting_episode_ids=[episode.episode_id],
            evidence_refs=refs[:5],
            proposed_status=status,
        )

    def propose_split(
        self, card: AdaptiveExperienceCard, split_contexts: list[dict[str, Any]]
    ) -> CardUpdateProposal:
        return CardUpdateProposal(
            operation=OP_SPLIT,
            rationale="CONTEXT_CLUSTERS_DIFFER",
            card_rule_id=card.rule_id,
            source_episode_ids=list(card.source_episode_ids),
            supporting_episode_ids=list(card.supporting_episode_ids),
            contradicting_episode_ids=list(card.contradicting_episode_ids),
            split_contexts=split_contexts,
            evidence_refs=[f"episode:{eid}" for eid in card.source_episode_ids],
        ).finalize()

    def propose_merge(
        self, target: AdaptiveExperienceCard, source: AdaptiveExperienceCard
    ) -> CardUpdateProposal:
        if not trigger_payload_equal(
            target.trigger.to_json() if target.trigger else None,
            source.trigger.to_json() if source.trigger else None,
        ):
            raise ValueError("MERGE requires trigger compatibility")
        if not context_payload_equal(
            target.context.to_json() if target.context else None,
            source.context.to_json() if source.context else None,
        ):
            raise ValueError("MERGE requires context compatibility")
        if not guidance_compatible(target.guidance, source.guidance):
            raise ValueError("MERGE refuses conflicting guidance")
        return CardUpdateProposal(
            operation=OP_MERGE,
            rationale="COMPATIBLE_TRIGGER_CONTEXT_GUIDANCE",
            card_rule_id=target.rule_id,
            merge_target_rule_ids=[source.rule_id],
            source_episode_ids=sorted(
                set(target.source_episode_ids) | set(source.source_episode_ids)
            ),
            supporting_episode_ids=sorted(
                set(target.supporting_episode_ids) | set(source.supporting_episode_ids)
            ),
            contradicting_episode_ids=sorted(
                set(target.contradicting_episode_ids)
                | set(source.contradicting_episode_ids)
            ),
            evidence_refs=[f"episode:{eid}" for eid in source.source_episode_ids],
        ).finalize()

    @staticmethod
    def _axes(
        episode: TradeEpisodeORM, review: ReviewAttempt | None, *, data_quality: str
    ) -> dict[str, AxisAssessment]:
        net = episode.net_pnl or Decimal("0")
        outcome = "WIN" if net > 0 else "LOSS" if net < 0 else "BREAKEVEN"
        review_available = bool(review and review.review)
        return {
            "market_outcome": AxisAssessment(outcome, "PROVEN", note="descriptive only"),
            "decision_quality": AxisAssessment(
                "REVIEWED" if review_available else UNKNOWN,
                "PARTIAL" if review_available else "UNKNOWN",
                evidence_refs=[f"review:{episode.episode_id}"] if review_available else [],
            ),
            "prediction_correctness": AxisAssessment(
                UNKNOWN, "UNKNOWN", note="filled only from review evidence refs"
            ),
            "risk_adjustment": AxisAssessment(
                "PRESENT" if getattr(episode, "leverage", None) else UNKNOWN,
                "PARTIAL" if getattr(episode, "leverage", None) else "UNKNOWN",
            ),
            "execution_quality": AxisAssessment(
                "FILL_DERIVED" if episode.fill_ids_json else UNKNOWN,
                "PROVEN" if episode.fill_ids_json else "UNKNOWN",
            ),
            "data_quality": AxisAssessment(
                data_quality, "PROVEN" if data_quality == "COMPLETE" else "UNKNOWN"
            ),
            "external_unmodeled": AxisAssessment(UNKNOWN, "UNKNOWN"),
        }


class DailyCardLearner:
    """Low-frequency write path; runtime callers are rejected."""

    WRITE_PATH = "DAILY_REVIEW"

    def __init__(
        self,
        session_factory,
        *,
        attribution: CardAttributionEngine | None = None,
        min_samples_for_active: int = 3,
    ) -> None:
        self.session_factory = session_factory
        self.attribution = attribution or CardAttributionEngine()
        self.store = AdaptiveCardStore(
            session_factory, min_samples_for_active=min_samples_for_active
        )

    async def learn_day(
        self,
        *,
        account_id: str,
        mode: str,
        review_date: str,
        profile_version: str | None = None,
        fence: Fence | None = None,
        origin: str = "DAILY_REVIEW",
        now: datetime | None = None,
    ) -> LearnerReport:
        if origin != self.WRITE_PATH:
            raise PermissionError(
                "Adaptive Experience Cards can only be updated on the Daily Review path"
            )
        now = now or datetime.now(UTC)
        report = LearnerReport(review_date=review_date)
        async with self.session_factory() as session:
            episodes = (
                await session.execute(
                    select(TradeEpisodeORM).where(
                        TradeEpisodeORM.factual.is_(True),
                        TradeEpisodeORM.closed_at
                        >= datetime.fromisoformat(review_date).replace(tzinfo=UTC),
                        TradeEpisodeORM.closed_at
                        < datetime.fromisoformat(review_date).replace(tzinfo=UTC)
                        + timedelta(days=1),
                    )
                )
            ).scalars().all()
        episode_by_id = {row.episode_id: row for row in episodes}
        attempts = await self._attempts(episodes, review_date, profile_version)
        for attempt in attempts:
            episode = episode_by_id.get(attempt.review.episode_id if attempt.review else "")
            if episode is None:
                continue
            report.considered += 1
            trace = await self._trace_for(episode, attempt)
            if trace is None:
                continue
            for ref in list(trace.selected_card_refs_json or []):
                rule_id = ref.split(":")[1] if ref.startswith("card:") else None
                if not rule_id:
                    continue
                card = await self.store.get_card(rule_id)
                if card is None:
                    continue
                report.attributed += 1
                attribution = self.attribution.attribute(
                    episode=episode,
                    review=attempt,
                    trace=trace,
                    card=card,
                    now=now,
                    data_quality="COMPLETE" if episode.funding_pnl is not None else "UNKNOWN",
                )
                if attribution.proposal is None or attribution.proposal.operation == OP_KEEP:
                    if attribution.proposal is not None:
                        report.mutations.append(
                            await self.store.apply(attribution.proposal, fence=fence, now=now)
                        )
                    continue
                try:
                    report.mutations.append(
                        await self.store.apply(attribution.proposal, fence=fence, now=now)
                    )
                except ClaimLostError:
                    report.claim_lost = True
                    report.skipped_reason = "CLAIM_LOST"
                    return report
        return report

    async def propose_from_pattern(
        self,
        *,
        pattern: GrowthPatternORM,
        reviews: list[ReviewAttempt],
        trigger: TriggerSignature,
        context: ContextSignature,
        rationale: str = "PATTERN_TO_EXPERIENCE_CARD",
        now: datetime | None = None,
    ) -> CardUpdateProposal:
        now = now or datetime.now(UTC)
        source_ids = sorted(
            set(list(pattern.success_refs_json or []) + list(pattern.contrary_refs_json or []))
        )
        support_ids = sorted(set(pattern.success_refs_json or []))
        contrary_ids = sorted(set(pattern.contrary_refs_json or []))
        if pattern.status not in {"VALIDATED", "CONTESTED"}:
            raise ValueError("only published patterns can seed a card")
        quality = assess_card_quality(
            knowledge_id=pattern.pattern_id,
            sample_count=pattern.sample_count,
            support_count=len(support_ids),
            contradiction_count=len(contrary_ids),
            trigger_complete=trigger.complete,
            regime_known=context.regime != UNKNOWN,
            evidence_quality=1.0 if reviews else 0.0,
            regime_consistency=1.0 if context.regime != UNKNOWN else 0.0,
            repeatability=len(support_ids) / max(1, len(source_ids)),
            confidence_input=(
                float(pattern.sample_count)
                / max(1, pattern.sample_count + len(contrary_ids))
            ),
            now=now,
            policy=self.attribution.quality_policy,
        )
        guidance = {
            "summary": pattern.status_reason or "pattern-derived experience",
            "effect": pattern.status,
            "sample_count": pattern.sample_count,
            "prompt_semantics": "historical evidence, not a command",
        }
        proposal = CardUpdateProposal(
            operation=OP_CREATE,
            rationale=rationale,
            source_episode_ids=source_ids,
            supporting_episode_ids=support_ids,
            contradicting_episode_ids=contrary_ids,
            evidence_refs=[f"pattern:{pattern.pattern_id}:v{pattern.version}"],
            proposed_trigger=trigger.to_json(),
            proposed_context=context.to_json(),
            proposed_guidance=guidance,
            proposed_status=STATUS_ACTIVE if quality.promotion_ready else STATUS_CANDIDATE,
        )
        return proposal.finalize()

    # ------------------------------------------------------------------
    async def _attempts(
        self, episodes: list[TradeEpisodeORM], review_date: str, profile_version: str | None
    ) -> list[ReviewAttempt]:
        if not episodes:
            return []
        episode_ids = [row.episode_id for row in episodes]
        async with self.session_factory() as session:
            query = select(GrowthReviewAttemptORM).where(
                GrowthReviewAttemptORM.episode_id.in_(episode_ids),
                GrowthReviewAttemptORM.status == STATUS_SUCCEEDED,
            )
            if profile_version:
                query = query.where(
                    GrowthReviewAttemptORM.profile_version == profile_version
                )
            rows = (await session.execute(query)).scalars().all()
        out = []
        for row in rows:
            if row.result_json is None:
                continue
            from crypto_trader.learning.growth_contracts import StructuredReview

            out.append(
                ReviewAttempt(
                    status=STATUS_SUCCEEDED,
                    attempt_id=row.attempt_id,
                    review=StructuredReview.model_validate(row.result_json),
                    idempotent=True,
                    account_id=row.account_id,
                    mode=row.mode,
                    symbol=row.symbol,
                    direction=row.direction,
                    review_date=row.review_date,
                    input_hash=row.input_hash,
                )
            )
        return out

    async def _trace_for(
        self, episode: TradeEpisodeORM, attempt: ReviewAttempt
    ) -> GrowthCardDecisionTraceORM | None:
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(GrowthCardDecisionTraceORM)
                    .where(
                        GrowthCardDecisionTraceORM.decision_id
                        == episode.entry_decision_id,
                        GrowthCardDecisionTraceORM.symbol == episode.symbol,
                    )
                    .order_by(GrowthCardDecisionTraceORM.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()


__all__ = [
    "CardAttributionEngine",
    "DailyCardLearner",
    "LearnerReport",
]
