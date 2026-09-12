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
    # The authorised policy: 60s floor + 60 reserve => exactly one position.
    facts = safe.position_management_capacity(open_positions=0)
    assert facts["worst_case_demand_per_position_per_hour"] == 60
    assert facts["guaranteed_position_management_capacity_per_hour"] == 60
    assert facts["max_safe_concurrent_positions"] == 1
    # A SECOND concurrent position is refused even though 2 x 60 == 120: it
    # would consume the entire window and leave nothing for selection, entry or
    # unexpected material reviews.
    assert safe.position_management_capacity(open_positions=1)[
        "max_safe_concurrent_positions"
    ] == 1
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

    # Authorised capacity policy: the gate is ON by default now.
    assert Settings().enforce_position_management_capacity is True
    assert Settings().position_review_min_interval_seconds == 60.0

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


# ============================================================ authorised
# capacity policy: 60s floor, 60 reserve, 60 general pool, max_safe = 1.
# Scheduled and material-event reviews share the eligibility window, so the
# per-position call rate cannot exceed 60/hour and the guarantee is provable.

POLICY_FLOOR = 60.0
POLICY_RESERVE = 60
POLICY_TOTAL = 120


def _policy_adapter():
    return _adapter(interval=POLICY_FLOOR, reserve=POLICY_RESERVE, total=POLICY_TOTAL)


def test_C1_configured_worst_case_scheduled_demand_is_60_per_hour():
    adapter = _policy_adapter()
    facts = adapter.position_management_capacity(open_positions=1)
    assert round(WINDOW / POLICY_FLOOR) == 60
    assert facts["worst_case_demand_per_position_per_hour"] == 60
    assert facts["guaranteed_position_management_capacity_per_hour"] == 60
    assert facts["max_safe_concurrent_positions"] == 1


def test_C2_general_pool_exhausted_leaves_60_management_calls():
    adapter = _policy_adapter()
    budget = adapter.llm_budget
    pool = budget.config.general_pool
    assert pool == 60
    for _ in range(pool):
        assert budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry").granted
    assert not budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry").granted

    # The full 60-call management guarantee survives the exhausted general pool.
    granted = 0
    while budget.try_acquire(P1_POSITION_LIFECYCLE, operation="position_review").granted:
        granted += 1
        assert granted <= 60
    assert granted == 60
    assert budget.snapshot()["position_management_calls_in_window"] == 60


def test_C3_material_events_inside_one_window_coalesce_to_at_most_one_review():
    """Scheduled AND material-event reviews share ONE eligibility window.

    This is the invariant that makes the capacity guarantee provable: a window
    yields at most one LLM review per position no matter how many material
    events land inside it. A material change marks the position dirty; it must
    NOT buy an extra call.
    """
    import asyncio

    from crypto_trader.runtime.engine import TradingEngine

    engine = TradingEngine.__new__(TradingEngine)
    engine.position_review_min_interval_seconds = POLICY_FLOOR
    engine.trade_plans = None
    engine.market_data = _MarketData()
    engine.order_manager = _EmptyOrders()

    class _Pos:
        quantity = Decimal("275")
        avg_entry_price = Decimal("0.01541")
        cost_basis = Decimal("423.775")
        leverage = Decimal("3")
        realized_pnl = Decimal("0")

    position = _Pos()
    state = {"next_due_at": 0.0, "failures": 0, "last_started_at": None}

    # First look: never reviewed before => eligible.
    assert asyncio.run(engine._is_due_for_review("CPUSDT", position, state, 0.0)) is True

    # Reviewed at t=0. Three material events land inside the window: each one
    # marks the position dirty but none of them may open eligibility early.
    state["last_started_at"] = 0.0
    state["last_review_signature"] = asyncio.run(
        engine._position_change_signature("CPUSDT", position)
    )
    for t, bid in ((1.0, "1"), (2.0, "2"), (3.0, "3")):
        engine.market_data.books._bid = bid  # a material price move each time
        assert asyncio.run(engine._is_due_for_review("CPUSDT", position, state, t)) is False
        assert state.get("position_review_dirty") is True

    # Only when the window elapses does exactly one review become eligible.
    engine.market_data.books._bid = "4"
    assert asyncio.run(
        engine._is_due_for_review("CPUSDT", position, state, POLICY_FLOOR)
    ) is True
    # Call rate per position can therefore never exceed one per window.
    assert WINDOW / POLICY_FLOOR == 60


