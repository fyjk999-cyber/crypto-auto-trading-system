"""G14 closed growth loop: factual result → card update → retrieval → trace."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from crypto_trader.learning.growth_attribution import DailyCardLearner
from crypto_trader.learning.growth_card_retrieval import (
    CardDecisionTraceStore,
    ExperienceCardRetriever,
)
from crypto_trader.learning.growth_contracts import (
    ObservationFact,
    StructuredReview,
)
from crypto_trader.learning.growth_contracts import (
    TestableLesson as LessonSpec,
)
from crypto_trader.learning.growth_experience import AdaptiveCardStore
from crypto_trader.learning.growth_models import (
    GrowthCardDecisionTraceORM,
    GrowthPatternORM,
    GrowthReviewAttemptORM,
)
from crypto_trader.learning.growth_review import ReviewAttempt
from crypto_trader.persistence.models import FillORM, OrderORM, TradeEpisodeORM
from tests.growth_system_v2.conftest import market_context, trigger

DAY = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)


def _episode(episode_id: str, *, net: str) -> TradeEpisodeORM:
    return TradeEpisodeORM(
        episode_id=episode_id,
        trade_plan_id=f"plan_{episode_id}",
        symbol="BTCUSDT",
        direction="LONG",
        entry_decision_id=f"decision_{episode_id}",
        exit_decision_id=f"exit_{episode_id}",
        entry_price=Decimal("100"),
        exit_price=Decimal("102"),
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
        opened_at=DAY - timedelta(hours=1),
        closed_at=DAY,
        fill_ids_json=[f"fill_{episode_id}"],
    )


def _review_row(episode_id: str, *, contrary: bool) -> GrowthReviewAttemptORM:
    lesson = LessonSpec(
        statement="Funding extreme association with trend continuation",
        testable_prediction="Future comparable episodes continue.",
        scope={"scope": "SYMBOL_REGIME", "symbols": ["BTCUSDT"], "regimes": ["BULL"]},
        evidence_refs=[f"episode:{episode_id}"],
        contrary_refs=[f"episode:{episode_id}"] if contrary else [],
        uncertainty="candidate",
        confidence="LOW",
    )
    review = StructuredReview(
        episode_id=episode_id,
        observation_facts=[
            ObservationFact(
                statement="Factual fills exist.",
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
    return GrowthReviewAttemptORM(
        attempt_id=f"attempt_{episode_id}",
        review_date="2026-09-10",
        episode_id=episode_id,
        account_id="default",
        mode="PAPER",
        symbol="BTCUSDT",
        direction="LONG",
        profile_version="p1",
        prompt_version="v1",
        schema_version="v1",
        provider="test-double",
        input_hash=f"input_{episode_id}",
        prompt_hash="ph",
        schema_hash="sh",
        status="SUCCEEDED",
        attempt_no=1,
        result_json=review.model_dump(mode="json"),
        usage_status="KNOWN",
    )


def _trace(decision_id: str, rule_id: str, version: int) -> GrowthCardDecisionTraceORM:
    return GrowthCardDecisionTraceORM(
        trace_id=f"trace_{decision_id}",
        decision_id=decision_id,
        account_id="default",
        mode="PAPER",
        symbol="BTCUSDT",
        as_of=DAY,
        selected_card_refs_json=[f"card:{rule_id}:v{version}"],
        candidate_card_refs_json=[],
        excluded_card_refs_json=[],
        excluded_reasons_json={},
    )


async def test_closed_growth_loop_and_idempotent_revalidation(v2_db):
    learner = DailyCardLearner(v2_db.session_factory)
    store = AdaptiveCardStore(v2_db.session_factory)

    # 1-3: factual episodes + published pattern + structured reviews.
    ep1 = _episode("ep_1", net="10")
    ep2 = _episode("ep_2", net="12")
    ep3 = _episode("ep_3", net="-6")
    pattern = GrowthPatternORM(
        pattern_id="pattern_loop",
        version=1,
        account_id="default",
        mode="PAPER",
        symbol="BTCUSDT",
        regime="BULL",
        direction="LONG",
        pattern_key="default:PAPER:BTCUSDT:BULL:LONG",
        sample_count=3,
        independent_sample_count=3,
        support_count=3,
        contrary_count=0,
        success_refs_json=["ep_1", "ep_2", "ep_3"],
        contrary_refs_json=[],
        status="VALIDATED",
        status_reason="NO_CONTRARY_EPISODES",
        known_at=DAY,
    )
    review2 = _review_row("ep_2", contrary=False)
    review3 = _review_row("ep_3", contrary=True)
    async with v2_db.session_factory() as session:
        session.add_all([ep1, ep2, ep3, pattern, review2, review3])
        await session.commit()

    # 4: pattern → Experience Card (ACTIVE only because independent samples exist).
    proposal = await learner.propose_from_pattern(
        pattern=pattern,
        reviews=[
            ReviewAttempt(
                status="SUCCEEDED",
                attempt_id=review2.attempt_id,
                review=StructuredReview.model_validate(review2.result_json),
            )
        ],
        trigger=trigger(),
        context=market_context(),
        now=DAY,
    )
    created = await store.apply(proposal, now=DAY)
    card = await store.get_card(created.rule_id)
    assert card.status == "ACTIVE"
    assert card.sample_count == 3

    # 5: decision trace shows the card was actually used (v1).
    async with v2_db.session_factory() as session:
        session.add_all(
            [
                _trace("decision_ep_2", created.rule_id, 1),
                _trace("decision_ep_3", created.rule_id, 1),
            ]
        )
        await session.commit()

    # 6: next factual outcome (ep_3) contradicts the used card → WATCH/version+1.
    first = await learner.learn_day(
        account_id="default",
        mode="PAPER",
        review_date="2026-09-10",
        profile_version="p1",
        now=DAY,
    )
    assert first.attributed >= 1
    after_contradiction = await store.get_card(created.rule_id)
    assert after_contradiction.contradiction_count >= 1
    assert after_contradiction.status == "WATCH"
    version_after_contradiction = after_contradiction.version
    assert version_after_contradiction > card.version

    # 7: a later support episode cannot silently re-promote an unresolved WATCH,
    # but it must still be recorded as support and advance one version.
    async with v2_db.session_factory() as session:
        session.add(_review_row("ep_1", contrary=False))
        session.add(_trace("decision_ep_1", created.rule_id, version_after_contradiction))
        await session.commit()
    second = await learner.learn_day(
        account_id="default",
        mode="PAPER",
        review_date="2026-09-10",
        profile_version="p1",
        now=DAY + timedelta(hours=1),
    )
    assert second.attributed >= 1
    after_support = await store.get_card(created.rule_id)
    assert after_support.status == "WATCH"
    assert after_support.support_count >= 2

    # 8: replaying the same day is idempotent at the journal level.
    version_before_replay = after_support.version
    replay = await learner.learn_day(
        account_id="default",
        mode="PAPER",
        review_date="2026-09-10",
        profile_version="p1",
        now=DAY + timedelta(hours=2),
    )
    after_replay = await store.get_card(created.rule_id)
    assert after_replay.version == version_before_replay
    assert replay.mutations
    assert all(mutation.idempotent for mutation in replay.mutations)

    # 9: the next similar state retrieves the card as evidence with its version.
    retrieval = await ExperienceCardRetriever(v2_db.session_factory).retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=DAY + timedelta(hours=3),
    )
    assert retrieval.selected, retrieval.excluded_reasons
    assert retrieval.selected[0].rule_id == created.rule_id
    assert retrieval.selected[0].version == after_replay.version
    trace = await CardDecisionTraceStore(v2_db.session_factory).record(
        retrieval,
        decision_id="decision_next",
        evidence_package_id="package_next",
    )
    assert trace.selected_card_refs_json == [
        f"card:{created.rule_id}:v{after_replay.version}"
    ]

    # 10: the loop never creates risk/execution artifacts or fake episodes.
    async with v2_db.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(OrderORM)) == 0
        assert await session.scalar(select(func.count()).select_from(FillORM)) == 0
        assert await session.scalar(select(func.count()).select_from(TradeEpisodeORM)) == 3
