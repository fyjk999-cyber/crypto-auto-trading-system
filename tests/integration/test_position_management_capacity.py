"""P2: position-management capacity must be PROVEN, not assumed.

The reserve in the budget work is only meaningful if it actually covers the
worst-case management demand of the positions the system will admit. This file
computes that number instead of trusting a green suite, and it deliberately
EXPOSES the case where the reserve is insufficient rather than hiding it.
"""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.llm_chief.budget import (
    P1_POSITION_LIFECYCLE,
    P2_FINAL_ENTRY_DECISION,
    REASON_ENTRY_BUDGET_EXHAUSTED,
    REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED,
    BudgetConfig,
    GlobalLLMBudget,
)
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter

WINDOW = 3600.0


def _adapter(*, interval: float, reserve: int, window: float = WINDOW, total: int = 120):
    adapter = SimulatedExchangeAdapter(initial_balances={"USDT": Decimal("100000")})
    adapter.llm_budget = GlobalLLMBudget(
        BudgetConfig(
            window_seconds=window,
            max_calls_per_window=total,
            position_management_reserve=reserve,
        )
    )
    adapter.position_review_min_interval_seconds = interval
    return adapter


# ------------------------------------------------------------------ P2-T1
def test_P2_T1_general_pool_exhausted_position_within_capacity_still_reviews():
    """Within guaranteed capacity, a spent general pool must not block reviews."""
    adapter = _adapter(interval=60.0, reserve=60)
    budget = adapter.llm_budget
    capacity = adapter.position_management_capacity(open_positions=0)
    assert capacity["max_safe_concurrent_positions"] >= 1

    pool = budget.config.general_pool
    for _ in range(pool):
        assert budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry").granted
    assert not budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry").granted

    # Management still has its guaranteed share.
    ticket = budget.try_acquire(P1_POSITION_LIFECYCLE, operation="position_review")
    assert ticket.granted is True


# ------------------------------------------------------------------ P2-T2
def test_P2_T2_insufficient_reserve_is_exposed_not_hidden():
    """A reserve smaller than one position's worst-case demand is NOT proven.

    This test exists to FAIL LOUDLY if someone shrinks the reserve and still
    claims the priority ordering is proven.
    """
    adapter = _adapter(interval=30.0, reserve=60)
    facts = adapter.position_management_capacity(open_positions=0)
    worst_case = facts["worst_case_demand_per_position_per_hour"]
    guaranteed = facts["guaranteed_position_management_capacity_per_hour"]

    # One position on a 30s floor needs the WHOLE window: the reserve cannot
    # cover it, so no position is provably manageable at that cadence.
    assert worst_case == 120
    assert guaranteed == 60
    assert worst_case > guaranteed
    # The honest consequence: zero safe positions under this configuration.
    assert facts["max_safe_concurrent_positions"] == 0
    assert facts["position_management_capacity_available"] is False
    assert facts["reason"] == "POSITION_MANAGEMENT_CAPACITY_UNAVAILABLE"


def test_P2_T2b_capacity_is_provable_only_at_a_safer_cadence():
    """With a cadence the budget can actually cover, capacity becomes provable."""
    safe = _adapter(interval=60.0, reserve=60)
    facts = safe.position_management_capacity(open_positions=0)
    assert facts["worst_case_demand_per_position_per_hour"] == 60
    assert facts["max_safe_concurrent_positions"] == 1
    assert facts["position_management_capacity_available"] is True
    assert facts["reason"] == "POSITION_MANAGEMENT_CAPACITY_AVAILABLE"


# ------------------------------------------------------------------ P2-T3
def test_P2_T3_unsafe_extra_position_is_refused():
    """Admitting a second position beyond capacity must not be available."""
    adapter = _adapter(interval=60.0, reserve=60)
    assert adapter.position_management_capacity(open_positions=0)[
        "position_management_capacity_available"
    ] is True
    facts = adapter.position_management_capacity(open_positions=1)
    assert facts["projected_open_positions"] == 2
    assert facts["position_management_capacity_available"] is False
    assert facts["reason"] == "POSITION_MANAGEMENT_CAPACITY_UNAVAILABLE"


# ------------------------------------------------------------------ P2-T4
def test_P2_T4_capacity_is_released_when_a_position_closes():
    adapter = _adapter(interval=60.0, reserve=60)
    assert adapter.position_management_capacity(open_positions=0)[
        "position_management_capacity_available"
    ] is True
    assert adapter.position_management_capacity(open_positions=1)[
        "position_management_capacity_available"
    ] is False
    # Once the position closes, eligibility recovers with no state to reset.
    assert adapter.position_management_capacity(open_positions=0)[
        "position_management_capacity_available"
    ] is True


# ------------------------------------------------------------------ P2-T5
def test_P2_T5_multiple_positions_consume_the_whole_management_capacity():
    """More positions than capacity must be refused for every extra one."""
    adapter = _adapter(interval=60.0, reserve=60)
    for open_positions in (0, 1, 2, 5):
        facts = adapter.position_management_capacity(open_positions=open_positions)
        expected = (open_positions + 1) <= facts["max_safe_concurrent_positions"]
        assert facts["position_management_capacity_available"] is expected, open_positions


# ------------------------------------------------------------------ P2-T6
def test_P2_T6_exhaustion_reasons_never_masquerade_as_each_other():
    budget = GlobalLLMBudget(
        BudgetConfig(window_seconds=WINDOW, max_calls_per_window=10, position_management_reserve=4)
    )
    while budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry").granted:
        pass
    entry_denied = budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry")
    assert entry_denied.reason == REASON_ENTRY_BUDGET_EXHAUSTED

    while budget.try_acquire(P1_POSITION_LIFECYCLE, operation="position_review").granted:
        pass
    position_denied = budget.try_acquire(P1_POSITION_LIFECYCLE, operation="position_review")
    assert position_denied.reason == REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED
    assert entry_denied.reason != position_denied.reason

    snapshot = budget.snapshot()
    assert snapshot["skipped_by_reason"].get(REASON_ENTRY_BUDGET_EXHAUSTED, 0) >= 1
    assert snapshot["skipped_by_reason"].get(
        REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED, 0
    ) >= 1


def test_P2_capacity_gate_is_not_direction_authority():
    """The gate must be authority-neutral and opt-in.

    It may only make an entry WAIT, and it must not be enabled by default so it
    cannot silently change admission behaviour in environments that did not ask
    for it.
    """
    import ast
    import inspect
    import textwrap

    from crypto_trader.config import Settings
    from crypto_trader.runtime.engine import TradingEngine

    assert Settings().enforce_position_management_capacity is False

    # Inspect EXECUTABLE code only: the docstring legitimately names LONG/SHORT
    # when explaining that ChiefTrader keeps sole authority over them.
    func = TradingEngine._position_management_capacity_available
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                node.body = node.body[1:] or [ast.Pass()]
    body = ast.unparse(tree)
    for forbidden in ("LONG", "SHORT", "OrderSide", "create_entry_signal"):
        assert forbidden not in body, f"gate must not touch direction ({forbidden})"
    # Fail closed when capacity cannot be computed.
    assert "return False" in body
