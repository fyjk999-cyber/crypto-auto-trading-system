"""Growth-adaptive LLM budget policy tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_trader.llm_chief.growth_budget import (
    STAGE_EXPERIENCED,
    STAGE_EXPLORATION,
    STAGE_LEARNING,
    STAGE_MATURE,
    GrowthBudgetPolicy,
    GrowthMaturityFacts,
)


def test_exploration_when_episode_count_is_low():
    rec = GrowthBudgetPolicy().recommend(
        GrowthMaturityFacts(
            closed_episodes=10,
            validated_cards=0,
            natural_card_retrievals=0,
            factual_card_feedback=0,
            retrieval_hit_rate=None,
        )
    )
    # Zero retrievals means hit-rate is UNKNOWN, so the policy must not lower
    # the budget below EXPLORATION.
    assert rec.stage == STAGE_EXPLORATION
    assert rec.max_calls_per_window == 240


def test_learning_stage():
    rec = GrowthBudgetPolicy().recommend(
        GrowthMaturityFacts(
            closed_episodes=30,
            validated_cards=5,
            natural_card_retrievals=10,
            factual_card_feedback=5,
            retrieval_hit_rate=0.50,
        )
    )
    assert rec.stage == STAGE_LEARNING
    assert rec.max_calls_per_window == 180


def test_experienced_stage():
    rec = GrowthBudgetPolicy().recommend(
        GrowthMaturityFacts(
            closed_episodes=100,
            validated_cards=15,
            natural_card_retrievals=50,
            factual_card_feedback=20,
            retrieval_hit_rate=0.30,
        )
    )
    assert rec.stage == STAGE_EXPERIENCED
    assert rec.max_calls_per_window == 120


def test_mature_stage():
    rec = GrowthBudgetPolicy().recommend(
        GrowthMaturityFacts(
            closed_episodes=200,
            validated_cards=30,
            natural_card_retrievals=100,
            factual_card_feedback=50,
            retrieval_hit_rate=0.50,
        )
    )
    assert rec.stage == STAGE_MATURE
    assert rec.max_calls_per_window == 90


def test_unknown_maturity_never_downgrades_budget():
    rec = GrowthBudgetPolicy().recommend(
        GrowthMaturityFacts(
            closed_episodes=200,
            validated_cards=30,
            natural_card_retrievals=100,
            factual_card_feedback=50,
            retrieval_hit_rate=None,
        )
    )
    assert rec.stage == STAGE_EXPLORATION
    assert rec.max_calls_per_window == 240
    assert any("retrieval_hit_rate" in reason for reason in rec.reasons)


def test_unreadable_maturity_never_downgrades_budget():
    rec = GrowthBudgetPolicy().recommend(GrowthMaturityFacts())
    assert rec.stage == STAGE_EXPLORATION
    assert rec.max_calls_per_window == 240


def test_stage_dwell_and_one_level_downgrade():
    policy = GrowthBudgetPolicy()
    mature = policy.recommend(
        GrowthMaturityFacts(
            closed_episodes=200,
            validated_cards=30,
            natural_card_retrievals=100,
            factual_card_feedback=50,
            retrieval_hit_rate=0.50,
        )
    )
    now = datetime.now(UTC)
    held = policy.apply_dwell(
        mature,
        current_stage=STAGE_EXPLORATION,
        stage_started_at=now - timedelta(hours=1),
        now=now,
    )
    assert held.stage == STAGE_EXPLORATION
    stepped = policy.apply_dwell(
        mature,
        current_stage=STAGE_EXPLORATION,
        stage_started_at=now - timedelta(hours=48),
        now=now,
    )
    assert stepped.stage == STAGE_LEARNING
    assert stepped.max_calls_per_window == 180
