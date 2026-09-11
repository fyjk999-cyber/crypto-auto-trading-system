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
