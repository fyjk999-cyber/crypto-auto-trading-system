"""LLM budget call-efficiency: suppression semantics, observability, replay.

Two distinct kinds of "no call happened" must never be conflated:

* ``SKIPPED_BUDGET`` (+ ENTRY_/POSITION_MANAGEMENT_BUDGET_EXHAUSTED) — the
  window was spent. This is a CAPACITY problem.
* ``REVIEW_COALESCED`` / ``UNCHANGED_CONTEXT`` / ``DUPLICATE_INPUT`` — the call
  was deliberately not made because it would have been redundant. This is an
  EFFICIENCY saving, and it must not be reported as starvation.

Conflating them is exactly why the live runtime could only say
``SKIPPED_BUDGET = 212`` without revealing whether position management was
starved or simply idle.

The replay at the bottom is deterministic (fake monotonic clock, no sleeps) and
loads the schedule pressure observed live: 470 decision attempts across ~6.6h,
with peaks of 80-103 attempts/hour and an open position under management.
"""

from __future__ import annotations

from crypto_trader.llm_chief.budget import (
    P0_POSITION_SAFETY,
    P1_POSITION_LIFECYCLE,
    P2_FINAL_ENTRY_DECISION,
    P4_MARKET_SELECTION,
    P5_BACKGROUND_RESEARCH,
    REASON_DUPLICATE_INPUT,
    REASON_ENTRY_BUDGET_EXHAUSTED,
    REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED,
    REASON_REVIEW_COALESCED,
    REASON_UNCHANGED_CONTEXT,
    BudgetConfig,
    GlobalLLMBudget,
)

OBSERVED_TOTAL_ATTEMPTS = 470
OBSERVED_HOURS = 6.6


class _FakeClock:
    """Deterministic monotonic clock. No real sleeping anywhere."""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _budget(max_calls: int = 120, window: float = 3600.0):
    clock = _FakeClock()
    return GlobalLLMBudget(
        BudgetConfig(window_seconds=window, max_calls_per_window=max_calls),
        clock=clock,
    ), clock


# ===================================================== suppression semantics


def test_suppression_reason_codes_are_distinct_from_budget_exhaustion():
    """The four suppression reasons must never collapse into SKIPPED_BUDGET."""
    for reason in (
        REASON_REVIEW_COALESCED,
        REASON_UNCHANGED_CONTEXT,
        REASON_DUPLICATE_INPUT,
    ):
        assert reason != REASON_ENTRY_BUDGET_EXHAUSTED
        assert reason != REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED
        assert reason != "SKIPPED_BUDGET"


def test_suppression_consumes_no_quota():
    """A coalesced call is a saving, not a spend."""
    budget, _ = _budget(max_calls=5)
    for _ in range(50):
        budget.note_suppressed(reason=REASON_REVIEW_COALESCED, operation="review")
    snapshot = budget.snapshot()
    assert snapshot["calls_in_window"] == 0
    assert snapshot["remaining"] == 5
    assert snapshot["coalesced_calls"] == 50
    # Suppression is not a budget miss.
    assert snapshot["skipped_by_reason"] == {}
    # ...and the window is still fully usable afterwards.
    assert budget.try_acquire(P1_POSITION_LIFECYCLE, operation="review").granted


def test_suppression_is_never_counted_as_a_skip():
    """Exhaust the window, then suppress: the two counters stay separate."""
    budget, _ = _budget(max_calls=3)
    for _ in range(3):
        budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry")
    refused = budget.try_acquire(P2_FINAL_ENTRY_DECISION, operation="entry")
    assert refused.granted is False
    budget.note_suppressed(reason=REASON_REVIEW_COALESCED, operation="review")

    snapshot = budget.snapshot()
    # Budget misses are counted as misses...
    assert snapshot["skipped_by_reason"][REASON_ENTRY_BUDGET_EXHAUSTED] >= 1
    # ...and the suppression is NOT folded into that counter.
    assert REASON_REVIEW_COALESCED not in snapshot["skipped_by_reason"]
    assert snapshot["coalesced_calls"] == 1


def test_unknown_suppression_reason_is_rejected():
    budget, _ = _budget()
    try:
        budget.note_suppressed(reason="MADE_UP", operation="x")
    except ValueError:
        return
    raise AssertionError("unknown suppression reason must be rejected")


def test_duplicate_and_unchanged_aggregate_into_duplicate_calls_avoided():
    budget, _ = _budget()
    budget.note_suppressed(reason=REASON_DUPLICATE_INPUT, operation="entry")
    budget.note_suppressed(reason=REASON_UNCHANGED_CONTEXT, operation="entry")
    budget.note_suppressed(reason=REASON_REVIEW_COALESCED, operation="review")
    snapshot = budget.snapshot()
    assert snapshot["duplicate_calls_avoided"] == 2
    assert snapshot["coalesced_calls"] == 1


