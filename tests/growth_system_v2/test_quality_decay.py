"""G13 quality / decay / status-transition tests."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

from crypto_trader.learning.growth_card_quality import (
    CardQualityPolicy,
    assess_card_quality,
)
from crypto_trader.learning.growth_v2_contracts import (
    STATUS_ACTIVE,
    STATUS_CANDIDATE,
    STATUS_RETIRED,
    STATUS_STALE,
    STATUS_WATCH,
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def _assess(**overrides):
    values = dict(
        knowledge_id="card_x",
        sample_count=3,
        support_count=3,
        contradiction_count=0,
        trigger_complete=True,
        regime_known=True,
        evidence_quality=1.0,
        regime_consistency=1.0,
        repeatability=1.0,
        confidence_input=0.8,
        now=NOW,
        last_validated_at=NOW - timedelta(days=1),
    )
    values.update(overrides)
    return assess_card_quality(**values)


def test_confidence_signature_has_no_pnl_or_win_rate():
    parameters = set(inspect.signature(assess_card_quality).parameters)
    assert not {"net_pnl", "pnl", "win_rate", "wins", "profit"} & parameters
    assessment = _assess()
    assert "base_governor_score" in assessment.axes
    assert "contradiction_rate" in assessment.axes
    assert assessment.performance_change_status == "UNKNOWN"


def test_insufficient_data_stays_candidate():
    assessment = _assess(sample_count=1, support_count=1, repeatability=1.0)
    assert assessment.promotion_ready is False
    assert assessment.status == STATUS_CANDIDATE
    assert assessment.confidence_level == "INSUFFICIENT_DATA"
    assert "INSUFFICIENT_SAMPLES" in assessment.reasons


def test_repeatable_supported_card_promotes_active():
    assessment = _assess(sample_count=12, confidence_input=0.8)
    assert assessment.promotion_ready is True
    assert assessment.status == STATUS_ACTIVE
    assert assessment.confidence_level in {"MEDIUM", "HIGH"}


def test_contradiction_rate_downgrades_to_watch():
    assessment = _assess(
        sample_count=4, support_count=3, contradiction_count=2, repeatability=0.6
    )
    assert assessment.status in {STATUS_WATCH, STATUS_STALE}
    assert assessment.confidence_level == "LOW_CONFIDENCE"
    assert "CONTRADICTION_RATE_HIGH" in assessment.reasons


def test_decay_transitions_are_explicit_and_reversible_policy():
    healthy = _assess(
        sample_count=4,
        support_count=4,
        contradiction_count=0,
        last_validated_at=NOW - timedelta(days=1),
    )
    assert healthy.health.status in {"VALID", "AGING"}
    assert healthy.status in {STATUS_ACTIVE, STATUS_WATCH}

    degraded = _assess(
        sample_count=4,
        support_count=2,
        contradiction_count=2,
        repeatability=0.5,
        regime_consistency=0.0,
        last_validated_at=NOW - timedelta(days=120),
    )
    assert degraded.health.status in {"INVALID", "DEGRADED"}
    assert degraded.status == STATUS_STALE  # default policy never auto-retires
    assert degraded.health.decay_score > 0

    retiring = assess_card_quality(
        knowledge_id="card_x",
        sample_count=4,
        support_count=1,
        contradiction_count=3,
        trigger_complete=True,
        regime_known=True,
        evidence_quality=0.5,
        regime_consistency=0.0,
        repeatability=0.25,
        confidence_input=0.2,
        now=NOW,
        last_validated_at=NOW - timedelta(days=120),
        policy=CardQualityPolicy(retire_on_invalid=True),
    )
    assert retiring.status == STATUS_RETIRED


async def test_decay_history_is_not_deleted(v2_db):
    """Status transitions keep every prior snapshot for audit."""
    from crypto_trader.learning.growth_experience import AdaptiveCardStore
    from crypto_trader.learning.growth_v2_contracts import CardUpdateProposal
    from tests.growth_system_v2.conftest import seed_card

    await seed_card(v2_db, rule_id="card_decay_history", status="ACTIVE")
    store = AdaptiveCardStore(v2_db.session_factory)
    for status in (STATUS_WATCH, STATUS_STALE, STATUS_RETIRED):
        proposal = CardUpdateProposal(
            operation="WATCH" if status == STATUS_WATCH else "RETIRE",
            rationale=f"TEST_{status}",
            card_rule_id="card_decay_history",
            proposed_status=status,
        ).finalize()
        await store.apply(proposal)
    history = await store.history("card_decay_history")
    assert [row.version for row in history] == [1, 2, 3, 4]
    assert {row.status for row in history} >= {
        STATUS_ACTIVE,
        STATUS_WATCH,
        STATUS_STALE,
        STATUS_RETIRED,
    }
    assert history[0].snapshot_json["status"] == STATUS_ACTIVE
