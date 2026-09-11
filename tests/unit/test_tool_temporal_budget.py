from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from crypto_trader.llm.tools.registry import LLMToolRegistry, ToolEvidence
from crypto_trader.llm_chief.engine import ToolSelection


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


async def test_tool_round_deadline_is_absolute_across_selection_and_execution():
    import asyncio

    from crypto_trader.llm_chief.tool_orchestrator import ToolDrivenChiefTrader

    called = []
    completed = []

    async def slow_tool(symbol, context):
        called.append(symbol)
        await asyncio.sleep(0.5)
        completed.append(symbol)

    class FakeChief:
        async def select_tools(self, ctx, catalog, *, timeout_seconds=None):
            return ["slow"], None

        def fail_closed(self, ctx, reason):
            return type("D", (), {"action": type("A", (), {"value": "FAIL_CLOSED"})()})()

        async def decide(self, ctx):
            raise AssertionError("decision must not run after deadline")

    registry = LLMToolRegistry()
    registry.register("slow", slow_tool)
    orchestrator = ToolDrivenChiefTrader.__new__(ToolDrivenChiefTrader)
    orchestrator.chief = FakeChief()
    orchestrator.tools = registry
    orchestrator.tool_round_budget_seconds = 0.05
    orchestrator.tool_selection_timeout_seconds = 0.01

    decision, package = await ToolDrivenChiefTrader.decide(
        orchestrator,
        type("Ctx", (), {"symbol": "BTCUSDT", "opportunity_context": None})(),
        tool_context={},
        now=datetime.now(UTC),
    )
    assert decision.action.value == "FAIL_CLOSED"
    assert package is None
    assert called == ["BTCUSDT"]
    assert completed == []  # cancelled by the shared absolute deadline


async def test_evidence_package_records_tool_contract_and_versions():
    now = datetime.now(UTC)

    async def tool(symbol, context):
        return ToolEvidence(
            "versioned", symbol, now, {"v": 1}, [], [], 1.0,
            "FACTUAL", ["source:versioned:v2"],
        )

    registry = LLMToolRegistry()
    registry.register("versioned", tool, version="2.3.0")
    package = await registry.build_package(
        ["versioned"], "BTCUSDT", {}, now=now
    )
    assert package.tool_versions == {"versioned": "2.3.0"}
    assert package.contract_version == "tool-round-v1"
    assert package.schema_version == "evidence-package-v1"
    assert "source:versioned:v2" in package.source_refs
