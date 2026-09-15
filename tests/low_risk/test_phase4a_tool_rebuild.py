"""Phase 4A test: tool-driven Chief forwards the fresh-state rebuild seam."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.tool_orchestrator import ToolDrivenChiefTrader


class _Chief:
    def __init__(self) -> None:
        self.rebuild_context = "UNSET"
        self.calls = 0

    async def select_tools(self, ctx, available):
        return ["t1"], None

    async def fail_closed(self, ctx, reason):
        raise AssertionError(f"unexpected fail_closed: {reason}")

    async def decide(self, ctx, *, rebuild_context=None):
        self.calls += 1
        self.rebuild_context = rebuild_context
        return ChiefTraderDecision(
            decision_id="d1",
            symbol=ctx.symbol,
            action="WAIT",
            market_regime=ctx.regime,
        )


class _Tools:
    def available(self):
        return ["t1"]

    async def build_package(self, selected, symbol, context, *, now):
        return SimpleNamespace(model_dump=lambda mode=None: {"selected": selected})


def _ctx() -> ChiefTraderContext:
    return ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={"last": "100"},
        regime="RANGE",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
    )


async def test_tool_chief_forwards_rebuild_context() -> None:
    chief = _Chief()
    orchestrator = ToolDrivenChiefTrader(chief, _Tools())

    async def rebuild():
        return ("FRESH", "v1")

    decision, package = await orchestrator.decide(
        _ctx(),
        tool_context={},
        now=datetime.now(UTC),
        rebuild_context=rebuild,
    )
    assert decision.action.value == "WAIT"
    assert package is not None
    assert chief.rebuild_context is rebuild
    assert chief.calls == 1


async def test_tool_chief_without_rebuild_context_is_unchanged() -> None:
    chief = _Chief()
    orchestrator = ToolDrivenChiefTrader(chief, _Tools())
    decision, _ = await orchestrator.decide(_ctx(), tool_context={}, now=datetime.now(UTC))
    assert decision.action.value == "WAIT"
    assert chief.rebuild_context is None
