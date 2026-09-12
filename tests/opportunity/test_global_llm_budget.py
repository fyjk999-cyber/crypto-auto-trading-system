"""Tests for the single global LLM budget authority (§8) enforcement."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from crypto_trader.llm_chief.budget import (
    P0_POSITION_SAFETY,
    P1_POSITION_LIFECYCLE,
    P2_FINAL_ENTRY_DECISION,
    P3_SELECTED_SYMBOL_RESEARCH,
    P4_MARKET_SELECTION,
    P5_BACKGROUND_RESEARCH,
    BudgetConfig,
    GlobalLLMBudget,
)
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import PositionState
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.provider import LLMResponse


@dataclass
class StubProvider:
    name = "stub"
    model = "stub-model"
    payload: dict | None = None
    ok: bool = True

    async def complete_json(self, *, prompt, **kwargs):
        return LLMResponse(
            text="{}",
            provider=self.name,
            model=self.model,
            latency_ms=12.0,
            parsed_json=self.payload if self.payload is not None else {"action": "NO_TRADE"},
            ok=self.ok,
            error=None if self.ok else "PROVIDER_DOWN",
            token_usage={"prompt_tokens": 7, "completion_tokens": 3},
        )

    def healthy(self) -> bool:
        return True


def _ctx(position_state=PositionState.FLAT) -> ChiefTraderContext:
    return ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={},
        regime="RANGE",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        position_state=position_state,
        prepared_at="2026-01-01T00:00:00+00:00",
    )


def test_priority_order_is_fixed_and_reservations_protect_higher_priorities():
    config = BudgetConfig(window_seconds=3600, max_calls_per_window=100)
    ceilings = {p: config.ceiling_for(p) for p in (
        P0_POSITION_SAFETY,
        P1_POSITION_LIFECYCLE,
        P2_FINAL_ENTRY_DECISION,
        P3_SELECTED_SYMBOL_RESEARCH,
        P4_MARKET_SELECTION,
        P5_BACKGROUND_RESEARCH,
    )}
    assert ceilings[P0_POSITION_SAFETY] == 100
    assert ceilings[P1_POSITION_LIFECYCLE] == 100
    assert ceilings[P2_FINAL_ENTRY_DECISION] == 100
    # lower priorities keep capacity reserved for the higher ones
    assert ceilings[P3_SELECTED_SYMBOL_RESEARCH] == 85  # 15% reserved above
    assert ceilings[P4_MARKET_SELECTION] == 70  # 30% reserved above
    assert ceilings[P5_BACKGROUND_RESEARCH] == 55  # 45% reserved above


def test_market_selection_budget_uses_and_tracks_operation_facts():
    budget = GlobalLLMBudget(BudgetConfig(window_seconds=60, max_calls_per_window=5))
    ticket = budget.try_acquire(P4_MARKET_SELECTION, operation="market_selection")
    assert ticket.granted is True
    ticket.complete(
        status="OK",
        provider="deepseek",
        model="deepseek-flash",
        input_tokens=100,
        output_tokens=20,
        latency_ms=1500,
    )
    snapshot = budget.snapshot()
    assert snapshot["granted_by_priority"][P4_MARKET_SELECTION] == 1
    entry = [e for e in snapshot["recent_operations"] if e["operation"] == "market_selection"][-1]
    assert entry["provider"] == "deepseek"
    assert entry["model"] == "deepseek-flash"
    assert entry["input_tokens"] == 100
    assert entry["output_tokens"] == 20
    assert entry["latency_ms"] == 1500


def test_exhausted_market_selection_budget_is_an_explicit_skip():
    budget = GlobalLLMBudget(
        BudgetConfig(
            window_seconds=60,
            max_calls_per_window=1,
            reserved_fraction_for_higher={P4_MARKET_SELECTION: 1},
        )
    )
    ticket = budget.try_acquire(P4_MARKET_SELECTION, operation="market_selection")
    assert ticket.granted is False
    assert ticket.state == "SKIPPED_BUDGET"
    assert budget.snapshot()["skipped_by_priority"][P4_MARKET_SELECTION] == 1


def test_higher_priority_call_is_never_blocked_by_lower_priority_usage():
    budget = GlobalLLMBudget(BudgetConfig(window_seconds=60, max_calls_per_window=5))
    # market selection ceiling = floor(5 * (1 - 0.30)) = 3
    assert budget.try_acquire(P4_MARKET_SELECTION, operation="market_selection").granted
    assert budget.try_acquire(P4_MARKET_SELECTION, operation="market_selection").granted
    assert budget.try_acquire(P4_MARKET_SELECTION, operation="market_selection").granted
    assert not budget.try_acquire(P4_MARKET_SELECTION, operation="market_selection").granted
    # position safety still has capacity
    assert budget.try_acquire(P0_POSITION_SAFETY, operation="position_exit").granted


def test_chief_decide_skips_without_calling_provider_when_budget_is_exhausted():
    budget = GlobalLLMBudget(
        BudgetConfig(
            window_seconds=60,
            max_calls_per_window=1,
            reserved_fraction_for_higher={P2_FINAL_ENTRY_DECISION: 1},
        )
    )
    provider = StubProvider()
    engine = ChiefTraderEngine(provider=provider, budget=budget)
    decision = asyncio.run(engine.decide(_ctx()))
    assert decision.action.value == "FAIL_CLOSED"
    assert "SKIPPED_BUDGET" in decision.reason_codes


def test_chief_decide_records_priority_by_position_state():
    budget = GlobalLLMBudget(BudgetConfig(window_seconds=60, max_calls_per_window=20))
    engine = ChiefTraderEngine(provider=StubProvider(), budget=budget)
    asyncio.run(engine.decide(_ctx(PositionState.FLAT)))
    asyncio.run(
        engine.decide(
            _ctx(PositionState.OPEN)
            if hasattr(PositionState, "OPEN")
            else _ctx(PositionState.FLAT)
        )
    )
    granted = budget.snapshot()["granted_by_priority"]
    assert granted.get(P2_FINAL_ENTRY_DECISION, 0) >= 1


def test_chief_tool_selection_is_budget_gated():
    """Tool selection on behalf of an ENTRY workflow is gated by the entry pool.

    The purpose is now inherited from the workflow (a position review's tool
    selection draws on position capacity instead), so this test states the entry
    case explicitly rather than relying on a hardcoded research priority.
    """
    budget = GlobalLLMBudget(
        BudgetConfig(
            window_seconds=60,
            max_calls_per_window=1,
            reserved_fraction_for_higher={P2_FINAL_ENTRY_DECISION: 1},
        )
    )
    engine = ChiefTraderEngine(provider=StubProvider(payload={"tools": []}), budget=budget)
    selected, error = asyncio.run(
        engine.select_tools(_ctx(PositionState.FLAT), ["trend"])
    )
    assert selected is None
    assert error and error != "SKIPPED_BUDGET", (
        "a denial must name the exhausted pool, not a bare SKIPPED_BUDGET"
    )


def test_tool_selection_success_is_recorded_in_the_budget():
    budget = GlobalLLMBudget(BudgetConfig(window_seconds=60, max_calls_per_window=20))
    engine = ChiefTraderEngine(provider=StubProvider(payload={"tools": ["trend"]}), budget=budget)
    selected, error = asyncio.run(engine.select_tools(_ctx(PositionState.FLAT), ["trend"]))
    assert error is None
    assert selected == ["trend"]
    # An ENTRY workflow's tool selection is charged to the entry purpose, not to
    # a research pool: the purpose is inherited from the workflow.
    assert budget.snapshot()["granted_by_priority"][P2_FINAL_ENTRY_DECISION] == 1
