"""Phase 5: three memory speeds with promotion and demotion."""

from __future__ import annotations

from crypto_trader.learning.memory_speeds import (
    MemoryRecord,
    apply_observation,
    promotion_summary,
)


def _observe(record: MemoryRecord, *, n: int, net: float, regimes: list[str] | None = None):
    for index in range(n):
        apply_observation(
            record,
            net_bps=net,
            regime=(regimes or ["TREND"])[index % len(regimes or ["TREND"])],
            win=net >= 0,
        )
    return record


def test_single_episode_is_fast_experience() -> None:
    record = _observe(MemoryRecord(key="k1", signature="breakout+high_cvd"), n=1, net=12.0)
    assert record.speed == "FAST_EXPERIENCE"
    assert record.can_modify_core is False


def test_repeated_cost_adjusted_edge_promotes_to_pattern() -> None:
    record = _observe(MemoryRecord(key="k2", signature="range+weak_cvd"), n=6, net=4.0)
    assert record.speed == "PATTERN"
    assert record.expectancy_bps == 4.0


def test_many_regimes_promote_to_validated_knowledge() -> None:
    # OLD: 21 samples promoted to VALIDATED_KNOWLEDGE.
    # NEW: memory-policy-v2 requires >=100 samples plus post-cost/multi-regime/stability.
    # WHY: avoid premature "20 samples = validated" promotion.
    record = _observe(
        MemoryRecord(key="k3", signature="trend_pullback"),
        n=100,
        net=5.0,
        regimes=["TREND_UP", "TREND_DOWN", "RANGE"],
    )
    assert record.speed == "VALIDATED_KNOWLEDGE"


def test_contradiction_demotes_but_never_grants_core_access() -> None:
    # OLD: demotion started from a 21-sample VALIDATED record.
    # NEW: the validated tier requires 100 samples under memory-policy-v2.
    # WHY: demotion semantics are unchanged; only the promotion threshold moved.
    record = _observe(
        MemoryRecord(key="k4", signature="late_breakout"),
        n=100,
        net=5.0,
        regimes=["TREND_UP", "TREND_DOWN", "RANGE"],
    )
    assert record.speed == "VALIDATED_KNOWLEDGE"
    apply_observation(record, net_bps=-30.0, regime="RANGE", win=False)
    assert record.speed == "PATTERN"
    assert record.demotions == 1
    assert record.can_modify_core is False


def test_promotion_summary_is_learning_only() -> None:
    record = _observe(MemoryRecord(key="k5", signature="s"), n=2, net=1.0)
    summary = promotion_summary(record)
    assert summary["authority"] == "LEARNING_ONLY"
    assert summary["is_order"] is False
    assert summary["can_modify_core"] is False
