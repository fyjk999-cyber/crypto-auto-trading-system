"""Growth-adaptive LLM budget policy.

The policy maps factual Growth maturity to a *recommended* rolling-hour call
budget.  It is deliberately conservative:

* unknown/missing maturity data never lowers the budget;
* a stage downgrade is one level at a time and respects a minimum dwell time;
* P0/P1 safety capacity is never part of the adaptive reduction.  Mature
  systems should reduce repeated research first, not position management.

This module contains no trading, risk, sizing or execution authority.  It only
produces a recommendation that runtime bootstrap may use when constructing the
single ``GlobalLLMBudget`` authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from crypto_trader.learning.growth_models import (
    GrowthCardDecisionTraceORM,
    GrowthCardVersionORM,
)
from crypto_trader.persistence.models import TradeEpisodeORM

STAGE_EXPLORATION = "EXPLORATION"
STAGE_LEARNING = "LEARNING"
STAGE_EXPERIENCED = "EXPERIENCED"
STAGE_MATURE = "MATURE"

STAGE_BUDGETS: dict[str, int] = {
    STAGE_EXPLORATION: 240,
    STAGE_LEARNING: 180,
    STAGE_EXPERIENCED: 120,
    STAGE_MATURE: 90,
}

# Lower rank == higher budget.  Downgrades move one rank at a time.
STAGE_RANK: dict[str, int] = {
    STAGE_EXPLORATION: 0,
    STAGE_LEARNING: 1,
    STAGE_EXPERIENCED: 2,
    STAGE_MATURE: 3,
}

RETRIEVABLE_CARD_STATUSES = frozenset({"ACTIVE", "WATCH"})
MIN_STAGE_DWELL = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class GrowthMaturityFacts:
    """Factual Growth maturity counters used by the policy.

    ``None`` means UNKNOWN/UNREADABLE.  Unknown maturity must never be used to
    justify a lower budget.
    """

    closed_episodes: int | None = None
    validated_cards: int | None = None
    natural_card_retrievals: int | None = None
    factual_card_feedback: int | None = None
    retrieval_hit_rate: float | None = None
    growth_inconsistent: bool = False

    def unknown_fields(self) -> tuple[str, ...]:
        fields: list[str] = []
        for name in (
            "closed_episodes",
            "validated_cards",
            "natural_card_retrievals",
            "factual_card_feedback",
        ):
            if getattr(self, name) is None:
                fields.append(name)
        if self.retrieval_hit_rate is None:
            fields.append("retrieval_hit_rate")
        return tuple(fields)


@dataclass(frozen=True, slots=True)
class GrowthBudgetRecommendation:
    stage: str
    max_calls_per_window: int
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "growth_stage": self.stage,
            "recommended_max_calls": self.max_calls_per_window,
            "reasons": list(self.reasons),
        }


class GrowthBudgetPolicy:
    """Map factual Growth maturity to the recommended rolling-hour budget."""

    def __init__(self) -> None:
        self.stage_budgets = dict(STAGE_BUDGETS)

    def budget_for(self, stage: str) -> int:
        return self.stage_budgets.get(stage, STAGE_BUDGETS[STAGE_EXPLORATION])

    def recommend(self, facts: GrowthMaturityFacts) -> GrowthBudgetRecommendation:
        unknown = facts.unknown_fields()
        if unknown:
            # Unknown maturity must never reduce the budget.
            return GrowthBudgetRecommendation(
                STAGE_EXPLORATION,
                self.budget_for(STAGE_EXPLORATION),
                tuple(f"UNKNOWN_MATURITY_HOLD_BUDGET:{name}" for name in unknown),
            )
        assert facts.closed_episodes is not None
        assert facts.validated_cards is not None
        assert facts.natural_card_retrievals is not None
        assert facts.factual_card_feedback is not None
        assert facts.retrieval_hit_rate is not None

        episodes = facts.closed_episodes
        cards = facts.validated_cards
        retrievals = facts.natural_card_retrievals
        feedback = facts.factual_card_feedback
        hit_rate = facts.retrieval_hit_rate

        learning = episodes >= 30 and cards >= 5 and retrievals >= 10 and feedback >= 5
        experienced = (
            learning
            and episodes >= 100
            and cards >= 15
            and retrievals >= 50
            and feedback >= 20
            and hit_rate >= 0.30
        )
        mature = (
            experienced
            and episodes >= 200
            and cards >= 30
            and retrievals >= 100
            and feedback >= 50
            and hit_rate >= 0.50
            and not facts.growth_inconsistent
        )

        if mature:
            stage = STAGE_MATURE
        elif experienced:
            stage = STAGE_EXPERIENCED
        elif learning:
            stage = STAGE_LEARNING
        else:
            stage = STAGE_EXPLORATION
        return GrowthBudgetRecommendation(stage, self.budget_for(stage), ())

    def apply_dwell(
        self,
        recommendation: GrowthBudgetRecommendation,
        *,
        current_stage: str | None,
        stage_started_at: datetime | None = None,
        now: datetime | None = None,
    ) -> GrowthBudgetRecommendation:
        """Apply minimum dwell and one-level-at-a-time downgrade rules."""

        if current_stage is None:
            return recommendation
        current_rank = STAGE_RANK.get(current_stage, 0)
        proposed_rank = STAGE_RANK.get(recommendation.stage, 0)
        if proposed_rank <= current_rank:
            # Upgrade or same stage: no dwell restriction.
            return recommendation
        if (
            stage_started_at is not None
            and (now or datetime.now(UTC)) - stage_started_at < MIN_STAGE_DWELL
        ):
            return GrowthBudgetRecommendation(
                current_stage,
                self.budget_for(current_stage),
                ("STAGE_DWELL_HOLD:24H",),
            )
        # A downgrade may move only one maturity level at a time.
        target_rank = min(proposed_rank, current_rank + 1)
        target_stage = next(
            stage for stage, rank in STAGE_RANK.items() if rank == target_rank
        )
        reasons = tuple(recommendation.reasons) + ("DOWNGRADE_ONE_LEVEL_AT_A_TIME",)
        return GrowthBudgetRecommendation(
            target_stage, self.budget_for(target_stage), reasons
        )


async def load_growth_maturity_facts(session_factory) -> GrowthMaturityFacts:
    """Load factual maturity counters; UNKNOWN on any read failure.

    Reads are read-only and never mutate Growth state.  ``retrieval_hit_rate``
    is only computed when at least one natural retrieval is known, preventing
    an unknown denominator from producing a fabricated downgrade signal.
    """

    try:
        async with session_factory() as session:
            closed_episodes = await session.scalar(
                select(func.count())
                .select_from(TradeEpisodeORM)
                .where(TradeEpisodeORM.factual.is_(True))
            )
            validated_cards = await session.scalar(
                select(func.count(func.distinct(GrowthCardVersionORM.card_rule_id)))
                .where(GrowthCardVersionORM.status.in_(tuple(RETRIEVABLE_CARD_STATUSES)))
            )
            trace_rows = (
                await session.execute(
                    select(
                        GrowthCardDecisionTraceORM.decision_id,
                        GrowthCardDecisionTraceORM.selected_card_refs_json,
                    )
                )
            ).all()
            retrieval_decision_ids = [
                str(decision_id)
                for decision_id, selected in trace_rows
                if decision_id and selected
            ]
            natural_card_retrievals = len(retrieval_decision_ids)
            factual_card_feedback = 0
            if retrieval_decision_ids:
                factual_card_feedback = (
                    await session.scalar(
                        select(func.count(func.distinct(TradeEpisodeORM.episode_id))).where(
                            or_(
                                TradeEpisodeORM.entry_decision_id.in_(
                                    retrieval_decision_ids
                                ),
                                TradeEpisodeORM.exit_decision_id.in_(
                                    retrieval_decision_ids
                                ),
                            )
                        )
                    )
                    or 0
                )
            retrieval_hit_rate = (
                factual_card_feedback / natural_card_retrievals
                if natural_card_retrievals
                else None
            )
            return GrowthMaturityFacts(
                closed_episodes=int(closed_episodes or 0),
                validated_cards=int(validated_cards or 0),
                natural_card_retrievals=natural_card_retrievals,
                factual_card_feedback=int(factual_card_feedback),
                retrieval_hit_rate=retrieval_hit_rate,
            )
    except Exception:
        return GrowthMaturityFacts()
