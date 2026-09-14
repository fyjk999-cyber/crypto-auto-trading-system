"""Phase B: Pattern -> factual review/evidence -> legitimate card closure."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.learning.growth_models import (
    GrowthPatternORM,
    GrowthReviewAttemptORM,
)
from crypto_trader.learning.growth_runtime_learning import (
    GrowthRuntimeLearningService,
)
from crypto_trader.persistence.models import (
    AICompressedExperienceORM,
    LLMDecisionORM,
    TradeEpisodeORM,
)

DAY = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
EPISODES = ["ep_b1", "ep_b2", "ep_b3"]


async def _true() -> bool:
    return True


def _episode(episode_id: str) -> TradeEpisodeORM:
    return TradeEpisodeORM(
        episode_id=episode_id,
        trade_plan_id=f"plan_{episode_id}",
        symbol="BTCUSDT",
        direction="LONG",
        entry_decision_id=f"decision_{episode_id}",
        exit_decision_id=None,
        order_ids_json=[],
        fill_ids_json=[f"fill_{episode_id}"],
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
        entry_market_regime="TRENDING",
        terminal_reason="EXIT",
        factual=True,
        review_status="REVIEWED",
        opened_at=DAY,
        closed_at=DAY,
    )


def _decision(episode_id: str, factor: dict) -> LLMDecisionORM:
    return LLMDecisionORM(
        decision_id=f"decision_{episode_id}",
        run_id="run_b",
        symbol="BTCUSDT",
        position_state="FLAT",
        action="LONG",
        model_provider="deepseek",
        model="deepseek-chat",
        model_version="0.1.0",
        prompt_version="canonical-1.0.0",
        market_regime="TRENDING",
        thesis="factual phase-b test decision",
        triggered_factors_json=[factor],
        factor_evidence_present=True,
        created_at=DAY,
    )


def _review(episode_id: str) -> GrowthReviewAttemptORM:
    return GrowthReviewAttemptORM(
        attempt_id=f"attempt_{episode_id}",
        review_date="2026-09-10",
        episode_id=episode_id,
        account_id="default",
        mode="PAPER",
        symbol="BTCUSDT",
        direction="LONG",
        profile_version="growth-review-v2",
        prompt_version="growth-review-prompt-v2",
        schema_version="growth-review-schema-v2",
        prompt_hash="p" * 64,
        schema_hash="s" * 64,
        input_hash=episode_id,
        status="SUCCEEDED",
        attempt_no=1,
        result_json={
            "episode_id": episode_id,
            "observation_facts": [
                {
                    "statement": "Factual fills and PnL lineage exist.",
                    "evidence_refs": [f"episode:{episode_id}"],
                }
            ],
            "testable_lessons": [
                {
                    "statement": "Momentum expansion continued in trend regime.",
                    "testable_prediction": "Comparable trend episodes continue.",
                    "scope": {"regime": "TRENDING", "direction": "LONG"},
                    "evidence_refs": [f"episode:{episode_id}"],
                    "confidence": "LOW",
                }
            ],
            "risk_rule_changes": [],
        },
        usage_status="KNOWN",
    )


def _pattern() -> GrowthPatternORM:
    return GrowthPatternORM(
        pattern_id="pattern_b1",
        version=1,
        account_id="default",
        mode="PAPER",
        symbol="BTCUSDT",
        regime="TRENDING",
        direction="LONG",
        pattern_key="default:PAPER:BTCUSDT:TRENDING:LONG",
        features_json={"evidence_domain": "PAPER"},
        scope_json={"proposition_key": "prop_b1", "evidence_domain": "PAPER"},
        sample_count=3,
        independent_sample_count=3,
        support_count=3,
        contrary_count=0,
        success_refs_json=list(EPISODES),
        contrary_refs_json=[],
        status="VALIDATED",
        status_reason="NO_CONTRARY_EPISODES",
        known_at=DAY,
    )


async def _seed(v2_db, *, with_reviews: bool, factor: dict) -> None:
    async with v2_db.session_factory() as session:
        session.add_all([_episode(eid) for eid in EPISODES])
        session.add_all([_decision(eid, factor) for eid in EPISODES])
        session.add(_pattern())
        if with_reviews:
            session.add_all([_review(eid) for eid in EPISODES])
        await session.commit()


def _service(v2_db) -> GrowthRuntimeLearningService:
    return GrowthRuntimeLearningService(
        v2_db.session_factory, provider=None, min_pattern_samples=3
    )


async def _materialize(v2_db) -> tuple[int, int, int]:
    service = _service(v2_db)
    return await service._materialize_cards(
        episode_ids=set(EPISODES), known_at=DAY, fence=_true
    )


async def _cards(v2_db) -> list[AICompressedExperienceORM]:
    async with v2_db.session_factory() as session:
        return list(
            (await session.execute(select(AICompressedExperienceORM))).scalars().all()
        )


async def test_pattern_with_valid_reviews_and_real_trigger_is_retrievable(v2_db):
    await _seed(
        v2_db,
        with_reviews=True,
        factor={
            "factor": "MOMENTUM_EXPANSION",
            "status": "TRIGGERED",
            "detector_version": "factors-v1",
            "observed_at": DAY.isoformat(),
        },
    )
    materialized, retrievable, considered = await _materialize(v2_db)
    assert considered == 1
    assert materialized == 1
    assert retrievable == 1
    cards = await _cards(v2_db)
    assert len(cards) == 1
    assert cards[0].status == "ACTIVE"
    assert cards[0].trigger_signature_json["factors"]


async def test_pattern_without_reviews_stays_candidate(v2_db):
    await _seed(
        v2_db,
        with_reviews=False,
        factor={
            "factor": "MOMENTUM_EXPANSION",
            "status": "TRIGGERED",
            "detector_version": "factors-v1",
            "observed_at": DAY.isoformat(),
        },
    )
    materialized, retrievable, _ = await _materialize(v2_db)
    assert materialized == 1
    assert retrievable == 0
    cards = await _cards(v2_db)
    assert cards[0].status == "CANDIDATE"


async def test_missing_trigger_metadata_is_not_fabricated(v2_db):
    await _seed(
        v2_db,
        with_reviews=True,
        factor={"factor": "MOMENTUM_EXPANSION", "strength": 1.0},
    )
    materialized, retrievable, _ = await _materialize(v2_db)
    assert materialized == 1
    assert retrievable == 0
    cards = await _cards(v2_db)
    assert cards[0].status == "CANDIDATE"
    factors = cards[0].trigger_signature_json["factors"]
    assert factors[0]["definition_version"] == "UNKNOWN"


async def test_materialize_cards_is_idempotent(v2_db):
    await _seed(
        v2_db,
        with_reviews=True,
        factor={
            "factor": "MOMENTUM_EXPANSION",
            "status": "TRIGGERED",
            "detector_version": "factors-v1",
            "observed_at": DAY.isoformat(),
        },
    )
    await _materialize(v2_db)
    await _materialize(v2_db)
    cards = await _cards(v2_db)
    assert len(cards) == 1
    async with v2_db.session_factory() as session:
        versions = (
            await session.execute(
                select(GrowthPatternORM.pattern_id).where(
                    GrowthPatternORM.pattern_id == "pattern_b1"
                )
            )
        ).all()
    assert versions


async def test_known_propositions_are_recalled_for_exact_same_scope(v2_db):
    from crypto_trader.learning.growth_models import GrowthLessonORM

    episode = _episode("ep_known")
    pattern = _pattern()
    lesson = GrowthLessonORM(
        lesson_id="lesson_known",
        version=1,
        source_kind="EPISODE",
        source_id="ep_known",
        account_id="default",
        mode="PAPER",
        symbol="BTCUSDT",
        direction="LONG",
        regime="TRENDING",
        statement="Momentum expansion continued in trend regime.",
        observation_refs_json=["episode:ep_known"],
        support_refs_json=["episode:ep_known"],
        contrary_refs_json=[],
        scope_json={"proposition_key": "prop_b1", "evidence_domain": "PAPER"},
        status="CANDIDATE",
        sample_count=1,
        independent_sample_count=1,
        known_at=DAY,
        created_at=DAY,
    )
    async with v2_db.session_factory() as session:
        session.add(pattern)
        session.add(lesson)
        await session.commit()

    service = GrowthRuntimeLearningService(
        v2_db.session_factory, provider=object()
    )
    known = await service._known_propositions_for(episode)
    assert len(known) == 1
    assert known[0].proposition_key == "prop_b1"
    assert known[0].statement == "Momentum expansion continued in trend regime."
    assert known[0].sample_count == 3


def test_review_prompt_requires_verbatim_known_proposition_reuse():
    from crypto_trader.learning.growth_contracts import (
        EpisodeReviewInput,
        KnownProposition,
    )
    from crypto_trader.learning.growth_review import StructuredReviewService

    payload = EpisodeReviewInput(
        episode_id="ep_prompt",
        account_id="default",
        mode="PAPER",
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        quantity=Decimal("1"),
        leverage=Decimal("1"),
        fees=Decimal("0"),
        gross_pnl=Decimal("1"),
        net_pnl=Decimal("1"),
        opened_at=DAY,
        closed_at=DAY,
        entry_market_regime="TRENDING",
        terminal_reason="EXIT",
        known_propositions=[
            KnownProposition(
                proposition_key="prop_b1",
                statement="Momentum expansion continued in trend regime.",
                symbol="BTCUSDT",
                regime="TRENDING",
                direction="LONG",
                sample_count=3,
                status="VALIDATED",
            )
        ],
    )
    service = StructuredReviewService(provider=None, session_factory=None)
    prompt = service.build_prompt(payload, allowed_refs={"episode:ep_prompt"})
    assert "KNOWN_PROPOSITIONS" in prompt
    assert "Momentum expansion continued in trend regime." in prompt
    assert "reuse its statement EXACTLY as written" in prompt
