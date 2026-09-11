"""Round-2 retrieval scope/budget regressions (R12-R13)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from crypto_trader.learning.growth_contracts import (
    ObservationFact,
    StructuredReview,
)
from crypto_trader.learning.growth_contracts import (
    TestableLesson as LessonSpec,
)
from crypto_trader.learning.growth_knowledge import (
    EpisodeBinding,
    GrowthKnowledgePublisher,
)
from crypto_trader.learning.growth_models import create_growth_schema
from crypto_trader.learning.growth_retrieval import (
    GrowthContextLoader,
    ToolBudget,
)
from crypto_trader.learning.growth_review import (
    STATUS_SUCCEEDED,
    ReviewAttempt,
)
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.persistence.models import AICoinProfileORM

SYMBOL = "BTCUSDT"
REGIME = "TREND"
AS_OF = datetime(2026, 9, 9, 12, tzinfo=UTC)


@pytest.fixture
async def growth_db(database):
    await create_growth_schema(database.engine)
    return database


def _binding(account_id: str = "default") -> EpisodeBinding:
    return EpisodeBinding(
        account_id=account_id,
        mode="PAPER",
        currency="USDT",
        instrument_id=SYMBOL,
        source_revision="src-df55b11",
        regime=REGIME,
        direction="LONG",
    )


def _attempt(episode_id: str, statement: str) -> ReviewAttempt:
    lesson = LessonSpec(
        statement=statement,
        testable_prediction="Future comparable episodes show the same association.",
        scope={"scope": "SYMBOL_REGIME", "symbols": [SYMBOL], "regimes": [REGIME]},
        evidence_refs=[f"episode:{episode_id}"],
        contrary_refs=[],
        uncertainty="candidate",
        confidence="LOW",
    )
    review = StructuredReview(
        episode_id=episode_id,
        observation_facts=[
            ObservationFact(
                statement="The episode closed with complete fills.",
                evidence_refs=[f"episode:{episode_id}"],
            )
        ],
        testable_lessons=[lesson],
        applicability_scope={
            "scope": "SYMBOL_REGIME",
            "symbols": [SYMBOL],
            "regimes": [REGIME],
        },
    )
    return ReviewAttempt(
        status=STATUS_SUCCEEDED,
        attempt_id=f"attempt_{episode_id}",
        review=review,
        account_id="default",
        mode="PAPER",
        symbol=SYMBOL,
        direction="LONG",
        regime=REGIME,
        currency="USDT",
        review_date="2026-09-09",
        input_hash=f"input_{episode_id}",
    )


def _context() -> ChiefTraderContext:
    return ChiefTraderContext(
        symbol=SYMBOL,
        market_snapshot={},
        regime=REGIME,
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        prepared_at=AS_OF.isoformat(),
    )


async def test_t18_ambiguous_coin_profile_never_crosses_account_scope(growth_db):
    async with growth_db.session_factory() as session:
        session.add(
            AICoinProfileORM(
                symbol=SYMBOL,
                sample_count=3,
                profile_summary="Symbol-only profile without account/mode provenance.",
                behavior_tags_json=["EVIDENCE_BASED_PROFILE"],
                best_setups_json=[],
                worst_setups_json=[],
                version=1,
                updated_at=AS_OF,
            )
        )
        await session.commit()
    for account_id in ("acct-a", "acct-b"):
        loader = GrowthContextLoader(
            growth_db.session_factory, account_id=account_id, mode="PAPER"
        )
        evidence = await loader.load_tool("coin_profile", _context(), as_of=AS_OF)
        assert evidence.source_refs == []
        assert evidence.data_quality == "NO_MATCHES"
        assert evidence.features["scope_unavailable"] is True


async def test_t19_final_serialized_growth_evidence_respects_hard_budget(growth_db):
    publisher = GrowthKnowledgePublisher(
        growth_db.session_factory, min_pattern_samples=3
    )
    statement = (
        "Volume expansion with falling realized volatility preceded the continuation; "
        "this statement is intentionally long enough to consume serialized budget."
    )
    for index in range(8):
        await publisher.publish_review(
            attempt=_attempt(f"bounded_{index}", statement),
            binding=_binding(),
            known_at=AS_OF,
        )
    loader = GrowthContextLoader(
        growth_db.session_factory,
        budget=ToolBudget(limit=99, token_budget=120),
    )
    assert loader.budget.limit == 5
    evidence = await loader.load_tool("memory_search", _context(), as_of=AS_OF)
    assert loader._serialized_cost(evidence) <= 120
    assert len(evidence.features.get("lessons", [])) <= 5
    assert len(evidence.features.get("patterns", [])) <= 5
