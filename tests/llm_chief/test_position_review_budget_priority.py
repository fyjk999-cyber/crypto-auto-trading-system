"""F1/F2: a position review must not be starved by entry/research traffic.

Observed production defect (runtime 460553f2)
---------------------------------------------
ETHFIUSDT had an OPEN position. Seven consecutive position reviews returned
FAIL_CLOSED with reason_codes ["SKIPPED_BUDGET"] and DeepSeek was never called.
The blocking acquire was NOT the position review itself:

    position_manager.review -> tool_chief.decide
      -> chief.select_tools                       (tool_orchestrator.py:41)
        -> budget.try_acquire(P3_SELECTED_SYMBOL_RESEARCH)   (engine.py:97)
          -> denied -> return None, "SKIPPED_BUDGET"
      -> fail_closed(ctx, error)                  (tool_orchestrator.py:52)

So the protected position reserve had capacity the whole time, while the review
died at an upstream RESEARCH gate - and the precise reason was thrown away and
flattened into the bare string "SKIPPED_BUDGET".

These tests pin the fix for both halves:
  * purpose inheritance: every model call belonging to a position review draws
    on the position-management priority, not the research tiers;
  * structured denial: each pool reports its own reason code end to end.
"""

from __future__ import annotations

from crypto_trader.llm_chief.budget import (
    P0_POSITION_SAFETY,
    P1_POSITION_LIFECYCLE,
    P2_FINAL_ENTRY_DECISION,
    P3_SELECTED_SYMBOL_RESEARCH,
    P4_MARKET_SELECTION,
    P5_BACKGROUND_RESEARCH,
    REASON_BACKGROUND_RESEARCH_BUDGET_EXHAUSTED,
    REASON_ENTRY_BUDGET_EXHAUSTED,
    REASON_GLOBAL_BUDGET_EXHAUSTED,
    REASON_MARKET_SELECTION_BUDGET_EXHAUSTED,
    REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED,
    REASON_SELECTED_SYMBOL_RESEARCH_BUDGET_EXHAUSTED,
    BudgetConfig,
    BudgetDenial,
    GlobalLLMBudget,
)
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import PositionState
from crypto_trader.llm_chief.engine import ChiefTraderEngine


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _engine(budget=None, provider=None):
    return ChiefTraderEngine(provider=provider or object(), budget=budget)


def _ctx(state: PositionState = PositionState.OPEN) -> ChiefTraderContext:
    return ChiefTraderContext(
        symbol="ETHFIUSDT",
        market_snapshot={},
        regime="RANGE",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        position_state=state,
        prepared_at="2026-01-01T00:00:00+00:00",
    )


# -------------------------------------------------------- purpose inheritance


def test_open_position_purpose_is_position_management():
    """F1: an OPEN position's whole workflow is position management."""
    engine = _engine()
    assert engine.purpose_priority(_ctx(PositionState.OPEN)) == P1_POSITION_LIFECYCLE


def test_flat_position_purpose_is_entry_decision():
    """F1: the entry path keeps its previous priority - no behaviour drift."""
    engine = _engine()
    assert engine.purpose_priority(_ctx(PositionState.FLAT)) == P2_FINAL_ENTRY_DECISION


def test_tool_selection_inherits_position_purpose():
    """F1: the upstream gate must not re-classify a review as P3 research."""
    import inspect

    source = inspect.getsource(ChiefTraderEngine.select_tools)
    assert "purpose_priority" in source, "tool selection still hardcodes its priority"
    assert "P3_SELECTED_SYMBOL_RESEARCH" not in source, (
        "tool selection still charges the research pool for a position review"
    )


# --------------------------------------------------------------------- B1


def test_B1_general_pool_exhausted_position_review_still_granted():
    """B1: with the general pool spent, a position review still acquires."""
    clock = _FakeClock()
    budget = GlobalLLMBudget(BudgetConfig(max_calls_per_window=120), clock=clock)
    config = budget.config
    assert config.general_pool == 60

    # Spend the GENERAL pool entirely through research/scanning/entry work.
    spent = 0
    while spent < config.general_pool:
        for priority in (P3_SELECTED_SYMBOL_RESEARCH, P4_MARKET_SELECTION,
                         P5_BACKGROUND_RESEARCH, P2_FINAL_ENTRY_DECISION):
            if spent >= config.general_pool:
                break
            if budget.try_acquire(priority, operation="general").granted:
                spent += 1
    assert spent == config.general_pool

    engine = _engine(budget)
    # The position review's tool-selection stage must still be grantable.
    ticket = budget.try_acquire(
        engine.purpose_priority(_ctx(PositionState.OPEN)), operation="tool_selection"
    )
    assert ticket.granted is True, "position review starved behind general traffic"
    assert ticket.priority == P1_POSITION_LIFECYCLE


