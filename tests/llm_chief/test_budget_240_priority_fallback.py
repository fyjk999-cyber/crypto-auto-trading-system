"""Merged 240/h budget + optional-research fallback regression tests.

The Unified Safety donor makes the whole position review inherit P1 and the
whole entry workflow inherit P2.  The optional-research fallback remains as a
defence-in-depth path for any explicit P3/P4/P5 denial: it must proceed with the
canonical baseline factual context and still make the P1/P2 final call.
"""

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
    REASON_ENTRY_BUDGET_EXHAUSTED,
    REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED,
    REASON_SELECTED_SYMBOL_RESEARCH_BUDGET_EXHAUSTED,
    BudgetConfig,
    GlobalLLMBudget,
    classify_budget_pressure,
)
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import (
    ChiefTraderDecision,
    FlatAction,
    OpenAction,
    PositionState,
)
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


@dataclass
class OptionalResearchDenyingChief:
    """Minimal Chief stub whose tool-selection stage is P3-debugged."""

    denial: str = REASON_SELECTED_SYMBOL_RESEARCH_BUDGET_EXHAUSTED
    final_action: str = "NO_TRADE"
    select_calls: int = 0
    decide_calls: int = 0

    async def select_tools(self, ctx, available_tools, *, timeout_seconds=None):
        self.select_calls += 1
        return None, self.denial

    async def decide(self, ctx: ChiefTraderContext) -> ChiefTraderDecision:
        self.decide_calls += 1
        action = self.final_action
        if ctx.position_state != PositionState.FLAT:
            action = action if action in {"HOLD", "REDUCE", "EXIT"} else "HOLD"
        return ChiefTraderDecision(
            decision_id=f"llm_stub_{self.decide_calls}",
            symbol=ctx.symbol,
            position_state=ctx.position_state,
            action=action,
            market_regime="RANGE",
            thesis="stub factual thesis",
            position_size_request=10.0 if action in {"LONG", "SHORT"} else 0.0,
            leverage_request=2.0 if action in {"LONG", "SHORT"} else 0.0,
            stop_loss=90.0 if action in {"LONG", "SHORT"} else None,
            reason_codes=["STUB"],
            model_provider="deepseek",
            model="deepseek-chat",
        )

    def fail_closed(self, ctx, reason):
        return ChiefTraderDecision(
            decision_id="llm_stub_fail",
            symbol=ctx.symbol,
            position_state=ctx.position_state,
            action=(
                FlatAction.FAIL_CLOSED
                if ctx.position_state == PositionState.FLAT
                else OpenAction.FAIL_CLOSED
            ),
            market_regime="UNKNOWN",
            thesis="FAIL_CLOSED",
            reason_codes=[reason or "UNKNOWN"],
            model_provider="deepseek",
            model="deepseek-chat",
        )

    def render_prompt(self, ctx):
        return "stub-prompt"


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
    chief = OptionalResearchDenyingChief(final_action="NO_TRADE")
    trader = ToolDrivenChiefTrader(chief, LLMToolRegistry())
    decision, package = asyncio.run(
        trader.decide(context(), tool_context={}, now=datetime.now(UTC))
    )
    assert chief.select_calls == 1
    assert chief.decide_calls == 1
    assert package is None
    assert decision.action.value == "NO_TRADE"
    assert "OPTIONAL_RESEARCH_SKIPPED_BUDGET" in decision.reason_codes
    stats = trader.budget_observability()
    assert stats["p3_optional_fallback_count"] == 1
    assert stats["p2_decisions_after_p3_skip"] == 1
    assert stats["last_final_decision_priority"] == P2_FINAL_ENTRY_DECISION


def test_p3_skip_open_position_still_reaches_p1_lifecycle_decision():
    chief = OptionalResearchDenyingChief(final_action="HOLD")
    trader = ToolDrivenChiefTrader(chief, LLMToolRegistry())
    decision, package = asyncio.run(
        trader.decide(
            context(PositionState.OPEN), tool_context={}, now=datetime.now(UTC)
        )
    )
    assert chief.decide_calls == 1
    assert package is None
    assert decision.action.value == "HOLD"
    assert "OPTIONAL_RESEARCH_SKIPPED_BUDGET" in decision.reason_codes
    stats = trader.budget_observability()
    assert stats["p1_decisions_after_p3_skip"] == 1
    assert stats["last_final_decision_priority"] == P1_POSITION_LIFECYCLE


