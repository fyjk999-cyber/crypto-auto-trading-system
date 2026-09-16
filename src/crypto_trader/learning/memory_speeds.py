"""Growth V2 memory speeds (Phase 5).

Three speeds with a strict learning discipline:

    FAST_EXPERIENCE      one episode is enough; may enter LLM context immediately
    PATTERN              repeated, cost-adjusted evidence across occurrences
    VALIDATED_KNOWLEDGE  many independent episodes, multiple regimes, stable edge

Core rules never change from Growth: fast experience can never modify Risk hard
rules, execution safety, model formulas or order authority. ``can_modify_core``
is always False and a contradicting observation demotes a record.

Learning/observability only — never an order authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

PATTERN_MIN_OBSERVATIONS = 5
PATTERN_MIN_EXPECTANCY_BPS = 2.0
VALIDATED_MIN_OBSERVATIONS = 100
VALIDATED_MIN_REGIMES = 3
VALIDATED_MIN_POST_COST_BPS = 0.0
POLICY_VERSION = "memory-policy-v2"
SAMPLE_TIERS = (
    ("PROVISIONAL", 0),
    ("EMERGING", 20),
    ("CANDIDATE", 50),
    ("FORMAL_VALIDATION_ELIGIBLE", 100),
)


class MemorySpeed(StrEnum):
    FAST_EXPERIENCE = "FAST_EXPERIENCE"
    PATTERN = "PATTERN"
    VALIDATED_KNOWLEDGE = "VALIDATED_KNOWLEDGE"


@dataclass
class MemoryRecord:
    key: str
    signature: str
    speed: str = MemorySpeed.FAST_EXPERIENCE.value
    observations: int = 0
    wins: int = 0
    net_bps_total: float = 0.0
    regimes: list[str] = field(default_factory=list)
    demotions: int = 0
    post_cost_expectancy_bps: float | None = None
    chronological_stable: bool = True
    unresolved_contradictions: int = 0
    authority: str = "LEARNING_ONLY"
    is_order: bool = False
    can_modify_core: bool = False

    @property
    def expectancy_bps(self) -> float:
        return self.net_bps_total / self.observations if self.observations else 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.observations if self.observations else 0.0


def sample_tier(observations: int) -> str:
    tier = "PROVISIONAL"
    for name, minimum in SAMPLE_TIERS:
        if observations >= minimum:
            tier = name
    return tier


def effective_post_cost_bps(record: MemoryRecord) -> float:
    if record.post_cost_expectancy_bps is None:
        return record.expectancy_bps
    return record.post_cost_expectancy_bps


def classify_speed(record: MemoryRecord) -> str:
    """Derive the highest justified speed from the factual record."""
    post_cost = effective_post_cost_bps(record)
    if (
        record.observations >= VALIDATED_MIN_OBSERVATIONS
        and len(set(record.regimes)) >= VALIDATED_MIN_REGIMES
        and post_cost > VALIDATED_MIN_POST_COST_BPS
        and record.chronological_stable
        and record.unresolved_contradictions == 0
    ):
        return MemorySpeed.VALIDATED_KNOWLEDGE.value
    if record.observations >= PATTERN_MIN_OBSERVATIONS and post_cost > PATTERN_MIN_EXPECTANCY_BPS:
        return MemorySpeed.PATTERN.value
    return MemorySpeed.FAST_EXPERIENCE.value


def apply_observation(
    record: MemoryRecord,
    *,
    net_bps: float,
    regime: str,
    win: bool,
    post_cost_bps: float | None = None,
    chronological_stable: bool | None = None,
    contradiction: bool = False,
) -> MemoryRecord:
    """Update one record with a factual observation and re-derive its speed."""
    record.observations += 1
    record.net_bps_total += float(net_bps)
    if win:
        record.wins += 1
    if regime and regime not in record.regimes:
        record.regimes.append(regime)
    if post_cost_bps is not None:
        previous = record.post_cost_expectancy_bps or 0.0
        count = max(1, record.observations)
        record.post_cost_expectancy_bps = (previous * (count - 1) + float(post_cost_bps)) / count
    if chronological_stable is not None:
        record.chronological_stable = bool(chronological_stable)
    if contradiction:
        record.unresolved_contradictions += 1

    target = classify_speed(record)
    rank = {
        MemorySpeed.FAST_EXPERIENCE.value: 0,
        MemorySpeed.PATTERN.value: 1,
        MemorySpeed.VALIDATED_KNOWLEDGE.value: 2,
    }
    if (net_bps < 0 or contradiction) and rank.get(record.speed, 0) > 0:
        # A contradicting outcome demotes instead of silently keeping status.
        record.demotions += 1
        record.speed = (
            MemorySpeed.PATTERN.value
            if record.speed == MemorySpeed.VALIDATED_KNOWLEDGE.value
            else MemorySpeed.FAST_EXPERIENCE.value
        )
    elif rank.get(target, 0) > rank.get(record.speed, 0):
        record.speed = target
    # Growth can never change core law, regardless of tier.
    record.can_modify_core = False
    return record


def promotion_summary(record: MemoryRecord) -> dict:
    return {
        "key": record.key,
        "signature": record.signature,
        "speed": record.speed,
        "observations": record.observations,
        "win_rate": round(record.win_rate, 6),
        "expectancy_bps": round(record.expectancy_bps, 6),
        "regimes": list(record.regimes),
        "demotions": record.demotions,
        "sample_tier": sample_tier(record.observations),
        "post_cost_expectancy_bps": round(effective_post_cost_bps(record), 6),
        "chronological_stable": record.chronological_stable,
        "unresolved_contradictions": record.unresolved_contradictions,
        "policy_version": POLICY_VERSION,
        "authority": "LEARNING_ONLY",
        "is_order": False,
        "can_modify_core": False,
    }