def test_B1b_position_review_not_downgraded_to_research():
    """B1: the review's own decision call also uses the protected priority."""
    clock = _FakeClock()
    budget = GlobalLLMBudget(BudgetConfig(max_calls_per_window=120), clock=clock)
    while budget.try_acquire(P3_SELECTED_SYMBOL_RESEARCH, operation="r").granted:
        pass
    engine = _engine(budget)
    ctx = _ctx(PositionState.OPEN)
    ticket = budget.try_acquire(engine.purpose_priority(ctx), operation="trading_decision")
    assert ticket.granted is True


# --------------------------------------------------------------------- B2


def test_B2_entry_denied_while_position_allowed():
    """B2: entry research is throttled; the open position is not."""
    clock = _FakeClock()
    budget = GlobalLLMBudget(BudgetConfig(max_calls_per_window=120), clock=clock)
    while budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry").granted:
        pass
    entry = budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry")
    assert entry.granted is False
    assert entry.reason == REASON_ENTRY_BUDGET_EXHAUSTED

    review = budget.try_acquire(P1_POSITION_LIFECYCLE, operation="position_review")
    assert review.granted is True


# --------------------------------------------------------------------- B3


def test_B3_true_position_reserve_exhaustion_is_explicit():
    """B3: when the position capacity itself is spent, say so precisely."""
    clock = _FakeClock()
    # A reserve SMALLER than the window, so the reserve (not the global ceiling)
    # is what actually runs out - that is the case that must be named precisely.
    budget = GlobalLLMBudget(
        BudgetConfig(max_calls_per_window=100, position_management_reserve=6),
        clock=clock,
    )
    assert budget.config.reserve_calls == 6
    # Position management is deliberately NOT capped by the reserve: the reserve
    # protects it FROM general work, it does not limit how much it may do. So the
    # invariant is only that it eventually stops and says why.
    granted = 0
    while budget.try_acquire(P1_POSITION_LIFECYCLE, operation="position_review").granted:
        granted += 1
        assert granted <= budget.config.ceiling_for(P1_POSITION_LIFECYCLE)
    assert granted > 0
    denied = budget.try_acquire(P1_POSITION_LIFECYCLE, operation="position_review")
    assert denied.granted is False
    assert denied.reason == REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED


# --------------------------------------------------------------------- B4


def test_B4_each_pool_reports_its_own_reason_code():
    """B4: four separate exhaustions must yield four distinct codes."""
    codes = set()
    for priority in (
        P2_FINAL_ENTRY_DECISION,
        P3_SELECTED_SYMBOL_RESEARCH,
        P4_MARKET_SELECTION,
        P5_BACKGROUND_RESEARCH,
        P1_POSITION_LIFECYCLE,
    ):
        clock = _FakeClock()
        # reserve < window so the POOL is the binding constraint for P1, and the
        # general pool for the rest - i.e. pool exhaustion, not window exhaustion.
        budget = GlobalLLMBudget(
            BudgetConfig(max_calls_per_window=100, position_management_reserve=6),
            clock=clock,
        )
        while budget.try_acquire(priority, operation="x").granted:
            pass
        denied = budget.try_acquire(priority, operation="x")
        assert denied.granted is False
        assert denied.reason and denied.reason != "SKIPPED_BUDGET", (
            f"{priority} still reports the opaque SKIPPED_BUDGET"
        )
        codes.add(denied.reason)

    assert REASON_ENTRY_BUDGET_EXHAUSTED in codes
    assert REASON_SELECTED_SYMBOL_RESEARCH_BUDGET_EXHAUSTED in codes
    assert REASON_MARKET_SELECTION_BUDGET_EXHAUSTED in codes
    assert REASON_BACKGROUND_RESEARCH_BUDGET_EXHAUSTED in codes
    assert REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED in codes
    assert len(codes) >= 5


