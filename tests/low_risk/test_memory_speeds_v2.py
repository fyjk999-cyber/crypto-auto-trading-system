from sqlalchemy import func, select

from crypto_trader.learning.memory_speed_store import MemorySpeedStore
from crypto_trader.learning.memory_speeds import (
    MemoryRecord,
    MemorySpeed,
    apply_observation,
    classify_speed,
    promotion_summary,
    sample_tier,
)
from crypto_trader.persistence.models import GrowthMemorySpeedORM


def _record(observations, regimes, post_cost, **kwargs):
    return MemoryRecord(
        key="k",
        signature="BTCUSDT|TREND_UP|breakout|15m|sig1",
        observations=observations,
        wins=int(observations * 0.6),
        net_bps_total=observations * max(post_cost, 0.0),
        regimes=list(regimes),
        post_cost_expectancy_bps=post_cost,
        **kwargs,
    )


def test_sample_tiers_and_no_premature_validated():
    assert sample_tier(0) == "PROVISIONAL"
    assert sample_tier(19) == "PROVISIONAL"
    assert sample_tier(20) == "EMERGING"
    assert sample_tier(49) == "EMERGING"
    assert sample_tier(50) == "CANDIDATE"
    assert sample_tier(99) == "CANDIDATE"
    assert sample_tier(100) == "FORMAL_VALIDATION_ELIGIBLE"
    twenty = _record(20, ["A", "B", "C"], 5.0)
    assert classify_speed(twenty) != MemorySpeed.VALIDATED_KNOWLEDGE.value


def test_validated_requires_100_post_cost_multi_regime_stability():
    good = _record(100, ["A", "B", "C"], 5.0)
    assert classify_speed(good) == MemorySpeed.VALIDATED_KNOWLEDGE.value
    contradiction = _record(100, ["A", "B", "C"], 5.0, unresolved_contradictions=1)
    assert classify_speed(contradiction) != MemorySpeed.VALIDATED_KNOWLEDGE.value
    unstable = _record(100, ["A", "B", "C"], 5.0, chronological_stable=False)
    assert classify_speed(unstable) != MemorySpeed.VALIDATED_KNOWLEDGE.value
    negative = _record(100, ["A", "B", "C"], -1.0)
    assert classify_speed(negative) != MemorySpeed.VALIDATED_KNOWLEDGE.value
    few_regimes = _record(100, ["A"], 5.0)
    assert classify_speed(few_regimes) != MemorySpeed.VALIDATED_KNOWLEDGE.value


def test_contradiction_demotes_existing_validated_record():
    record = _record(100, ["A", "B", "C"], 5.0)
    record.speed = MemorySpeed.VALIDATED_KNOWLEDGE.value
    apply_observation(record, net_bps=-3.0, regime="A", win=False, contradiction=True)
    assert record.speed == MemorySpeed.PATTERN.value
    assert record.unresolved_contradictions == 1
    assert record.can_modify_core is False
    summary = promotion_summary(record)
    assert summary["policy_version"] == "memory-policy-v2"
    assert summary["can_modify_core"] is False and summary["is_order"] is False


async def test_memory_speed_persistence_and_restart(database):
    record = _record(100, ["A", "B", "C"], 5.0)
    record.speed = MemorySpeed.VALIDATED_KNOWLEDGE.value
    store = MemorySpeedStore(database.session_factory)
    summary = await store.save(record)
    assert summary["sample_tier"] == "FORMAL_VALIDATION_ELIGIBLE"
    restarted = MemorySpeedStore(database.session_factory)
    loaded = await restarted.load("k")
    assert loaded is not None and loaded.speed == MemorySpeed.VALIDATED_KNOWLEDGE.value
    assert loaded.post_cost_expectancy_bps == 5.0 and loaded.can_modify_core is False
    record.observations = 101
    await store.save(record)
    async with database.session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(GrowthMemorySpeedORM))
    assert count == 1
    assert (await restarted.load("k")).observations == 101
