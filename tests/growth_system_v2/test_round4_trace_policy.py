"""Round-4 T11: ranking policy must invalidate incompatible trace overrides."""

from __future__ import annotations

from sqlalchemy import select

from crypto_trader.learning.growth_card_retrieval import (
    CardRankingPolicy,
    ExperienceCardRetriever,
    register_experience_card_tool,
)
from crypto_trader.learning.growth_models import GrowthCardDecisionTraceORM
from crypto_trader.llm.tools.registry import LLMToolRegistry
from tests.growth_system_v2.conftest import seed_card
from tests.growth_system_v2.test_round2_card_budget_trace import _tool_context

POLICY_A = CardRankingPolicy(
    weights={
        "trigger": 0.60,
        "scope": 0.10,
        "quality": 0.10,
        "recency": 0.05,
        "semantic": 0.15,
    }
)
POLICY_B = CardRankingPolicy(
    weights={
        "trigger": 0.10,
        "scope": 0.10,
        "quality": 0.10,
        "recency": 0.05,
        "semantic": 0.65,
    }
)


async def test_t11_policy_change_rekeys_trace_override(v2_db):
    await seed_card(v2_db, rule_id="t11_card", status="ACTIVE")
    override = "cardtrace_override_t11"
    evidence = []
    for policy in (POLICY_A, POLICY_B):
        registry = LLMToolRegistry()
        register_experience_card_tool(
            registry, ExperienceCardRetriever(v2_db.session_factory, policy=policy)
        )
        context = {**_tool_context(), "card_trace_id": override}
        evidence.append(await registry.call("experience_cards", "BTCUSDT", context))
    assert evidence[0].features["card_trace_id"] == override
    assert evidence[1].features["card_trace_id"] != override
    async with v2_db.session_factory() as session:
        rows = (
            await session.execute(select(GrowthCardDecisionTraceORM))
        ).scalars().all()
    by_fingerprint = {
        (row.applicability_json or {}).get("_policy_fingerprint"): row
        for row in rows
    }
    assert POLICY_A.fingerprint() in by_fingerprint
    assert POLICY_B.fingerprint() in by_fingerprint
    assert len(by_fingerprint) == 2
