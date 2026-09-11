"""Runtime read vs Daily-Review write separation + durability tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from crypto_trader.learning.growth_attribution import DailyCardLearner
from crypto_trader.learning.growth_card_retrieval import (
    ExperienceCardRetriever,
    register_experience_card_tool,
)
from crypto_trader.learning.growth_experience import AdaptiveCardStore
from crypto_trader.learning.growth_models import (
    GrowthCardDecisionTraceORM,
    GrowthCardVersionORM,
    GrowthReviewAttemptORM,
)
from crypto_trader.learning.growth_v2_contracts import (
    CardUpdateProposal,
)
from crypto_trader.llm.tools.registry import LLMToolRegistry
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.persistence.models import FillORM, OrderORM, TradeEpisodeORM
from tests.growth_system_v2.conftest import AS_OF, market_context, seed_card

DAY = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)


async def test_runtime_reads_card_but_cannot_mutate_it(v2_db):
    await seed_card(v2_db, rule_id="card_rw", status="ACTIVE")
    store = AdaptiveCardStore(v2_db.session_factory)
    before = await store.get_card("card_rw")
    retriever = ExperienceCardRetriever(v2_db.session_factory)
    registry = LLMToolRegistry()
    register_experience_card_tool(registry, retriever)
    evidence = await registry.call(
        "experience_cards",
        "BTCUSDT",
        {
            "as_of": AS_OF,
            "chief_context": ChiefTraderContext(
                symbol="BTCUSDT",
                market_snapshot={},
                regime="BULL",
                quant_evidence=[],
                portfolio_state={},
                risk_summary={},
                prepared_at=AS_OF.isoformat(),
            ),
            "factor_states": [
                {
                    "factor_id": "funding_rate",
                    "state": "EXTREME_HIGH",
                    "definition_version": "funding-def-v1",
                },
                {
                    "factor_id": "open_interest",
                    "state": "RISING",
                    "definition_version": "oi-def-v1",
                },
            ],
            "market_state": market_context().to_json(),
        },
    )
    assert evidence.source_refs
    after = await store.get_card("card_rw")
    assert after.version == before.version
    assert after.status == before.status
    async with v2_db.session_factory() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(GrowthCardVersionORM)
            )
        ) == len(await store.history("card_rw"))


async def test_daily_review_path_can_update_cards(v2_db):
    from crypto_trader.learning.growth_contracts import (
        ObservationFact,
        StructuredReview,
    )
    from crypto_trader.learning.growth_contracts import (
        TestableLesson as LessonSpec,
    )

    await seed_card(
        v2_db,
        rule_id="card_daily_update",
        status="WATCH",
        source_ids=["ep_day"],
        support_ids=["ep_day"],
    )
    lesson = LessonSpec(
        statement="Support evidence for the card",
        testable_prediction="Same association repeats.",
        evidence_refs=["episode:ep_day"],
        contrary_refs=[],
        uncertainty="candidate",
        confidence="LOW",
    )
    review = StructuredReview(
        episode_id="ep_day",
        observation_facts=[
            ObservationFact(statement="Factual close.", evidence_refs=["episode:ep_day"])
        ],
        testable_lessons=[lesson],
        applicability_scope={"scope": "SYMBOL_REGIME"},
    )
    episode = TradeEpisodeORM(
        episode_id="ep_day",
        trade_plan_id="plan_ep_day",
        symbol="BTCUSDT",
        direction="LONG",
        entry_decision_id="decision_ep_day",
        exit_decision_id="exit_ep_day",
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        opened_quantity=Decimal("1"),
        closed_quantity=Decimal("1"),
        leverage=Decimal("1"),
        fees=Decimal("0"),
        funding_pnl=Decimal("0"),
        gross_pnl=Decimal("1"),
        net_pnl=Decimal("1"),
        holding_time_seconds=60,
        entry_market_regime="BULL",
        terminal_reason="EXIT",
        factual=True,
        review_status="REVIEWED",
        opened_at=DAY - timedelta(hours=1),
        closed_at=DAY,
    )
    attempt = GrowthReviewAttemptORM(
        attempt_id="attempt_ep_day",
        review_date="2026-09-10",
        episode_id="ep_day",
        account_id="default",
        mode="PAPER",
        symbol="BTCUSDT",
        direction="LONG",
        profile_version="p1",
        prompt_version="v1",
        schema_version="v1",
        provider="test-double",
        input_hash="input_ep_day",
        prompt_hash="ph",
        schema_hash="sh",
        status="SUCCEEDED",
        attempt_no=1,
        result_json=review.model_dump(mode="json"),
    )
    trace = GrowthCardDecisionTraceORM(
        trace_id="trace_ep_day",
        decision_id="decision_ep_day",
        account_id="default",
        mode="PAPER",
        symbol="BTCUSDT",
        as_of=DAY,
        selected_card_refs_json=["card:card_daily_update:v1"],
        candidate_card_refs_json=[],
        excluded_card_refs_json=[],
        excluded_reasons_json={},
    )
    async with v2_db.session_factory() as session:
        session.add_all([episode, attempt, trace])
        await session.commit()
    store = AdaptiveCardStore(v2_db.session_factory)
    before = await store.get_card("card_daily_update")
    report = await DailyCardLearner(v2_db.session_factory).learn_day(
        account_id="default",
        mode="PAPER",
        review_date="2026-09-10",
        profile_version="p1",
        now=DAY,
    )
    after = await store.get_card("card_daily_update")
    assert report.mutations
    assert after.version > before.version
    # No execution/risk artifacts from the write path either.
    async with v2_db.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(OrderORM)) == 0
        assert await session.scalar(select(func.count()).select_from(FillORM)) == 0


async def test_fence_loss_blocks_card_mutation(v2_db):
    from crypto_trader.learning.growth_experience import ClaimLostError

    await seed_card(v2_db, rule_id="card_fence", status="ACTIVE")
    store = AdaptiveCardStore(v2_db.session_factory)
    before = await store.get_card("card_fence")

    async def lost_claim() -> bool:
        return False

    proposal = CardUpdateProposal(
        operation="UPDATE",
        rationale="FENCE_TEST",
        card_rule_id="card_fence",
        supporting_episode_ids=["ep_fence"],
        source_episode_ids=["ep_fence"],
    ).finalize()
    with pytest.raises(ClaimLostError):
        await store.apply(proposal, fence=lost_claim, now=DAY)
    after = await store.get_card("card_fence")
    assert after.version == before.version


async def test_restart_replay_does_not_double_update(v2_db):
    await seed_card(v2_db, rule_id="card_replay", status="ACTIVE")
    store = AdaptiveCardStore(v2_db.session_factory)
    proposal = CardUpdateProposal(
        operation="UPDATE",
        rationale="REPLAY_TEST",
        card_rule_id="card_replay",
        supporting_episode_ids=["ep_replay"],
        source_episode_ids=["ep_replay"],
    ).finalize()
    first = await store.apply(proposal, now=DAY)
    second = await store.apply(proposal, now=DAY + timedelta(minutes=5))
    assert second.idempotent is True
    assert second.version == first.version
    history = await store.history("card_replay")
    assert sum(row.operation == "UPDATE" for row in history) == 1