def test_true_p2_exhaustion_still_fails_closed():
    budget = GlobalLLMBudget(
        BudgetConfig(
            window_seconds=3600,
            max_calls_per_window=240,
            reserved_fraction_for_higher={P2_FINAL_ENTRY_DECISION: 1.0},
        )
    )
    provider = StubProvider()
    trader = ToolDrivenChiefTrader(
        ChiefTraderEngine(provider=provider, budget=budget), LLMToolRegistry()
    )
    decision, package = asyncio.run(
        trader.decide(context(), tool_context={}, now=datetime.now(UTC))
    )
    assert package is None
    assert provider.calls == 0
    assert decision.action.value == "FAIL_CLOSED"
    assert REASON_ENTRY_BUDGET_EXHAUSTED in decision.reason_codes


def test_true_p1_exhaustion_still_fails_closed():
    budget = GlobalLLMBudget(
        BudgetConfig(
            window_seconds=3600,
            max_calls_per_window=240,
            reserved_fraction_for_higher={P1_POSITION_LIFECYCLE: 1.0},
        )
    )
    provider = StubProvider()
    trader = ToolDrivenChiefTrader(
        ChiefTraderEngine(provider=provider, budget=budget), LLMToolRegistry()
    )
    decision, package = asyncio.run(
        trader.decide(
            context(PositionState.OPEN), tool_context={}, now=datetime.now(UTC)
        )
    )
    assert package is None
    assert provider.calls == 0
    assert decision.action.value == "FAIL_CLOSED"
    assert REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED in decision.reason_codes


def test_lower_priority_usage_cannot_starve_p0_p1_p2():
    for priority in (P4_MARKET_SELECTION, P5_BACKGROUND_RESEARCH):
        budget = GlobalLLMBudget(
            BudgetConfig(window_seconds=3600, max_calls_per_window=240)
        )
        for _ in range(budget.config.ceiling_for(priority)):
            assert budget.try_acquire(priority, operation="research").granted
        assert budget.try_acquire(P0_POSITION_SAFETY, operation="position_exit").granted
        assert budget.try_acquire(
            P1_POSITION_LIFECYCLE, operation="position_review"
        ).granted
        assert budget.try_acquire(
            P2_FINAL_ENTRY_DECISION, operation="trading_decision"
        ).granted


def test_position_reserve_keeps_safety_callable_after_general_pool_spent():
    budget = GlobalLLMBudget(BudgetConfig(window_seconds=3600, max_calls_per_window=240))
    general_pool = budget.config.general_pool
    while budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="trading_decision").granted:
        pass
    snapshot = budget.snapshot()
    assert snapshot["general_calls_in_window"] == general_pool
    assert budget.try_acquire(P0_POSITION_SAFETY, operation="position_exit").granted
    assert budget.try_acquire(P1_POSITION_LIFECYCLE, operation="position_review").granted


def test_p3_skip_does_not_create_directional_authority():
    chief = OptionalResearchDenyingChief(final_action="LONG")
    trader = ToolDrivenChiefTrader(chief, LLMToolRegistry())
    decision, _ = asyncio.run(
        trader.decide(context(), tool_context={}, now=datetime.now(UTC))
    )
    assert decision.action.value == "LONG"
    assert decision.thesis == "stub factual thesis"


def test_budget_snapshot_distinguishes_research_pressure_from_global_exhaustion():
    # reserve=0 keeps this test focused on the rolling-window ceiling itself.
    budget = GlobalLLMBudget(
        BudgetConfig(
            window_seconds=3600,
            max_calls_per_window=240,
            position_management_reserve=0,
        )
    )
    for _ in range(205):
        assert budget.try_acquire(
            P2_FINAL_ENTRY_DECISION, operation="trading_decision"
        ).granted
    snapshot = budget.snapshot()
    assert snapshot["calls_in_window"] == 205
    assert snapshot["global_budget_exhausted"] is False
    pressure = classify_budget_pressure(snapshot)
    assert "D4_P3_RESEARCH_BUDGET_EXHAUSTED" in pressure["codes"]
    assert "D4_GLOBAL_LLM_BUDGET_EXHAUSTED" not in pressure["codes"]
    assert pressure["verdict"] == "OPTIONAL_RESEARCH_BUDGET_PRESSURE"