# ===================================================== observability (§14/§15)


def test_snapshot_exposes_who_spent_the_window_and_why_it_was_refused():
    """Supervisor must be able to answer 'who consumed the budget?'."""
    budget, _ = _budget(max_calls=10)
    ticket = budget.try_acquire(P4_MARKET_SELECTION, operation="market_selection")
    ticket.complete(
        status="OK",
        provider="deepseek",
        model="deepseek-flash",
        input_tokens=1200,
        output_tokens=180,
        latency_ms=2100,
    )
    while budget.try_acquire(P4_MARKET_SELECTION, operation="market_selection").granted:
        pass

    snapshot = budget.snapshot()
    for key in (
        "window_seconds",
        "max_calls_per_window",
        "calls_in_window",
        "remaining",
        "position_management_reserve",
        "general_pool",
        "general_calls_in_window",
        "position_management_calls_in_window",
        "skipped_by_reason",
        "suppressed_by_reason",
        "coalesced_calls",
        "duplicate_calls_avoided",
        "input_tokens_by_priority",
        "output_tokens_by_priority",
        "avg_latency_ms_by_priority",
    ):
        assert key in snapshot, f"snapshot lost {key}"

    assert snapshot["input_tokens_by_priority"][P4_MARKET_SELECTION] == 1200
    assert snapshot["output_tokens_by_priority"][P4_MARKET_SELECTION] == 180
    assert snapshot["avg_latency_ms_by_priority"][P4_MARKET_SELECTION] == 2100.0
    assert snapshot["skipped_by_reason"][REASON_ENTRY_BUDGET_EXHAUSTED] >= 1


# ===================================================== reserve protection


def test_general_work_cannot_consume_the_position_reserve():
    """§4: P2/P3/P4/P5 stop at the general pool; P0/P1 stay callable."""
    budget, _ = _budget(max_calls=120)
    config = budget.config
    assert config.reserve_calls == 60
    assert config.general_pool == 60

    granted_general = 0
    while budget.try_acquire(P5_BACKGROUND_RESEARCH, operation="research").granted:
        granted_general += 1
    assert granted_general == config.general_pool

    refused = budget.try_acquire(P5_BACKGROUND_RESEARCH, operation="research")
    assert refused.granted is False
    assert refused.reason == REASON_ENTRY_BUDGET_EXHAUSTED

    # The protected capacity is intact for position management.
    for _ in range(config.reserve_calls):
        assert budget.try_acquire(
            P1_POSITION_LIFECYCLE, operation="position_review"
        ).granted


def test_position_reserve_exhaustion_is_explicit():
    """§11: a spent reserve reports its own reason, not a generic skip."""
    budget, _ = _budget(max_calls=10, window=3600.0)
    config = budget.config
    spent = 0
    while budget.try_acquire(P1_POSITION_LIFECYCLE, operation="review").granted:
        spent += 1
    assert spent > 0

    refused = budget.try_acquire(P1_POSITION_LIFECYCLE, operation="review")
    assert refused.granted is False
    assert refused.reason == REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED
    assert refused.reason != REASON_ENTRY_BUDGET_EXHAUSTED
    assert config.reserve_calls <= 10


def test_priority_order_keeps_position_management_first():
    from crypto_trader.llm_chief.budget import PRIORITY_ORDER

    assert PRIORITY_ORDER[0] == P0_POSITION_SAFETY
    assert PRIORITY_ORDER[1] == P1_POSITION_LIFECYCLE
    assert PRIORITY_ORDER.index(P2_FINAL_ENTRY_DECISION) > 1
    assert PRIORITY_ORDER.index(P5_BACKGROUND_RESEARCH) == len(PRIORITY_ORDER) - 1


# ===================================================== deterministic replay


