"""G12 attribution, KEEP/UPDATE/SPLIT/MERGE/RETIRE evolution tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from crypto_trader.learning.growth_attribution import (
    CardAttributionEngine,
    DailyCardLearner,
)
from crypto_trader.learning.growth_contracts import (
    ObservationFact,
    StructuredReview,
)
from crypto_trader.learning.growth_contracts import (
    TestableLesson as LessonSpec,
)
from crypto_trader.learning.growth_experience import AdaptiveCardStore
from crypto_trader.learning.growth_models import GrowthCardDecisionTraceORM
from crypto_trader.learning.growth_review import STATUS_SUCCEEDED, ReviewAttempt
from crypto_trader.learning.growth_v2_contracts import (
    OP_KEEP,
    OP_MERGE,
    OP_SPLIT,
    OP_UPDATE,
    STATUS_ACTIVE,
    STATUS_CANDIDATE,
    STATUS_RETIRED,
    STATUS_WATCH,
    CardUpdateProposal,
)
from crypto_trader.persistence.models import TradeEpisodeORM
from tests.growth_system_v2.conftest import market_context, seed_card, trigger

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def _episode(episode_id: str = "ep_1", *, net: str = "10") -> TradeEpisodeORM:
    closed = NOW
    return TradeEpisodeORM(
        episode_id=episode_id,
        trade_plan_id=f"plan_{episode_id}",
        symbol="BTCUSDT",
        direction="LONG",
        entry_decision_id=f"decision_{episode_id}",
        exit_decision_id=f"exit_{episode_id}",
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        opened_quantity=Decimal("1"),
        closed_quantity=Decimal("1"),
        leverage=Decimal("1"),
        fees=Decimal("0"),
        funding_pnl=Decimal("0"),
        gross_pnl=Decimal(net),
        net_pnl=Decimal(net),
        holding_time_seconds=60,
        entry_market_regime="BULL",
        terminal_reason="EXIT",
        factual=True,
        review_status="REVIEWED",
        opened_at=closed - timedelta(hours=1),
        closed_at=closed,
        fill_ids_json=[f"fill_{episode_id}"],
    )


def _review(
    episode_id: str = "ep_1",
    *,
    evidence_refs: list[str] | None = None,
    contrary_refs: list[str] | None = None,
) -> ReviewAttempt:
    lesson = LessonSpec(
        statement="Funding extreme association with trend continuation",
        testable_prediction="Future extreme funding in BULL continues.",
        scope={"scope": "SYMBOL_REGIME", "symbols": ["BTCUSDT"], "regimes": ["BULL"]},
        evidence_refs=evidence_refs or [f"episode:{episode_id}"],
        contrary_refs=contrary_refs or [],
        uncertainty="candidate",
        confidence="LOW",
    )
    review = StructuredReview(
        episode_id=episode_id,
        observation_facts=[
            ObservationFact(
                statement="Factual episode closed with fills.",
                evidence_refs=[f"episode:{episode_id}"],
            )
        ],
        testable_lessons=[lesson],
        applicability_scope={
            "scope": "SYMBOL_REGIME",
            "symbols": ["BTCUSDT"],
            "regimes": ["BULL"],
        },
    )
    return ReviewAttempt(
        status=STATUS_SUCCEEDED,
        attempt_id=f"attempt_{episode_id}",
        review=review,
        account_id="default",
        mode="PAPER",
        symbol="BTCUSDT",
        direction="LONG",
        regime="BULL",
        review_date="2026-09-10",
        input_hash=f"input_{episode_id}",
    )


def _trace(*selected_rule_ids: str, decision_id: str = "decision_ep_1"):
    return GrowthCardDecisionTraceORM(
        trace_id="trace_test",
        decision_id=decision_id,
        account_id="default",
        mode="PAPER",
        symbol="BTCUSDT",
        as_of=NOW,
        selected_card_refs_json=[f"card:{rule_id}:v1" for rule_id in selected_rule_ids],
        candidate_card_refs_json=[],
        excluded_card_refs_json=[],
        excluded_reasons_json={},
    )


async def test_win_without_card_relevant_evidence_is_keep_not_confidence_bump(v2_db):
    await seed_card(
        v2_db,
        rule_id="card_keep",
        status=STATUS_ACTIVE,
        source_ids=["ep_9"],
        support_ids=["ep_9"],
    )
    store = AdaptiveCardStore(v2_db.session_factory)
    card = await store.get_card("card_keep")
    engine = CardAttributionEngine()
    report = engine.attribute(
        episode=_episode("ep_9", net="100"),
        review=_review("ep_9", evidence_refs=["episode:other"]),
        trace=_trace("card_keep"),
        card=card,
        now=NOW,
        data_quality="COMPLETE",
    )
    assert report.causality == "OUTCOME_ASSOCIATED"
    assert report.proposal is not None and report.proposal.operation == OP_KEEP
    before = await store.get_card("card_keep")
    result = await store.apply(report.proposal)
    after = await store.get_card("card_keep")
    assert result.operation == OP_KEEP
    assert after.version == before.version
    assert after.support_count == before.support_count


async def test_loss_without_evidence_does_not_invalidate(v2_db):
    await seed_card(
        v2_db,
        rule_id="card_loss",
        status=STATUS_ACTIVE,
        source_ids=["ep_10"],
        support_ids=["ep_10"],
    )
    store = AdaptiveCardStore(v2_db.session_factory)
    card = await store.get_card("card_loss")
    report = CardAttributionEngine().attribute(
        episode=_episode("ep_10", net="-50"),
        review=_review("ep_10", evidence_refs=["episode:other"]),
        trace=_trace("card_loss"),
        card=card,
        now=NOW,
        data_quality="COMPLETE",
    )
    await store.apply(report.proposal)
    after = await store.get_card("card_loss")
    assert after.status == STATUS_ACTIVE
    assert after.version == card.version


async def test_contradiction_downgrades_without_invalidating(v2_db):
    await seed_card(
        v2_db,
        rule_id="card_contra",
        status=STATUS_ACTIVE,
        source_ids=["ep_1", "ep_2", "ep_3"],
        support_ids=["ep_1", "ep_2", "ep_3"],
    )
    store = AdaptiveCardStore(v2_db.session_factory)
    card = await store.get_card("card_contra")
    report = CardAttributionEngine(allow_retire_on_contradiction=False).attribute(
        episode=_episode("ep_1", net="-5"),
        review=_review("ep_1", evidence_refs=["episode:ep_1"], contrary_refs=["episode:ep_1"]),
        trace=_trace("card_contra"),
        card=card,
        now=NOW,
        data_quality="COMPLETE",
    )
    assert report.proposal is not None and report.proposal.operation == OP_UPDATE
    result = await store.apply(report.proposal)
    after = await store.get_card("card_contra")
    assert result.status == STATUS_WATCH
    assert after.status == STATUS_WATCH
    assert after.contradiction_count >= 1
    assert after.contradiction_count < after.support_count  # WATCH, not invalidation
    assert after.version == card.version + 1


async def test_support_update_promotes_candidate_and_records_version(v2_db):
    await seed_card(
        v2_db,
        rule_id="card_support",
        status=STATUS_CANDIDATE,
        source_ids=["ep_1"],
        support_ids=["ep_1"],
    )
    store = AdaptiveCardStore(v2_db.session_factory)
    card = await store.get_card("card_support")
    report = CardAttributionEngine().attribute(
        episode=_episode("ep_1", net="5"),
        review=_review("ep_1", evidence_refs=["episode:ep_1"]),
        trace=_trace("card_support"),
        card=card,
        now=NOW,
        data_quality="COMPLETE",
    )
    assert report.proposal is not None and report.proposal.operation == OP_UPDATE
    await store.apply(report.proposal)
    after = await store.get_card("card_support")
    assert after.version == 2
    history = await store.history("card_support")
    assert [row.version for row in history] == [1, 2]
    assert history[-1].snapshot_json["version"] == 2


async def test_split_preserves_parent_lineage_and_retires_parent(v2_db):
    await seed_card(
        v2_db,
        rule_id="card_split",
        status=STATUS_ACTIVE,
        source_ids=["ep_1", "ep_2", "ep_3"],
        support_ids=["ep_1", "ep_2", "ep_3"],
    )
    store = AdaptiveCardStore(v2_db.session_factory)
    card = await store.get_card("card_split")
    proposal = CardAttributionEngine().propose_split(
        card,
        [
            market_context(regime="BULL").to_json(),
            market_context(regime="RANGE").to_json(),
        ],
    )
    result = await store.apply(proposal)
    assert result.operation == OP_SPLIT and result.status == STATUS_RETIRED
    parent = await store.get_card("card_split")
    assert parent.status == STATUS_RETIRED
    assert len(result.created_rule_ids) == 2
    for child_id in result.created_rule_ids:
        child = await store.get_card(child_id)
        assert child.supersedes_rule_id == "card_split"
        assert child.supersedes_version == card.version
        assert child.trigger is not None


async def test_merge_requires_compatibility_and_preserves_sources_auditably(v2_db):
    await seed_card(
        v2_db,
        rule_id="card_merge_a",
        status=STATUS_ACTIVE,
        source_ids=["ep_1", "ep_2", "ep_3"],
        support_ids=["ep_1", "ep_2", "ep_3"],
    )
    await seed_card(
        v2_db,
        rule_id="card_merge_b",
        status=STATUS_ACTIVE,
        source_ids=["ep_4", "ep_5"],
        support_ids=["ep_4", "ep_5"],
    )
    store = AdaptiveCardStore(v2_db.session_factory)
    target = await store.get_card("card_merge_a")
    source = await store.get_card("card_merge_b")
    engine = CardAttributionEngine()
    proposal = engine.propose_merge(target, source)
    result = await store.apply(proposal)
    assert result.operation == OP_MERGE
    merged = await store.get_card("card_merge_a")
    assert merged is not None
    assert set(merged.source_episode_ids) >= {"ep_1", "ep_4"}
    assert (await store.get_card("card_merge_b")).status == STATUS_RETIRED

    # Incompatible guidance must refuse merge (never average conflicting rules).
    await seed_card(
        v2_db,
        rule_id="card_merge_c",
        status=STATUS_ACTIVE,
        guidance={"summary": "opposite", "direction": "SHORT"},
        source_ids=["ep_6", "ep_7", "ep_8"],
        support_ids=["ep_6", "ep_7", "ep_8"],
    )
    conflicting = await store.get_card("card_merge_c")
    with pytest.raises(ValueError):
        engine.propose_merge(await store.get_card("card_merge_a"), conflicting)


async def test_retire_is_auditable_and_not_retrieved(v2_db):
    from crypto_trader.learning.growth_card_retrieval import ExperienceCardRetriever

    await seed_card(v2_db, rule_id="card_retire_it", status=STATUS_ACTIVE)
    store = AdaptiveCardStore(v2_db.session_factory)
    proposal = CardUpdateProposal(
        operation="RETIRE",
        rationale="MANUAL_RETIRE",
        card_rule_id="card_retire_it",
        proposed_status=STATUS_RETIRED,
    ).finalize()
    await store.apply(proposal)
    card = await store.get_card("card_retire_it")
    assert card.status == STATUS_RETIRED
    history = await store.history("card_retire_it")
    assert history[-1].operation == "RETIRE"
    result = await ExperienceCardRetriever(v2_db.session_factory).retrieve(
        trigger=trigger(), context=market_context(), as_of=datetime.now(UTC)
    )
    assert result.selected == []


async def test_runtime_origin_cannot_write_cards(v2_db):
    learner = DailyCardLearner(v2_db.session_factory)
    with pytest.raises(PermissionError):
        await learner.learn_day(
            account_id="default",
            mode="PAPER",
            review_date="2026-09-10",
            origin="RUNTIME",
        )