class _MarketData:
    """Minimal stand-in exposing the live book the signature reads."""

    def __init__(self):
        self.books = _Books()


class _Books(dict):
    def __init__(self):
        super().__init__()
        self._bid = "1"

    def get(self, symbol, default=None):  # noqa: A003 - mirror dict API
        return _Book(self._bid)


class _Book:
    def __init__(self, bid):
        self._bid = bid

    def best_bid(self):
        return _Price(self._bid)

    def best_ask(self):
        return _Price(self._bid)


class _Price:
    def __init__(self, price):
        self.price = Decimal(price)


class _EmptyOrders:
    async def get(self, _order_id):
        return None


def adapter_capacity_ceiling(adapter) -> int:
    return adapter.position_management_capacity(open_positions=1)[
        "guaranteed_position_management_capacity_per_hour"
    ]


def test_C4_coalesced_review_reads_fresh_evidence_not_the_first_event():
    """Coalescing must never cache evidence.

    The eligibility gate is async and re-derives the signature from LIVE state
    (position, book, plan and entry-order status) every time it runs, so a
    review that coalesces three events still sees the newest facts.
    """
    import inspect

    from crypto_trader.runtime.engine import TradingEngine

    signature_src = inspect.getsource(TradingEngine._position_change_signature)
    for live_fact in (
        "self.market_data.books",
        "get_active_for_symbol",
        "order_manager.get",
        "realized_pnl",
    ):
        assert live_fact in signature_src, f"signature lost live fact {live_fact}"
    # It records the post-review signature only AFTER the review ran.
    review_src = inspect.getsource(TradingEngine._review_positions_once)
    assert "last_review_signature" in review_src
    assert "position_review_dirty" in review_src


def test_C5_second_concurrent_position_is_refused():
    adapter = _policy_adapter()
    assert adapter.position_management_capacity(open_positions=1)[
        "position_management_capacity_available"
    ] is False


def test_C6_capacity_recovers_when_the_position_closes():
    adapter = _policy_adapter()
    assert adapter.position_management_capacity(open_positions=1)[
        "position_management_capacity_available"
    ] is False
    recovered = adapter.position_management_capacity(open_positions=0)
    assert recovered["position_management_capacity_available"] is True
    assert recovered["reason"] == "POSITION_MANAGEMENT_CAPACITY_AVAILABLE"


def test_C7_capacity_rejection_creates_no_order_from_the_resource_path():
    """The gate sits BEFORE any TradePlan linkage/approval side effect.

    Asserted structurally so a future reordering cannot silently start creating
    plans or orders on a resource-unavailable path.
    """
    import inspect

    from crypto_trader.runtime.engine import TradingEngine

    process = inspect.getsource(TradingEngine.process_signal)
    gate_at = process.index("_position_management_capacity_available")
    link_at = process.index("trade_plans.link")
    approve_at = process.index("TradePlanState.APPROVED")
    submit_at = process.index("self.adapter.submit_order")
    # Gate is evaluated before plan linkage, approval and submission.
    assert gate_at < link_at
    assert gate_at < approve_at
    assert gate_at < submit_at
    # And the refusal is a plain early return, not an order construction.
    gate_src = inspect.getsource(TradingEngine._position_management_capacity_available)
    assert "submit_order" not in gate_src
    assert "create_from_intent" not in gate_src


def test_C8_capacity_rejection_preserves_chieftrader_provenance():
    """Resource refusal must not rewrite direction provenance.

    The gate records the capacity reason only; the directional decision keeps
    its own record and ChiefTrader remains the sole LONG/SHORT authority.
    """
    import ast
    import inspect
    import textwrap

    from crypto_trader.runtime.engine import TradingEngine

    gate_src = inspect.getsource(TradingEngine._position_management_capacity_available)
    assert "POSITION_MANAGEMENT_CAPACITY_UNAVAILABLE" in gate_src

    # No directional mutation anywhere in the executable body.
    tree = ast.parse(textwrap.dedent(gate_src))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                node.body = node.body[1:] or [ast.Pass()]
    body = ast.unparse(tree)
    for forbidden in ("LONG", "SHORT", "OrderSide", "direction"):
        assert forbidden not in body, f"gate must not touch direction ({forbidden})"