def test_B4b_pool_throttled_denial_names_the_pool_not_the_window():
    """B4: when the general POOL is the binding limit, say so.

    Realistic config (120 window / 60 reserve): ordinary work stops at the 60
    general pool while the window still has room, so the honest reason is the
    pool's, not a global one.
    """
    clock = _FakeClock()
    budget = GlobalLLMBudget(BudgetConfig(max_calls_per_window=120), clock=clock)
    config = budget.config
    while budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry").granted:
        pass
    snapshot = budget.snapshot()
    assert snapshot["general_calls_in_window"] == config.general_pool
    assert snapshot["calls_in_window"] < config.max_calls_per_window, (
        "the window must still have room - the pool is the binding limit"
    )
    denied = budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry")
    assert denied.reason == REASON_ENTRY_BUDGET_EXHAUSTED


def test_B4c_position_priority_at_the_ceiling_reports_position_exhaustion():
    """B4: a position priority that spent the whole window is POSITION.

    The reserve bounds only non-position work, so position management can
    legitimately consume the entire window; that is the case a supervisor must
    be able to see as position-management exhaustion.
    """
    clock = _FakeClock()
    budget = GlobalLLMBudget(BudgetConfig(max_calls_per_window=4), clock=clock)
    while budget.try_acquire(P1_POSITION_LIFECYCLE, operation="review").granted:
        pass
    assert budget.snapshot()["calls_in_window"] == 4
    denied = budget.try_acquire(P1_POSITION_LIFECYCLE, operation="review")
    assert denied.reason == REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED


def test_B4d_global_code_applies_when_position_work_consumed_the_window():
    """B4: a GENERAL priority refused because POSITION work took the window.

    With the window full and the general pool borrowed away by position use,
    ordinary work has no capacity at all - that is the global case.
    """
    clock = _FakeClock()
    budget = GlobalLLMBudget(BudgetConfig(max_calls_per_window=4), clock=clock)
    # Position work consumes the whole window (the reserve does not cap P1).
    while budget.try_acquire(P1_POSITION_LIFECYCLE, operation="review").granted:
        pass
    assert budget.snapshot()["calls_in_window"] == 4
    denied = budget.try_acquire(P3_SELECTED_SYMBOL_RESEARCH, operation="research")
    assert denied.granted is False
    assert denied.reason == REASON_GLOBAL_BUDGET_EXHAUSTED


def test_denial_facts_are_self_explaining():
    """F2: a denial must carry enough facts to be actionable on its own."""
    clock = _FakeClock()
    budget = GlobalLLMBudget(BudgetConfig(max_calls_per_window=6), clock=clock)
    while budget.try_acquire(P3_SELECTED_SYMBOL_RESEARCH, operation="ts").granted:
        pass
    denied = budget.try_acquire(P3_SELECTED_SYMBOL_RESEARCH, operation="ts")
    facts = BudgetDenial.from_ticket(denied).as_facts()
    for key in (
        "reason",
        "priority",
        "operation",
        "budget_pool",
        "effective_ceiling",
        "current_usage",
        "total_limit",
    ):
        assert key in facts, f"denial facts lost {key}"
    assert facts["reason"] == REASON_SELECTED_SYMBOL_RESEARCH_BUDGET_EXHAUSTED
    assert facts["budget_pool"] == "GENERAL"
    assert facts["total_limit"] == 6


def test_denial_reason_survives_tool_selection_path():
    """F2: select_tools must return the REASON, never a bare SKIPPED_BUDGET."""
    import inspect

    source = inspect.getsource(ChiefTraderEngine.select_tools)
    assert "BudgetDenial.from_ticket" in source, (
        "tool selection discards the structured denial"
    )
    assert 'return None, "SKIPPED_BUDGET"' not in source


def test_position_management_priorities_are_the_protected_set():
    """Guard: the protected set must stay P0/P1 only."""
    from crypto_trader.llm_chief.budget import POSITION_MANAGEMENT_PRIORITIES

    assert POSITION_MANAGEMENT_PRIORITIES == (P0_POSITION_SAFETY, P1_POSITION_LIFECYCLE)


def test_budget_limits_are_unchanged():
    """§5: no budget increase is part of this fix."""
    config = BudgetConfig()
    assert config.window_seconds == 3600
    assert config.max_calls_per_window == 120
    assert config.reserve_calls == 60
    assert config.general_pool == 60