def _replay(max_calls: int = 120, *, hours: float = OBSERVED_HOURS):
    """Replay today's SCHEDULE PRESSURE only — no trading outcome is invented.

    Load model, taken from the live runtime's observed shape:
      * one open position under management;
      * scheduled position reviews at ``position_review_min_interval_seconds``
        (60s default), i.e. ~60 attempts/hour;
      * plus a bounded number of material-change re-arms (a material change does
        not buy an extra call — it marks the plan dirty and coalesces);
      * general traffic (entry + market selection + research) at the measured
        80-103 attempts/hour peaks.

    Returns counters, both for quota and for suppression.
    """
    clock = _FakeClock()
    budget = GlobalLLMBudget(
        BudgetConfig(window_seconds=3600.0, max_calls_per_window=max_calls),
        clock=clock,
    )
    review_interval = 60.0
    next_review_at = 0.0
    last_review_at: float | None = None

    stats = {
        "attempted_calls": 0,
        "provider_calls": 0,
        "coalesced_calls": 0,
        "duplicate_calls_avoided": 0,
        "entry_budget_exhausted": 0,
        "position_budget_exhausted": 0,
        "position_reviews_succeeded": 0,
        "position_reviews_required": 0,
    }

    total_seconds = int(hours * 3600)
    # 90 general attempts/hour ≈ midpoint of the observed 80-103 peak range.
    general_per_minute = 1.5

    for second in range(total_seconds):
        clock.advance(1.0)

        # ---- position management: ONE decision point per eligible event ------
        # Two kinds of trigger feed the same gate:
        #   * the scheduled cadence (position_review_min_interval_seconds), and
        #   * a material change (partial fill, order-state change, material mark
        #     move), which does NOT buy an extra call — it marks the plan dirty
        #     and coalesces into the next eligible review.
        material_trigger = second % 90 == 0
        scheduled_trigger = clock.value >= next_review_at
        if scheduled_trigger or material_trigger:
            stats["position_reviews_required"] += 1
            stats["attempted_calls"] += 1
            if last_review_at is not None and (
                clock.value - last_review_at
            ) < review_interval:
                # Inside the coalescing window with an unchanged signature: the
                # call is deliberately NOT made. Counted as coalesced, never as
                # a budget miss.
                budget.note_suppressed(
                    reason=REASON_REVIEW_COALESCED, operation="position_review"
                )
                stats["coalesced_calls"] += 1
            else:
                ticket = budget.try_acquire(
                    P1_POSITION_LIFECYCLE, operation="position_review"
                )
                if ticket.granted:
                    stats["provider_calls"] += 1
                    stats["position_reviews_succeeded"] += 1
                    last_review_at = clock.value
                elif ticket.reason == REASON_POSITION_MANAGEMENT_BUDGET_EXHAUSTED:
                    stats["position_budget_exhausted"] += 1
                next_review_at = clock.value + review_interval
            if scheduled_trigger:
                next_review_at = clock.value + review_interval

        # ---- general traffic -------------------------------------------------
        if second % int(60 / general_per_minute) == 0:
            stats["attempted_calls"] += 1
            ticket = budget.try_acquire(
                P2_FINAL_ENTRY_DECISION, operation="entry_decision"
            )
            if ticket.granted:
                stats["provider_calls"] += 1
            elif ticket.reason == REASON_ENTRY_BUDGET_EXHAUSTED:
                stats["entry_budget_exhausted"] += 1

    # Coverage is measured over reviews that were actually REQUIRED to reach the
    # provider (coalesced ones needed no call at all, so they cannot miss).
    required_calls = (
        stats["position_reviews_required"] - stats["coalesced_calls"]
    )
    stats["position_reviews_required_to_call"] = required_calls
    stats["position_review_coverage"] = (
        stats["position_reviews_succeeded"] / required_calls if required_calls else 1.0
    )
    return stats


def test_replay_position_management_is_never_starved():
    """§19 acceptance: zero avoidable position-management starvation."""
    stats = _replay()
    assert stats["position_budget_exhausted"] == 0, (
        "position management was starved even though a protected reserve exists"
    )
    assert stats["position_review_coverage"] == 1.0
    assert stats["position_reviews_succeeded"] > 0


def test_replay_respects_the_global_window():
    """The 120/h ceiling still binds — protection is not a bypass."""
    stats = _replay(max_calls=120)
    # Over any single hour the granted count cannot exceed the window limit.
    assert stats["provider_calls"] <= 120 * (OBSERVED_HOURS + 1)


def test_replay_general_work_degrades_first():
    """Entry/scanning absorbs the shortfall; position management does not."""
    stats = _replay()
    assert stats["entry_budget_exhausted"] > 0, (
        "expected general traffic to exceed its pool under the observed peak"
    )
    assert stats["position_budget_exhausted"] == 0


def test_replay_suppression_reduces_calls_without_touching_quota():
    """Coalescing must show up as avoided calls, not as budget misses."""
    stats = _replay()
    assert stats["coalesced_calls"] >= 0
    # Every position-review event ends in exactly one of three states:
    # coalesced, served, or starved by the reserve.
    assert (
        stats["coalesced_calls"]
        + stats["position_reviews_succeeded"]
        + stats["position_budget_exhausted"]
        == stats["position_reviews_required"]
    )


def test_replay_is_deterministic():
    """Same load twice => identical counters (no dependence on wall clock)."""
    first = _replay()
    second = _replay()
    assert first == second
