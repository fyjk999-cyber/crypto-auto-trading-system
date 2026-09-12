"""Round-4 six-blocker adversarial regressions (T01-T10)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from crypto_trader.learning.growth_knowledge import (
    GrowthKnowledgePublisher,
)
from crypto_trader.learning.growth_models import create_growth_schema
from crypto_trader.learning.growth_retrieval import GrowthContextLoader, ToolBudget
from crypto_trader.llm.tools.context import register_context_tools
from crypto_trader.llm.tools.registry import (
    EvidenceBudgetConfigurationError,
    LLMToolRegistry,
)
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.context_loader import ChiefContextLoader
from crypto_trader.persistence.models import AICompressedExperienceORM
from tests.growth_system.test_round2_publication_semantics import (
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


def _context() -> ChiefTraderContext:
    return ChiefTraderContext(
        symbol=SYMBOL,
        market_snapshot={},
        regime=REGIME,
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        prepared_at=KNOWN_AT.isoformat(),
    )


async def _publish_attempts(publisher, attempts):
    await publisher.publish_attempts(
        attempts,
        bindings={row.review.episode_id: _binding() for row in attempts},
        known_at=KNOWN_AT,
    )


async def test_t01_contrary_reconciles_all_exact_proposition_lessons(
    growth_db, publisher
):
    attempts = [_attempt(f"t01_a{index}") for index in range(3)] + [
        _attempt("t01_contrary", contrary_refs=["episode:t01_contrary"])
    ]
    await _publish_attempts(publisher, attempts)
    patterns = await publisher.store.current_patterns_for_scope(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
    )
    assert [row.status for row in patterns] == ["CONTESTED"]
    lessons = await publisher.store.current_lessons_for_scope(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
    )
    exact = [row for row in lessons if row.statement == STATEMENT_A]
    assert exact and all(row.status == "CONTESTED" for row in exact)


async def test_t02_split_support_upgrades_historical_member_lessons(
    growth_db, publisher
):
    await _publish_attempts(
        publisher, [_attempt("t02_a0"), _attempt("t02_a1")]
    )
    before = await publisher.store.current_lessons_for_scope(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
    )
    assert all(row.status == "CANDIDATE" for row in before)
    await _publish_attempts(publisher, [_attempt("t02_a2")])
    patterns = await publisher.store.current_patterns_for_scope(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
    )
    assert [row.status for row in patterns] == ["VALIDATED"]
    lessons = await publisher.store.current_lessons_for_scope(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
    )
    assert len(lessons) == 3
    assert all(row.status == "VALIDATED" for row in lessons)


async def test_t03_unrelated_proposition_not_synchronized(growth_db, publisher):
    attempts = [_attempt(f"t03_a{index}") for index in range(3)] + [
        _attempt("t03_b0", statement=STATEMENT_B)
    ]
    await _publish_attempts(publisher, attempts)
    lessons = await publisher.store.current_lessons_for_scope(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
    )
    unrelated = [row for row in lessons if row.statement == STATEMENT_B]
    assert unrelated and unrelated[0].status == "CANDIDATE"


async def test_t04_revoked_latest_lesson_cannot_reenter_compression(
    growth_db, publisher
):
    for index in range(3):
        await publisher.publish_review(
            attempt=_attempt(f"t04_{index}"), binding=_binding(), known_at=KNOWN_AT
        )
    lessons = await publisher.store.current_lessons_for_scope(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
    )
    assert lessons
    for lesson in lessons:
        await publisher.revoke(
            kind="lesson",
            logical_id=lesson.lesson_id,
            reason="R4-T04",
            at=KNOWN_AT,
        )
    compression = await publisher.compress(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME,
        known_at=KNOWN_AT,
    )
    assert compression is not None
    assert STATEMENT_A not in compression.content


async def _seed_card(
    growth_db,
    *,
    rule_id: str,
    account_id: str = "default",
    mode: str = "PAPER",
    status: str = "ACTIVE",
    known_at=KNOWN_AT,
    share_scope: str = "ACCOUNT_MODE",
) -> None:
    async with growth_db.session_factory() as session:
        session.add(
            AICompressedExperienceORM(
                rule_id=rule_id,
                symbol=SYMBOL,
                title=rule_id,
                content="card content",
                source_episode_count=1,
                account_id=account_id,
                mode=mode,
                status=status,
                share_scope=share_scope,
                known_at=known_at,
                created_at=known_at,
                applicability_scope_json={"scope": "SYMBOL", "symbols": [SYMBOL]},
            )
        )
        await session.commit()


async def _memory_search(growth_db, *, account_id: str, as_of=KNOWN_AT):
    registry = LLMToolRegistry()
    register_context_tools(registry, ChiefContextLoader(growth_db.session_factory))
    return await registry.call(
        "memory_search",
        SYMBOL,
        {
            "chief_context": _context(),
            "as_of": as_of,
            "account_id": account_id,
            "mode": "PAPER",
        },
    )


async def test_t05_foreign_private_card_does_not_leak(growth_db):
    await _seed_card(growth_db, rule_id="t05_foreign", account_id="acct-b")
    evidence = await _memory_search(growth_db, account_id="acct-a")
    assert evidence.source_refs == []


async def test_t06_candidate_card_does_not_leak(growth_db):
    await _seed_card(growth_db, rule_id="t06_candidate", status="CANDIDATE")
    evidence = await _memory_search(growth_db, account_id="default")
    assert evidence.source_refs == []


async def test_t07_future_known_card_does_not_leak(growth_db):
    await _seed_card(
        growth_db,
        rule_id="t07_future",
        known_at=KNOWN_AT + timedelta(days=1),
    )
    evidence = await _memory_search(growth_db, account_id="default")
    assert evidence.source_refs == []


async def test_t08_explicit_shared_card_follows_share_scope(growth_db):
    await _seed_card(
        growth_db,
        rule_id="t08_shared",
        account_id="acct-b",
        share_scope="GLOBAL_EXPLICIT",
    )
    evidence = await _memory_search(growth_db, account_id="acct-a")
    assert evidence.source_refs == ["memory:rule:t08_shared"]


async def test_t09_impossible_budget_fails_fast_via_registry(growth_db):
    loader = GrowthContextLoader(
        growth_db.session_factory, budget=ToolBudget(token_budget=1)
    )
    registry = LLMToolRegistry()
    register_context_tools(registry, loader)
    with pytest.raises(EvidenceBudgetConfigurationError):
        await registry.call(
            "memory_search",
            SYMBOL,
            {"chief_context": _context(), "as_of": KNOWN_AT},
        )


async def test_t10_small_budget_uses_real_serialized_cost(growth_db):
    import json
    from dataclasses import asdict

    loader = GrowthContextLoader(
        growth_db.session_factory, budget=ToolBudget(token_budget=120)
    )
    evidence = await loader.load_tool("memory_search", _context(), as_of=KNOWN_AT)
    cost = len(json.dumps(asdict(evidence), sort_keys=True, default=str)) // 4
    assert cost <= 120
    assert evidence.source_refs == []
