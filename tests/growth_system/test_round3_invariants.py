"""Round-3 reviewer counterexample regressions (F01/F02/F04/F05/F06/F10/F11)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from crypto_trader.learning.growth_experience import ClaimLostError
from crypto_trader.learning.growth_knowledge import (
    PATTERN_CANDIDATE,
    PATTERN_STAGED,
    RETRIEVABLE_STATUSES,
    GrowthKnowledgePublisher,
)
from crypto_trader.learning.growth_models import (
    GrowthLessonORM,
    GrowthPatternORM,
    create_growth_schema,
)
from crypto_trader.learning.growth_retrieval import GrowthContextLoader, ToolBudget
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.persistence.models import AICompressedExperienceORM, DailyReviewRunORM
from tests.growth_system.test_round2_publication_semantics import (
    DATE,
    KNOWN_AT,
    REGIME,
    STATEMENT_A,
    STATEMENT_B,
    SYMBOL,
    _attempt,
    _binding,
)


@pytest.fixture
async def growth_db(database):
    await create_growth_schema(database.engine)
    return database


@pytest.fixture
def publisher(growth_db):
    return GrowthKnowledgePublisher(growth_db.session_factory, min_pattern_samples=3)


async def test_f01_stale_staging_never_reaches_authoritative_aggregation(
    growth_db, publisher
):
    attempts = [_attempt("stale_0"), _attempt("stale_1")]
    bindings = {row.review.episode_id: _binding() for row in attempts}
    async with growth_db.session_factory() as session:
        session.add(
            DailyReviewRunORM(
                review_date=DATE,
                status="RUNNING",
                claim_token="dead-token",
                owner="worker",
                claim_deadline_at=KNOWN_AT - timedelta(seconds=1),
                attempt_count=1,
            )
        )
        await session.commit()
    with pytest.raises(ClaimLostError):
        await publisher.publish_attempts(
            attempts, bindings=bindings, known_at=KNOWN_AT,
            claim_context=(DATE, "dead-token", "worker"),
        )
    fresh = _attempt("fresh_0")
    await publisher.publish_attempts(
        [fresh], bindings={"fresh_0": _binding()}, known_at=KNOWN_AT
    )
    authoritative = await publisher.store.current_patterns_for_scope(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
    )
    assert len(authoritative) == 1
    assert authoritative[0].sample_count == 1
    assert authoritative[0].status == PATTERN_CANDIDATE
    async with growth_db.session_factory() as session:
        staged = (
            await session.execute(
                select(GrowthPatternORM).where(GrowthPatternORM.status == PATTERN_STAGED)
            )
        ).scalars().all()
    assert staged  # isolated versions, never aggregated or visible


async def test_f05_operator_propositions_do_not_collide(growth_db, publisher):
    statements = [
        "RSI > 70 predicts reversal",
        "RSI > 70 predicts reversal",
        "RSI < 70 predicts reversal",
    ]
    attempts = [_attempt(f"operator_{i}", statement=s) for i, s in enumerate(statements)]
    await publisher.publish_attempts(
        attempts,
        bindings={row.review.episode_id: _binding() for row in attempts},
        known_at=KNOWN_AT,
    )
    assert (
        await publisher.store.current_patterns_for_scope(
            account_id="default",
            mode="PAPER",
            symbol=SYMBOL,
            regime=REGIME,
            statuses=RETRIEVABLE_STATUSES,
        )
        == []
    )


async def _seed_unrelated_candidate(growth_db, publisher):
    for index in range(3):
        await publisher.publish_review(
            attempt=_attempt(f"normal_{index}", statement=STATEMENT_A),
            binding=_binding(),
            known_at=KNOWN_AT,
        )
    pattern = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )
    )[0]
    proposition_b = "prop_unrelated_b"
    async with growth_db.session_factory() as session:
        session.add(
            GrowthLessonORM(
                lesson_id="lesson_unrelated_b",
                version=1,
                source_kind="EPISODE",
                source_id=(pattern.success_refs_json or ["normal_0"])[0],
                episode_id=(pattern.success_refs_json or ["normal_0"])[0],
                account_id="default",
                mode="PAPER",
                symbol=SYMBOL,
                direction="LONG",
                regime=REGIME,
                statement=STATEMENT_B,
                observation_refs_json=[],
                support_refs_json=[],
                contrary_refs_json=[],
                scope_json={"proposition_key": proposition_b},
                status="CANDIDATE",
                sample_count=1,
                known_at=KNOWN_AT,
            )
        )
        await session.commit()
    return pattern, proposition_b


async def test_f06_f10_compression_and_revoke_use_exact_proposition(
    growth_db, publisher
):
    pattern, _ = await _seed_unrelated_candidate(growth_db, publisher)
    compression = await publisher.compress(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
    )
    assert compression is not None
    assert STATEMENT_B not in compression.content
    await publisher.revoke(
        kind="pattern", logical_id=pattern.pattern_id, reason="F10", at=KNOWN_AT
    )
    lessons = await publisher.store.current_lessons_for_scope(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
    )
    unrelated = [row for row in lessons if row.statement == STATEMENT_B]
    assert unrelated and unrelated[0].status == "CANDIDATE"


async def test_f11_compression_history_survives_later_revocation(growth_db, publisher):
    for index in range(3):
        await publisher.publish_review(
            attempt=_attempt(f"hist_{index}", statement=STATEMENT_A),
            binding=_binding(),
            known_at=KNOWN_AT,
        )
    compression = await publisher.compress(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME,
        known_at=KNOWN_AT,
    )
    as_of = KNOWN_AT + timedelta(minutes=30)
    before = await publisher.list_published_compressions(
        account_id="default", mode="PAPER", as_of=as_of
    )
    assert before
    await publisher.revoke(
        kind="compression",
        logical_id=compression.compression_id,
        reason="F11",
        at=KNOWN_AT + timedelta(hours=2),
    )
    after = await publisher.list_published_compressions(
        account_id="default", mode="PAPER", as_of=as_of
    )
    assert [(row.compression_id, row.status) for row in after] == [
        (row.compression_id, row.status) for row in before
    ]


async def test_f02_legacy_card_tool_fails_closed_for_foreign_scope(growth_db):
    async with growth_db.session_factory() as session:
        session.add(
            AICompressedExperienceORM(
                rule_id="foreign_live_retired",
                symbol=SYMBOL,
                title="foreign",
                content="leak",
                source_episode_count=1,
                account_id="foreign",
                mode="LIVE",
                status="RETIRED",
                applicability_scope_json={
                    "scope": "SYMBOL",
                    "symbols": [SYMBOL],
                },
                created_at=KNOWN_AT - timedelta(days=1),
            )
        )
        await session.commit()
    from crypto_trader.llm.tools.context import register_context_tools
    from crypto_trader.llm.tools.registry import LLMToolRegistry

    # F02 is about the legacy canonical path: use ChiefContextLoader there.
    from crypto_trader.llm_chief.context_loader import ChiefContextLoader

    registry = LLMToolRegistry()
    register_context_tools(registry, ChiefContextLoader(growth_db.session_factory))
    context = ChiefTraderContext(
        symbol=SYMBOL,
        market_snapshot={},
        regime=REGIME,
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        prepared_at=KNOWN_AT.isoformat(),
    )
    evidence = await registry.call(
        "memory_search",
        SYMBOL,
        {
            "chief_context": context,
            "as_of": KNOWN_AT,
            "account_id": "default",
            "mode": "PAPER",
        },
    )
    assert evidence.source_refs == []
    assert evidence.data_quality == "NO_MATCHES"


async def test_f04_impossible_budget_is_explicit_configuration_failure(
    growth_db, publisher
):
    loader = GrowthContextLoader(
        growth_db.session_factory, budget=ToolBudget(token_budget=1)
    )
    from crypto_trader.llm.tools.registry import EvidenceBudgetConfigurationError

    with pytest.raises(EvidenceBudgetConfigurationError):
        await loader.load_tool(
            "memory_search",
            ChiefTraderContext(
                symbol=SYMBOL,
                market_snapshot={},
                regime=REGIME,
                quant_evidence=[],
                portfolio_state={},
                risk_summary={},
                prepared_at=KNOWN_AT.isoformat(),
            ),
            as_of=KNOWN_AT,
        )
