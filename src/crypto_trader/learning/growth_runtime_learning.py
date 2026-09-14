"""Canonical runtime growth-learning path.

Closed factual episode -> structured evidence-bound review -> lesson /
proposition / pattern -> Adaptive Experience Card -> Chief ``experience_cards``
retrieval with trace-before-use.

This module deliberately does not create any legacy ``ai_trade_reviews`` row or
template lesson.  When the structured provider is unavailable or returns
insufficient evidence, no reusable knowledge is published.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from crypto_trader.governance.trade_episode import FactualTradeEpisode
from crypto_trader.learning.growth_attribution import DailyCardLearner
from crypto_trader.learning.growth_contracts import (
    EpisodeReviewInput,
    StructuredReview,
    TestableLesson,
)
from crypto_trader.learning.growth_experience import (
    AdaptiveCardStore,
    ClaimLostError,
)
from crypto_trader.learning.growth_knowledge import (
    RETRIEVABLE_STATUSES,
    EpisodeBinding,
    GrowthKnowledgePublisher,
    KnowledgeStore,
    contains_absolute_rule,
)
from crypto_trader.learning.growth_models import GrowthReviewAttemptORM
from crypto_trader.learning.growth_review import (
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    ReviewAttempt,
    StructuredReviewService,
)
from crypto_trader.learning.growth_review_evidence import (
    CausalEvidenceUnavailable,
    GrowthReviewEvidence,
    GrowthReviewEvidenceLoader,
    validate_causal_evidence_refs,
)
from crypto_trader.learning.growth_v2_contracts import (
    SHARE_SCOPE_ACCOUNT_MODE,
    ContextSignature,
    TriggerSignature,
)
from crypto_trader.persistence.models import AITradeReviewORM, LLMDecisionORM, TradeEpisodeORM

Fence = Callable[[], Awaitable[bool]]

CANONICAL_REGIMES = {
    "TRENDING",
    "RANGING",
    "HIGH_VOLATILITY",
    "LOW_VOLATILITY",
    "ACCUMULATION",
    "DISTRIBUTION",
    "PANIC",
    "UNKNOWN",
}

_REGIME_ALIASES = {
    "TREND": "TRENDING",
    "TRENDING": "TRENDING",
    "TREND_UP": "TRENDING",
    "TREND_DOWN": "TRENDING",
    "TREND_BULL": "TRENDING",
    "TREND_BEAR": "TRENDING",
    "UPTREND": "TRENDING",
    "DOWNTREND": "TRENDING",
    "BULL": "TRENDING",
    "BEAR": "TRENDING",
    "RANGE": "RANGING",
    "RANGING": "RANGING",
    "CHOP": "RANGING",
    "SIDEWAYS": "RANGING",
    "CONSOLIDATION": "RANGING",
    "HIGH_VOLATILITY": "HIGH_VOLATILITY",
    "VOLATILE": "HIGH_VOLATILITY",
    "PANIC": "PANIC",
    "LOW_VOLATILITY": "LOW_VOLATILITY",
    "QUIET": "LOW_VOLATILITY",
    "ACCUMULATION": "ACCUMULATION",
    "DISTRIBUTION": "DISTRIBUTION",
    "BREAKOUT": "TRENDING",
    "UNKNOWN": "UNKNOWN",
}


def normalize_regime(raw: str | None) -> tuple[str, str]:
    """Return ``(canonical_regime, regime_context)``.

    Free text is preserved as context but never used as coarse pattern
    identity.  The canonical value is chosen from the existing factor-regime
    taxonomy rather than inventing a parallel enum.
    """
    context = (raw or "UNKNOWN").strip()[:64]
    upper = context.upper()
    if upper in _REGIME_ALIASES:
        return _REGIME_ALIASES[upper], context
    if "TREND" in upper or "MOMENTUM" in upper:
        return "TRENDING", context
    if "RANGE" in upper or "CHOP" in upper or "CONSOLID" in upper:
        return "RANGING", context
    if "VOLATIL" in upper or "PANIC" in upper:
        return "HIGH_VOLATILITY" if "LOW" not in upper else "LOW_VOLATILITY", context
    if "ACCUM" in upper:
        return "ACCUMULATION", context
    if "DISTRIB" in upper:
        return "DISTRIBUTION", context
    return "UNKNOWN", context


@dataclass
class GrowthRuntimeReport:
    status: str
    review_date: str
    closed_episodes_seen: int = 0
    structured_reviews_created: int = 0
    reviews_with_causal_lessons: int = 0
    reviews_with_future_rules: int = 0
    lessons_created: int = 0
    patterns_created: int = 0
    cards_created: int = 0
    retrievable_cards: int = 0
    compressions_created: int = 0
    retrievals: int = 0
    traces: int = 0
    trace_failures: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "review_date": self.review_date,
            "closed_episodes_seen": self.closed_episodes_seen,
            "structured_reviews_created": self.structured_reviews_created,
            "reviews_with_causal_lessons": self.reviews_with_causal_lessons,
            "reviews_with_future_rules": self.reviews_with_future_rules,
            "lessons_created": self.lessons_created,
            "patterns_created": self.patterns_created,
            "cards_created": self.cards_created,
            "retrievable_cards": self.retrievable_cards,
            "compressions_created": self.compressions_created,
            "retrievals": self.retrievals,
            "traces": self.traces,
            "trace_failures": self.trace_failures,
            "errors": list(self.errors),
        }


def runtime_status(report: GrowthRuntimeReport) -> str:
    if report.closed_episodes_seen == 0:
        return "NO_DATA"
    if report.structured_reviews_created == 0:
        return "BLOCKED"
    if report.retrievable_cards == 0 and report.compressions_created == 0:
        if report.cards_created or report.lessons_created or report.patterns_created:
            return "CANDIDATE_LEARNING"
        return "REVIEW_ONLY"
    if report.errors or report.trace_failures:
        return "DEGRADED"
    return "LEARNING"


def _episode_review_input(
    episode: FactualTradeEpisode,
    *,
    account_id: str,
    mode: str,
    currency: str,
    review_evidence: GrowthReviewEvidence,
) -> EpisodeReviewInput:
    canonical_regime, regime_context = normalize_regime(episode.entry_market_regime)
    market_changes = [
        {
            "entry_market_regime_raw": episode.entry_market_regime,
            "regime_context": regime_context,
            "holding_time_seconds": episode.holding_time_seconds,
        }
    ]
    return EpisodeReviewInput(
        episode_id=episode.episode_id,
        account_id=account_id,
        mode=mode,
        symbol=episode.symbol,
        direction=episode.direction,
        currency=currency,
        entry_decision_id=episode.entry_decision_id,
        exit_decision_id=episode.exit_decision_id,
        order_refs=list(episode.order_ids or []),
        fill_refs=list(episode.fill_ids or []),
        entry_price=episode.entry_price,
        exit_price=episode.exit_price,
        quantity=episode.closed_quantity,
        leverage=episode.leverage,
        fees=episode.fees,
        funding_pnl=episode.funding_pnl,
        funding_provenance="PROVEN",
        gross_pnl=episode.gross_pnl,
        net_pnl=episode.net_pnl,
        opened_at=episode.opened_at,
        closed_at=episode.closed_at,
        entry_market_regime=canonical_regime,
        terminal_reason=episode.terminal_reason,
        thesis=f"closed episode terminal_reason={episode.terminal_reason}",
        selected_tools=[],
        trade_plan={
            "trade_plan_id": episode.trade_plan_id,
            "holding_time_seconds": episode.holding_time_seconds,
            "fees": str(episode.fees),
        },
        risk_adjustments=[],
        position_actions=[],
        market_changes=market_changes,
        missing_evidence=list(review_evidence.missing_evidence),
        review_evidence=review_evidence.as_payload(),
    )


def _binding(
    episode: FactualTradeEpisode,
    *,
    account_id: str,
    mode: str,
    currency: str,
) -> EpisodeBinding:
    canonical_regime, _context = normalize_regime(episode.entry_market_regime)
    return EpisodeBinding(
        account_id=account_id,
        mode=mode,
        currency=currency,
        instrument_id=episode.symbol,
        source_revision=episode.trade_plan_id,
        terminal_reason=episode.terminal_reason,
        funding_provenance="PROVEN",
        proof_kind="FACTUAL_EPISODE",
        regime=canonical_regime,
        direction=episode.direction,
    )


def _future_rule_scope(item) -> dict:
    applicability = dict(item.applicability or {})
    scope: dict = {"scope": "SYMBOL_REGIME"}
    for key in ("scope", "symbols", "regimes", "directions"):
        if key in applicability:
            scope[key] = applicability[key]
    if "regime" in applicability and "regimes" not in scope:
        scope["regimes"] = [applicability["regime"]]
    if "symbol" in applicability and "symbols" not in scope:
        scope["symbols"] = [applicability["symbol"]]
    if "direction" in applicability and "directions" not in scope:
        scope["directions"] = [applicability["direction"]]
    scope["counter_conditions"] = list(item.counter_conditions or [])
    return scope



def _prepare_publication_attempt(
    attempt: ReviewAttempt,
    *,
    evidence: GrowthReviewEvidence,
) -> tuple[ReviewAttempt | None, list[str]]:
    """Return a publication-safe deep copy and explicit blocked reasons."""
    if attempt.review is None:
        return None, []
    review = attempt.review
    safe_lessons = []
    blocked: list[str] = []
    for lesson in review.testable_lessons:
        if contains_absolute_rule(lesson.statement):
            blocked.append(
                f"ABSOLUTE_RULE_LANGUAGE_BLOCKED:{review.episode_id}"
            )
            continue
        try:
            validate_causal_evidence_refs(evidence, list(lesson.evidence_refs))
            if lesson.contrary_refs:
                validate_causal_evidence_refs(evidence, list(lesson.contrary_refs))
        except CausalEvidenceUnavailable as exc:
            blocked.append(
                f"CAUSAL_EVIDENCE_BLOCKED:{review.episode_id}:{exc}"
            )
            continue
        safe_lessons.append(lesson.model_copy(deep=True))
    for item in review.future_rules:
        if contains_absolute_rule(item.statement):
            blocked.append(
                f"ABSOLUTE_RULE_LANGUAGE_BLOCKED:{review.episode_id}"
            )
            continue
        try:
            validate_causal_evidence_refs(evidence, list(item.evidence_refs))
        except CausalEvidenceUnavailable as exc:
            blocked.append(
                f"CAUSAL_EVIDENCE_BLOCKED:{review.episode_id}:{exc}"
            )
            continue
        safe_lessons.append(
            TestableLesson(
                statement=item.statement,
                testable_prediction=item.statement,
                scope=_future_rule_scope(item),
                evidence_refs=list(item.evidence_refs),
                contrary_refs=[],
                uncertainty="FUTURE_RULE",
                confidence=item.confidence,
            )
        )
    if not safe_lessons:
        return None, blocked
    publication_review = review.model_copy(deep=True)
    publication_review.testable_lessons = safe_lessons
    return replace(attempt, review=publication_review), blocked



class GrowthRuntimeLearningService:
    """One canonical runtime learning authority (Daily Review path only)."""

    WRITE_PATH = "DAILY_REVIEW"

    def __init__(
        self,
        session_factory,
        *,
        provider,
        account_id: str = "default",
        mode: str = "PAPER",
        currency: str = "USDT",
        min_pattern_samples: int = 3,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.account_id = account_id
        self.mode = mode
        self.currency = currency
        self.store = KnowledgeStore(session_factory)
        self.publisher = GrowthKnowledgePublisher(
            session_factory, min_pattern_samples=min_pattern_samples
        )
        self.evidence_loader = GrowthReviewEvidenceLoader(session_factory)
        self.review_service = (
            StructuredReviewService(provider, session_factory)
            if provider is not None
            else None
        )
        self.card_store = AdaptiveCardStore(session_factory)
        self.card_learner = DailyCardLearner(session_factory)

    async def run(
        self,
        episodes: list[FactualTradeEpisode],
        *,
        review_date: str,
        claim_token: str,
        owner: str,
        fence: Fence,
        now: datetime | None = None,
    ) -> GrowthRuntimeReport:
        report = GrowthRuntimeReport(
            status="NO_DATA", review_date=review_date
        )
        report.closed_episodes_seen = len(episodes)
        if not episodes:
            return report
        if self.review_service is None:
            report.status = "BLOCKED"
            report.errors.append("NO_STRUCTURED_REVIEW_PROVIDER")
            return report

        attempts: list[ReviewAttempt] = []
        evidence_by_episode: dict[str, GrowthReviewEvidence] = {}
        bindings: dict[str, EpisodeBinding] = {}
        succeeded: list[ReviewAttempt] = []
        for episode in episodes:
            try:
                evidence = await self.evidence_loader.load(
                    episode,
                    account_id=self.account_id,
                    mode=self.mode,
                    now=now,
                )
                payload = _episode_review_input(
                    episode,
                    account_id=self.account_id,
                    mode=self.mode,
                    currency=self.currency,
                    review_evidence=evidence,
                )
                binding = _binding(
                    episode,
                    account_id=self.account_id,
                    mode=self.mode,
                    currency=self.currency,
                )
                evidence_by_episode[episode.episode_id] = evidence
            except Exception as exc:
                report.errors.append(type(exc).__name__)
                continue
            bindings[episode.episode_id] = binding
            try:
                attempt = await self.review_service.review(
                    payload,
                    review_date=review_date,
                    allowed_refs=payload.derived_refs(),
                    claim_token=claim_token,
                    owner=owner,
                    claim_checker=fence,
                )
            except Exception as exc:  # durable FAILED attempt is persisted by service
                report.errors.append(f"{type(exc).__name__}")
                continue
            attempts.append(attempt)
            if attempt.status != STATUS_SUCCEEDED or attempt.review is None:
                if attempt.status == STATUS_FAILED:
                    report.errors.append(attempt.error_type or "REVIEW_FAILED")
                continue
            succeeded.append(attempt)
            review = attempt.review
            report.structured_reviews_created += 1
            report.reviews_with_future_rules += 1 if review.future_rules else 0
            await self._persist_audit_learning(attempt)

        if not succeeded:
            report.status = (
                "FAILED"
                if attempts and report.errors
                else "REVIEW_ONLY"
                if attempts
                else "BLOCKED"
            )
            return report

        publishable_attempts: list[ReviewAttempt] = []
        for attempt in succeeded:
            if attempt.review is None:
                continue
            evidence = evidence_by_episode.get(attempt.review.episode_id)
            if evidence is None:
                report.errors.append("CAUSAL_EVIDENCE_MISSING")
                continue
            safe_attempt, blocked = _prepare_publication_attempt(
                attempt, evidence=evidence
            )
            report.errors.extend(blocked)
            if safe_attempt is not None:
                publishable_attempts.append(safe_attempt)

        report.reviews_with_causal_lessons = sum(
            1
            for safe_attempt in publishable_attempts
            if safe_attempt.review is not None
            and bool(safe_attempt.review.testable_lessons)
        )
        if not publishable_attempts:
            report.reviews_with_causal_lessons = 0
            report.status = "REVIEW_ONLY"
            return report

        # Epistemic time: knowledge becomes known when the review/publish runs,
        # never backdated to the historical episode close time.
        known_at = now or datetime.now(UTC)
        try:
            published = await self.publisher.publish_attempts(
                publishable_attempts,
                bindings=bindings,
                known_at=known_at,
                claim_context=(review_date, claim_token, owner),
            )
        except ClaimLostError:
            report.status = "DEGRADED"
            report.errors.append("CLAIM_LOST")
            return report
        report.lessons_created = int(published.get("lessons", 0))
        report.patterns_created = int(published.get("published_count", 0))

        cards, retrievable, patterns = await self._materialize_cards(
            episode_ids={
                attempt.review.episode_id
                for attempt in publishable_attempts
                if attempt.review
            },
            known_at=known_at,
            fence=fence,
        )
        report.cards_created = cards
        report.retrievable_cards = retrievable
        report.status = runtime_status(report)
        if report.status == "NO_DATA":
            report.status = "REVIEW_ONLY"
        return report

    async def _persist_audit_learning(self, attempt: ReviewAttempt) -> None:
        """Persist causal review fields on the descriptive review row.

        These fields are audit/support evidence; reusable learned experience is
        still published only through lessons/patterns/cards.
        """
        if attempt.review is None:
            return
        review = attempt.review
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(AITradeReviewORM).where(
                        AITradeReviewORM.episode_id == review.episode_id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return
            row.success_factors_json = [
                item.statement for item in review.success_factors
            ]
            row.failure_factors_json = [
                item.statement for item in review.failure_factors
            ]
            row.mistakes_json = [
                item.model_dump(mode="json") for item in review.mistakes
            ]
            row.future_rules_json = [
                item.model_dump(mode="json") for item in review.future_rules
            ]
            row.lessons_json = [
                lesson.statement for lesson in review.testable_lessons
            ]
            await session.commit()

    async def _load_pattern_review_attempts(
        self, member_ids: set[str]
    ) -> list[ReviewAttempt]:
        """Load the latest succeeded structured review for each pattern member."""
        if not member_ids:
            return []
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(GrowthReviewAttemptORM)
                    .where(
                        GrowthReviewAttemptORM.episode_id.in_(tuple(member_ids)),
                        GrowthReviewAttemptORM.status == STATUS_SUCCEEDED,
                        GrowthReviewAttemptORM.account_id == self.account_id,
                        GrowthReviewAttemptORM.mode == self.mode,
                    )
                    .order_by(GrowthReviewAttemptORM.created_at.asc())
                )
            ).scalars().all()
        latest: dict[str, ReviewAttempt] = {}
        for row in rows:
            if row.result_json is None:
                continue
            latest[row.episode_id] = ReviewAttempt(
                status=STATUS_SUCCEEDED,
                attempt_id=row.attempt_id,
                review=StructuredReview.model_validate(row.result_json),
                usage_status=row.usage_status,
                idempotent=True,
                account_id=row.account_id,
                mode=row.mode,
                symbol=row.symbol,
                direction=row.direction,
                review_date=row.review_date,
                input_hash=row.input_hash,
            )
        return [latest[key] for key in sorted(latest)]

    async def _factor_states_for_pattern(
        self, member_ids: set[str], known_at: datetime
    ) -> list[dict[str, Any]]:
        """Recover factual factor states from the members' decision lineage.

        ``triggered_factors_json`` contains only observed triggered factors;
        state/definition_version/observed_at are used when the runtime stored
        them.  Missing metadata is preserved as UNKNOWN and never inferred.
        """
        if not member_ids:
            return []
        async with self.session_factory() as session:
            episodes = (
                await session.execute(
                    select(TradeEpisodeORM).where(
                        TradeEpisodeORM.episode_id.in_(tuple(member_ids))
                    )
                )
            ).scalars().all()
            decision_ids: set[str] = set()
            for episode in episodes:
                if episode.entry_decision_id:
                    decision_ids.add(episode.entry_decision_id)
                if episode.exit_decision_id:
                    decision_ids.add(episode.exit_decision_id)
                decision_ids.update(
                    str(item) for item in (episode.position_decision_ids_json or [])
                )
            if not decision_ids:
                return []
            decisions = (
                await session.execute(
                    select(LLMDecisionORM).where(
                        LLMDecisionORM.decision_id.in_(tuple(decision_ids))
                    )
                )
            ).scalars().all()
        states: list[dict[str, Any]] = []
        for decision in decisions:
            for raw in decision.triggered_factors_json or []:
                if not isinstance(raw, dict):
                    continue
                factor_id = raw.get("factor") or raw.get("factor_id")
                if not factor_id:
                    continue
                raw_state = str(
                    raw.get("status") or raw.get("state") or "TRIGGERED"
                ).upper()
                state = "UNKNOWN" if raw_state == "UNAVAILABLE" else raw_state
                definition_version = (
                    raw.get("detector_version")
                    or raw.get("definition_version")
                    or "UNKNOWN"
                )
                observed_at = raw.get("observed_at") or decision.created_at
                if isinstance(observed_at, str):
                    try:
                        observed_at = datetime.fromisoformat(observed_at)
                    except ValueError:
                        observed_at = decision.created_at
                states.append(
                    {
                        "factor_id": str(factor_id),
                        "state": state,
                        "definition_version": str(definition_version),
                        "observed_at": observed_at,
                    }
                )
        return states

    async def _materialize_cards(
        self,
        *,
        episode_ids: set[str],
        known_at: datetime,
        fence: Fence,
    ) -> tuple[int, int, int]:
        if not episode_ids:
            return 0, 0, 0
        patterns = await self.store.current_patterns_for_scope(
            account_id=self.account_id,
            mode=self.mode,
            statuses=RETRIEVABLE_STATUSES,
        )
        materialized = 0
        retrievable = 0
        considered = 0
        for pattern in patterns:
            members = set(pattern.success_refs_json or []) | set(
                pattern.contrary_refs_json or []
            )
            if not members.intersection(episode_ids):
                continue
            considered += 1
            reviews = await self._load_pattern_review_attempts(members)
            factor_states = await self._factor_states_for_pattern(members, known_at)
            trigger = TriggerSignature.from_factor_states(
                factor_states, as_of=known_at
            )
            context = ContextSignature.from_market_state(
                {
                    "regime": pattern.regime or "UNKNOWN",
                    "trend_state": pattern.regime or "UNKNOWN",
                    "liquidity_state": "UNKNOWN",
                    "timeframe": "1d",
                    "direction": pattern.direction or "UNKNOWN",
                },
                as_of=known_at,
                symbol=pattern.symbol,
            )
            proposal = await self.card_learner.propose_from_pattern(
                pattern=pattern,
                reviews=reviews,
                trigger=trigger,
                context=context,
                rationale="CANONICAL_PATTERN_TO_EXPERIENCE_CARD",
                now=known_at,
            )
            guidance = dict(proposal.proposed_guidance or {})
            guidance.update(
                {
                    "proposition_key": (pattern.scope_json or {}).get(
                        "proposition_key"
                    ),
                    "regime": pattern.regime,
                    "direction": pattern.direction,
                    "evidence_domain": (pattern.features_json or {}).get(
                        "evidence_domain"
                    ),
                }
            )
            proposal.proposed_guidance = guidance
            proposal.account_id = pattern.account_id
            proposal.mode = pattern.mode
            proposal.share_scope = SHARE_SCOPE_ACCOUNT_MODE
            result = await self.card_store.apply(proposal, fence=fence, now=known_at)
            if result.created_rule_ids:
                materialized += 1
                if result.status in {"ACTIVE", "WATCH"}:
                    retrievable += 1
        return materialized, retrievable, considered
