"""G14 ChiefTrader integration: cards are evidence, never direction/order."""

from __future__ import annotations

import json

from sqlalchemy import func, select

from crypto_trader.learning.growth_card_retrieval import (
    CardDecisionTraceStore,
    ExperienceCardRetriever,
    register_experience_card_tool,
)
from crypto_trader.learning.growth_models import GrowthCardDecisionTraceORM
from crypto_trader.llm.tools.context import register_context_tools
from crypto_trader.llm.tools.registry import LLMToolRegistry
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.provider import LLMResponse
from crypto_trader.llm_chief.tool_orchestrator import ToolDrivenChiefTrader
from crypto_trader.persistence.models import FillORM, OrderORM, TradeEpisodeORM
from tests.growth_system_v2.conftest import AS_OF, market_context, seed_card, trigger


class ScriptedProvider:
    name = "deepseek-test-double"
    model = "deepseek-test-model"

    def __init__(self, selected_tools: list[str]):
        self.selected_tools = selected_tools
        self.calls: list[dict] = []

    def healthy(self) -> bool:
        return True

    async def complete_json(self, **kwargs) -> LLMResponse:
        self.calls.append(kwargs)
        if kwargs.get("operation") == "tool_selection":
            payload = {"tools": self.selected_tools}
        else:
            payload = {
                "action": "NO_TRADE",
                "market_regime": "BULL",
                "thesis": "Experience cards are historical evidence; no current edge.",
                "supporting_evidence": [],
                "contradicting_evidence": [],
                "reason_codes": ["EVIDENCE_ONLY"],
                "position_size_request": 0,
                "leverage_request": 0,
                "raw_llm_confidence": 0.0,
            }
        return LLMResponse(
            text=json.dumps(payload),
            provider=self.name,
            model=self.model,
            latency_ms=1.0,
            parsed_json=payload,
            ok=True,
            token_usage={"prompt_tokens": 1, "completion_tokens": 1},
        )


def _context():
    return ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={"last": "100", "regime": "BULL"},
        regime="BULL",
        quant_evidence=[],
        portfolio_state={"equity": "100000"},
        risk_summary={"max_leverage": "3"},
        prepared_at=AS_OF.isoformat(),
    )


def _tool_context():
    return {
        "as_of": AS_OF,
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
        "account_id": "default",
        "mode": "PAPER",
    }


async def test_chief_receives_cards_as_evidence_and_trace_records_versions(v2_db):
    await seed_card(v2_db, rule_id="card_chief", status="ACTIVE")
    registry = LLMToolRegistry()
    retriever = ExperienceCardRetriever(v2_db.session_factory)
    register_experience_card_tool(registry, retriever)
    # The official context tools can coexist with the card tool.
    from crypto_trader.learning.growth_retrieval import GrowthContextLoader

    register_context_tools(registry, GrowthContextLoader(v2_db.session_factory))
    provider = ScriptedProvider(["experience_cards"])
    chief = ToolDrivenChiefTrader(ChiefTraderEngine(provider=provider), registry)

    decision, package = await chief.decide(
        _context(), tool_context=_tool_context(), now=AS_OF
    )
    assert package is not None
    assert package.selected_tools == ["experience_cards"]
    assert any(ref.startswith("card:card_chief") for ref in package.source_refs)
    card_item = package.items[0].finding["cards"][0]
    assert card_item["can_emit_direction"] is False
    assert card_item["evidence_only"] is True
    assert "NOT_COMMANDS" in card_item["prompt_semantics"]
    assert decision.action == "NO_TRADE"

    final_prompt = provider.calls[-1]["prompt"]
    assert "card:card_chief" in final_prompt
    assert "HISTORICAL_EXPERIENCE_EVIDENCE_NOT_COMMANDS" in final_prompt

    trace = await CardDecisionTraceStore(v2_db.session_factory).record(
        await retriever.retrieve(
            trigger=trigger(), context=market_context(), as_of=AS_OF
        ),
        decision_id=decision.decision_id,
        evidence_package_id="package_chief",
    )
    assert trace.selected_card_refs_json == ["card:card_chief:v1"]
    assert trace.decision_id == decision.decision_id
    async with v2_db.session_factory() as session:
        stored = (await session.execute(select(GrowthCardDecisionTraceORM))).scalars().all()
    assert stored[0].card_versions_json == {"card:card_chief": 1}


async def test_chief_decision_creates_no_order_or_fill_and_does_not_mutate_card(v2_db):
    await seed_card(v2_db, rule_id="card_no_order", status="ACTIVE")
    registry = LLMToolRegistry()
    retriever = ExperienceCardRetriever(v2_db.session_factory)
    register_experience_card_tool(registry, retriever)
    provider = ScriptedProvider(["experience_cards"])
    chief = ToolDrivenChiefTrader(ChiefTraderEngine(provider=provider), registry)
    await chief.decide(_context(), tool_context=_tool_context(), now=AS_OF)
    async with v2_db.session_factory() as session:
        orders = await session.scalar(select(func.count()).select_from(OrderORM))
        fills = await session.scalar(select(func.count()).select_from(FillORM))
        episodes = await session.scalar(select(func.count()).select_from(TradeEpisodeORM))
    assert orders == 0 and fills == 0 and episodes == 0
    from crypto_trader.learning.growth_experience import AdaptiveCardStore

    stored = await AdaptiveCardStore(v2_db.session_factory).get_card("card_no_order")
    assert stored.version == 1 and stored.status == "ACTIVE"
