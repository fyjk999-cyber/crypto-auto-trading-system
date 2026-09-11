import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from crypto_trader.llm.tools.registry import LLMToolRegistry, ToolEvidence
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.engine import ChiefTraderEngine, ToolSelection
from crypto_trader.llm_chief.provider import LLMResponse
from crypto_trader.llm_chief.tool_orchestrator import ToolDrivenChiefTrader


async def test_future_payload_cannot_reach_chief_as_fresh_evidence():
    now = datetime.now(UTC)
    registry = LLMToolRegistry()

    async def future(symbol, context):
        assert context["as_of"] == now
        return ToolEvidence(
            "future", symbol, now + timedelta(seconds=1),
            {"price": "999"}, ["buy"], [], 1.0, "FACTUAL", ["future-source"],
        )

    registry.register("future", future)
    package = await registry.build_package(["future"], "SOLUSDT", {}, now=now)
    item = package.items[0]
    assert item.freshness == "FUTURE_REJECTED"
    assert item.data_quality == "UNAVAILABLE"
    assert item.finding == {} and item.supporting_evidence == []
    assert package.source_refs == []


def test_selection_and_execution_share_eight_tool_budget():
    assert len(ToolSelection(tools=[str(i) for i in range(8)]).tools) == 8
    with pytest.raises(ValidationError):
        ToolSelection(tools=[str(i) for i in range(9)])


async def test_expired_overall_deadline_starts_no_tool():
    registry = LLMToolRegistry()
    called = []

    async def tool(symbol, context):
        called.append(symbol)

    registry.register("tool", tool)
    with pytest.raises(ValueError, match="deadline"):
        await registry.build_package(
            ["tool"], "SOLUSDT", {}, now=datetime.now(UTC), overall_timeout_seconds=0,
        )
    assert called == []


async def test_tool_selection_and_execution_share_one_wall_clock_deadline():
    called: list[str] = []

    async def evidence(symbol, context):
        called.append(symbol)
        return ToolEvidence(
            "trend", symbol, context["as_of"], {}, [], [], 1.0, "FACTUAL", []
        )

    class SlowSelectionProvider:
        name = "deepseek"
        model = "test"

        async def complete_json(self, **kwargs):
            if kwargs.get("operation") == "tool_selection":
                await asyncio.sleep(0.05)
                return LLMResponse(
                    text='{"tools":["trend"]}',
                    provider=self.name,
                    model=self.model,
                    latency_ms=50,
                    parsed_json={"tools": ["trend"]},
                )
            raise AssertionError("final decision must not run after evidence deadline")

    context = ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={},
        regime="UNKNOWN",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
    )
    registry = LLMToolRegistry()
    registry.register("trend", evidence)
    trader = ToolDrivenChiefTrader(
        ChiefTraderEngine(SlowSelectionProvider()),
        registry,
        tool_round_timeout_seconds=0.01,
    )
    decision, package = await trader.decide(
        context, tool_context={}, now=datetime.now(UTC)
    )
    assert decision.action == "FAIL_CLOSED"
    assert decision.reason_codes == ["TOOL_ROUND_TIMEOUT"]
    assert package is None
    assert called == []
