"""Round-2 V2 card evidence budget and per-account trace regressions."""

from __future__ import annotations

import json
from dataclasses import asdict

from sqlalchemy import select

from crypto_trader.learning.growth_card_retrieval import (
    CardRankingPolicy,
    ExperienceCardRetriever,
    register_experience_card_tool,
)
from crypto_trader.learning.growth_models import GrowthCardDecisionTraceORM
from crypto_trader.llm.tools.registry import LLMToolRegistry
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.persistence.models import AICompressedExperienceORM
from tests.growth_system_v2.conftest import AS_OF, market_context, seed_card


def _context(symbol: str = "BTCUSDT") -> ChiefTraderContext:
    return ChiefTraderContext(
        symbol=symbol,
        market_snapshot={},
        regime="BULL",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        prepared_at=AS_OF.isoformat(),
    )


def _tool_context(account_id: str = "default") -> dict:
    return {
        "as_of": AS_OF,
        "chief_context": _context(),
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
        "account_id": account_id,
        "mode": "PAPER",
    }


def _cost(evidence) -> int:
    return max(1, len(json.dumps(asdict(evidence), sort_keys=True, default=str)) // 4)


async def test_card_evidence_respects_full_serialized_budget(v2_db):
    await seed_card(
        v2_db,
        rule_id="card_huge",
        status="ACTIVE",
        guidance={"summary": "x" * 4000, "direction": "LONG"},
    )
    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == "card_huge"
                )
            )
        ).scalar_one()
        row.source_episode_ids_json = [f"ep_{index}" for index in range(200)]
        row.supporting_episode_ids_json = list(row.source_episode_ids_json)
        await session.commit()
    retriever = ExperienceCardRetriever(
        v2_db.session_factory, policy=CardRankingPolicy(token_budget=120)
    )
    registry = LLMToolRegistry()
    register_experience_card_tool(registry, retriever)
    evidence = await registry.call("experience_cards", "BTCUSDT", _tool_context())
    assert _cost(evidence) <= 120
    assert len(evidence.features.get("cards", [])) <= 1


async def test_shared_card_trace_is_isolated_per_account(v2_db):
    await seed_card(v2_db, rule_id="card_shared", status="ACTIVE")
    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == "card_shared"
                )
            )
        ).scalar_one()
        row.share_scope = "GLOBAL_EXPLICIT"
        row.applicability_scope_json = {
            "sharing": "GLOBAL_EXPLICIT",
            "approved_by": "test-only",
        }
        await session.commit()
    retriever = ExperienceCardRetriever(v2_db.session_factory)
    registry = LLMToolRegistry()
    register_experience_card_tool(registry, retriever)
    trace_ids = []
    for account_id in ("acct-a", "acct-b"):
        evidence = await registry.call(
            "experience_cards", "BTCUSDT", _tool_context(account_id)
        )
        assert evidence.source_refs == ["card:card_shared:v1"]
        trace_ids.append(evidence.features["card_trace_id"])
    assert len(set(trace_ids)) == 2
    async with v2_db.session_factory() as session:
        rows = (
            await session.execute(select(GrowthCardDecisionTraceORM))
        ).scalars().all()
    assert {row.account_id for row in rows} == {"acct-a", "acct-b"}
    assert len({row.trace_id for row in rows}) == 2
