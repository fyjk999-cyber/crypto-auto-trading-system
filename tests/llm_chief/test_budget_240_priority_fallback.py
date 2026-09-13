"""LLM budget 240/h + P3 optional-research priority-inversion regression tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from crypto_trader.config import Settings
from crypto_trader.llm.tools.registry import LLMToolRegistry
from crypto_trader.llm_chief.budget import (
    P0_POSITION_SAFETY,
    P1_POSITION_LIFECYCLE,
    P2_FINAL_ENTRY_DECISION,
    P3_SELECTED_SYMBOL_RESEARCH,
    P4_MARKET_SELECTION,
    P5_BACKGROUND_RESEARCH,
    BudgetConfig,
    GlobalLLMBudget,
    classify_budget_pressure,
)
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import PositionState
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.provider import LLMResponse
from crypto_trader.llm_chief.tool_orchestrator import ToolDrivenChiefTrader


@dataclass
class StubProvider:
    name = "deepseek"
    model = "deepseek-chat"
    payload: dict | None = None
    calls: int = 0

    async def complete_json(self, *, prompt, **kwargs):
        self.calls += 1
        return LLMResponse(
            text="{}",
            provider=self.name,
            model=self.model,
            latency_ms=1.0,
            parsed_json=self.payload or {
                "action": "NO_TRADE",
                "market_regime": "RANGE",
                "reason_codes": ["INSUFFICIENT_EDGE"],
            },
        )

    def healthy(self) -> bool:
        return True


def context(position_state: PositionState = PositionState.FLAT) -> ChiefTraderContext:
    return ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={"source": "OKX_PUBLIC"},
        regime="RANGE",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        position_state=position_state,
        prepared_at="2026-01-01T00:00:00+00:00",
    )


def test_settings_default_budget_is_240_per_3600_seconds():
    settings = Settings()
    assert settings.llm_budget_max_calls_per_window == 240
    assert settings.llm_budget_window_seconds == 3600.0


def test_240_budget_ceilings_are_exact():
    config = BudgetConfig(window_seconds=3600, max_calls_per_window=240)
    assert config.ceiling_for(P0_POSITION_SAFETY) == 240
    assert config.ceiling_for(P1_POSITION_LIFECYCLE) == 240
    assert config.ceiling_for(P2_FINAL_ENTRY_DECISION) == 240
    assert config.ceiling_for(P3_SELECTED_SYMBOL_RESEARCH) == 204
    assert config.ceiling_for(P4_MARKET_SELECTION) == 168
    assert config.ceiling_for(P5_BACKGROUND_RESEARCH) == 132


def test_p3_skip_flat_still_reaches_p2_final_decision():
    budget = GlobalLLMBudget(
        BudgetConfig(
            window_seconds=3600,
            max_calls_per_window=240,
            reserved_fraction_for_higher={P3_SELECTED_SYMBOL_RESEARCH: 1.0},
        )
    )
    provider = StubProvider()
    chief = ChiefTraderEngine(provider=provider, budget=budget)
    trader = ToolDrivenChiefTrader(chief, LLMToolRegistry())
    decision, package = asyncio.run(
        trader.decide(context(), tool_context={}, now=datetime.now(UTC))
    )
    assert package is None
    assert provider.calls == 1
    assert decision.action.value == "NO_TRADE"
    assert "OPTIONAL_RESEARCH_SKIPPED_BUDGET" in decision.reason_codes
    stats = trader.budget_observability()
    assert stats["p3_optional_fallback_count"] == 1
    assert stats["p2_decisions_after_p3_skip"] == 1
    assert stats["last_final_decision_priority"] == P2_FINAL_ENTRY_DECISION
    assert stats["last_final_decision_attempted"] is True


def test_p3_skip_open_position_still_reaches_p1_lifecycle_decision():
    budget = GlobalLLMBudget(
        BudgetConfig(
            window_seconds=3600,
            max_calls_per_window=240,
            reserved_fraction_for_higher={P3_SELECTED_SYMBOL_RESEARCH: 1.0},
        )
    )
    provider = StubProvider(
        payload={
            "action": "HOLD",
            "market_regime": "RANGE",
            "reason_codes": ["THESIS_INTACT"],
        }
    )
    chief = ChiefTraderEngine(provider=provider, budget=budget)
    trader = ToolDrivenChiefTrader(chief, LLMToolRegistry())
    decision, package = asyncio.run(
        trader.decide(
            context(PositionState.OPEN), tool_context={}, now=datetime.now(UTC)
        )
    )
    assert package is None
    assert provider.calls == 1
    assert decision.action.value == "HOLD"
    assert "OPTIONAL_RESEARCH_SKIPPED_BUDGET" in decision.reason_codes
    stats = trader.budget_observability()
    assert stats["p3_optional_fallback_count"] == 1
    assert stats["p1_decisions_after_p3_skip"] == 1
    assert stats["last_final_decision_priority"] == P1_POSITION_LIFECYCLE


def test_true_p2_exhaustion_still_fails_closed():
    budget = GlobalLLMBudget(
        BudgetConfig(
            window_seconds=3600,
            max_calls_per_window=240,
            reserved_fraction_for_higher={
                P2_FINAL_ENTRY_DECISION: 1.0,
                P3_SELECTED_SYMBOL_RESEARCH: 1.0,
            },
        )
    )
    provider = StubProvider()
    trader = ToolDrivenChiefTrader(
        ChiefTraderEngine(provider=provider, budget=budget), LLMToolRegistry()
    )
    decision, package = asyncio.run(
        trader.decide(context(), tool_context={}, now=None)
    )
    assert package is None
    assert provider.calls == 0
    assert decision.action.value == "FAIL_CLOSED"
    assert "SKIPPED_BUDGET" in decision.reason_codes
    assert "OPTIONAL_RESEARCH_SKIPPED_BUDGET" not in decision.reason_codes


def test_true_p1_exhaustion_still_fails_closed():
    budget = GlobalLLMBudget(
        BudgetConfig(
            window_seconds=3600,
            max_calls_per_window=240,
            reserved_fraction_for_higher={
                P1_POSITION_LIFECYCLE: 1.0,
                P3_SELECTED_SYMBOL_RESEARCH: 1.0,
            },
        )
    )
    provider = StubProvider()
    trader = ToolDrivenChiefTrader(
        ChiefTraderEngine(provider=provider, budget=budget), LLMToolRegistry()
    )
    decision, package = asyncio.run(
        trader.decide(context(PositionState.OPEN), tool_context={}, now=None)
    )
    assert package is None
    assert provider.calls == 0
    assert decision.action.value == "FAIL_CLOSED"
    assert "SKIPPED_BUDGET" in decision.reason_codes


def test_lower_priority_usage_cannot_starve_p0_p1_p2():
    # Consume each lower priority individually up to its reserved ceiling.
    # A single lower priority can never consume the whole 240-call window.
    for priority in (P4_MARKET_SELECTION, P5_BACKGROUND_RESEARCH):
        budget = GlobalLLMBudget(BudgetConfig(window_seconds=3600, max_calls_per_window=240))
        for _ in range(budget.config.ceiling_for(priority)):
            assert budget.try_acquire(priority, operation="research").granted
        snapshot = budget.snapshot()
        assert snapshot["calls_in_window"] < snapshot["max_calls_per_window"]
        assert budget.try_acquire(P0_POSITION_SAFETY, operation="position_exit").granted
        assert budget.try_acquire(P1_POSITION_LIFECYCLE, operation="position_review").granted
        assert budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="trading_decision").granted


def test_p3_skip_does_not_create_directional_authority():
    budget = GlobalLLMBudget(
        BudgetConfig(
            window_seconds=3600,
            max_calls_per_window=240,
            reserved_fraction_for_higher={P3_SELECTED_SYMBOL_RESEARCH: 1.0},
        )
    )
    provider = StubProvider(
        payload={
            "action": "LONG",
            "market_regime": "TREND",
            "thesis": "factual provider thesis",
            "position_size_request": 10.0,
            "leverage_request": 2.0,
            "stop_loss": 90.0,
            "reason_codes": ["PROVIDER_LONG"],
        }
    )
    trader = ToolDrivenChiefTrader(
        ChiefTraderEngine(provider=provider, budget=budget), LLMToolRegistry()
    )
    decision, _ = asyncio.run(trader.decide(context(), tool_context={}, now=None))
    assert provider.calls == 1
    assert decision.action.value == "LONG"
    assert decision.thesis == "factual provider thesis"


def test_budget_snapshot_distinguishes_research_pressure_from_global_exhaustion():
    budget = GlobalLLMBudget(BudgetConfig(window_seconds=3600, max_calls_per_window=240))
    for _ in range(205):
        assert budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="trading_decision").granted
    snapshot = budget.snapshot()
    assert snapshot["calls_in_window"] == 205
    assert snapshot["global_budget_exhausted"] is False
    pressure = classify_budget_pressure(snapshot)
    # P3 ceiling is 204; at 205 global calls P3 is exhausted while P2 still is not.
    assert "D4_P3_RESEARCH_BUDGET_EXHAUSTED" in pressure["codes"]
    assert "D4_GLOBAL_LLM_BUDGET_EXHAUSTED" not in pressure["codes"]
    assert pressure["verdict"] == "OPTIONAL_RESEARCH_BUDGET_PRESSURE"


def test_p0_p1_safety_remain_callable_after_global_window_exhaustion():
    budget = GlobalLLMBudget(BudgetConfig(window_seconds=3600, max_calls_per_window=240))
    for _ in range(240):
        assert budget.try_acquire(
            P2_FINAL_ENTRY_DECISION, operation="trading_decision"
        ).granted
    snapshot = budget.snapshot()
    assert snapshot["global_budget_exhausted"] is True
    assert snapshot["exhausted_by_priority"][P2_FINAL_ENTRY_DECISION] is True
    # P0/P1 safety is not blocked by lower-priority/global window usage.
    assert budget.try_acquire(P0_POSITION_SAFETY, operation="position_exit").granted
    assert budget.try_acquire(P1_POSITION_LIFECYCLE, operation="position_review").granted
    assert not budget.try_acquire(
        P2_FINAL_ENTRY_DECISION, operation="trading_decision"
    ).granted
