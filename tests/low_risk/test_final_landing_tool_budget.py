"""PR #2 port: bounded tool budget, tool timeout and versioned contracts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from crypto_trader.llm.tools.registry import LLMToolRegistry, ToolEvidence
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.tool_orchestrator import ToolDrivenChiefTrader


async def _evidence(name: str, symbol: str) -> ToolEvidence:
    return ToolEvidence(
        tool_name=name,
        symbol=symbol,
        timestamp=datetime.now(UTC),
        features={"ok": True},
        supporting_evidence=["ok"],
        contrary_evidence=[],
        confidence_of_measurement=0.8,
        data_quality="HEALTHY",
        source_refs=[f"test:{name}"],
    )


async def test_tool_timeout_is_explicit_and_never_fabricated():
    tools = LLMToolRegistry()

    async def slow(symbol: str, _context: dict) -> ToolEvidence:
        await asyncio.sleep(0.2)
        return await _evidence("slow", symbol)

    tools.register("slow", slow)
    evidence = await tools.call("slow", "BTCUSDT", {}, timeout_seconds=0.01)
    assert evidence.data_quality == "UNAVAILABLE"
    assert evidence.contrary_evidence == ["tool timeout"]
    assert evidence.confidence_of_measurement == 0.0


async def test_tool_budget_and_versioned_contract_are_enforced():
    tools = LLMToolRegistry()

    async def tool(symbol: str, _context: dict) -> ToolEvidence:
        return await _evidence("t", symbol)

    async def tool2(symbol: str, _context: dict) -> ToolEvidence:
        return await _evidence("t2", symbol)

    tools.register("t", tool, version="2.3.4", description="test tool")
    tools.register("t2", tool2)
    contracts = tools.contract_catalog()
    assert contracts["t"]["version"] == "2.3.4"
    assert contracts["t"]["source"] == "RUNTIME_BOUND"

    package = await tools.build_package(
        ["t"], "BTCUSDT", {"symbol": "BTCUSDT"}, now=datetime.now(UTC)
    )
    assert package.items[0].tool_version == "2.3.4"

    with pytest.raises(ValueError, match="tool budget exceeded"):
        await tools.build_package(
            ["t", "t2"],
            "BTCUSDT",
            {},
            now=datetime.now(UTC),
            max_tools=1,
        )


class _SlowChief:
    def __init__(self) -> None:
        self.fail_reason: str | None = None

    async def select_tools(self, _ctx, _available):
        await asyncio.sleep(0.2)
        return ["t"], None

    def fail_closed(self, ctx, reason):
        self.fail_reason = reason
        return ChiefTraderDecision(
            decision_id="d1",
            symbol=ctx.symbol,
            action="FAIL_CLOSED",
            market_regime=ctx.regime,
            reason_codes=[reason],
        )


class _Tools:
    def available(self):
        return ["t"]

    async def build_package(self, *_args, **_kwargs):
        raise AssertionError("package must not be built after timeout")


def _ctx() -> ChiefTraderContext:
    return ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={},
        regime="RANGE",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
    )


async def test_one_wall_clock_budget_bounds_tool_round():
    chief = _SlowChief()
    orchestrator = ToolDrivenChiefTrader(
        chief, _Tools(), tool_round_timeout_seconds=0.01
    )
    decision, package = await orchestrator.decide(
        _ctx(), tool_context={}, now=datetime.now(UTC)
    )
    assert package is None
    assert decision.action == "FAIL_CLOSED"
    assert chief.fail_reason == "TOOL_ROUND_TIMEOUT"
