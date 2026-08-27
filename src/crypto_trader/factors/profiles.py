"""Canonical factor profiles and deterministic readiness assessment.

Policy is enforced by code, never by an LLM:
- every required factor usable                  -> READY
- any required factor unusable (or absent)      -> BLOCKED
- required usable but an optional unusable      -> DEGRADED

This module ends at the factor/profile assessment boundary. BLOCKED must not
be wired into order execution from here; consumers decide their own policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from crypto_trader.factors.capture import EXPECTED_FACTOR_IDS
from crypto_trader.factors.health.states import USABLE_STATES, FactorHealthState

if TYPE_CHECKING:
    from crypto_trader.factors.version import FactorSnapshotContract

READY = "READY"
DEGRADED = "DEGRADED"
BLOCKED = "BLOCKED"

READINESS_LEVELS: tuple[str, ...] = (READY, DEGRADED, BLOCKED)

UNUSABLE_STATES: tuple[str, ...] = (
    FactorHealthState.MISSING_DATA,
    FactorHealthState.INSUFFICIENT_HISTORY,
    FactorHealthState.STALE_INPUT,
    FactorHealthState.CALCULATION_FAILED,
    FactorHealthState.DISABLED,
)


@dataclass(frozen=True)
class FactorProfile:
    name: str
    required_factors: tuple[str, ...]
    optional_factors: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_factors", tuple(self.required_factors))
        object.__setattr__(self, "optional_factors", tuple(self.optional_factors))
        overlap = set(self.required_factors) & set(self.optional_factors)
        if overlap:
            raise ValueError(f"profile {self.name!r}: required/optional overlap: {sorted(overlap)}")
        if len(set(self.required_factors)) != len(self.required_factors):
            raise ValueError(f"profile {self.name!r}: duplicate required factors")
        if len(set(self.optional_factors)) != len(self.optional_factors):
            raise ValueError(f"profile {self.name!r}: duplicate optional factors")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "required_factors": list(self.required_factors),
            "optional_factors": list(self.optional_factors),
        }


CANONICAL_PROFILE_NAMES: tuple[str, ...] = (
    "TREND",
    "MOMENTUM",
    "MEAN_REVERSION",
    "DERIVATIVES",
    "MICROSTRUCTURE",
    "FULL",
)

_CANONICAL = {
    profile.name: profile
    for profile in (
        FactorProfile(
            name="TREND",
            required_factors=("trend", "momentum"),
            optional_factors=("breakout", "mean_reversion"),
        ),
        FactorProfile(
            name="MOMENTUM",
            required_factors=("return", "momentum"),
            optional_factors=("volume_change", "volume_anomaly"),
        ),
        FactorProfile(
            name="MEAN_REVERSION",
            required_factors=("mean_reversion",),
            optional_factors=("realized_volatility", "volatility_regime"),
        ),
        FactorProfile(
            name="DERIVATIVES",
            required_factors=("funding_rate", "open_interest"),
            optional_factors=("funding_change", "oi_divergence", "liquidation_pressure"),
        ),
        FactorProfile(
            name="MICROSTRUCTURE",
            required_factors=(
                "orderbook_imbalance",
                "buy_sell_imbalance",
                "cvd",
                "aggressive_trading_ratio",
            ),
            optional_factors=("volume_divergence", "volume_anomaly"),
        ),
    )
}

# FULL is the union behavior: every canonical profile's required factors are
# required together; the union of canonically-optional factors plus every other
# computed factor remain optional.
_required_union = tuple(
    dict.fromkeys(
        factor for profile in _CANONICAL.values() for factor in profile.required_factors
    )
)
required_set = set(_required_union)
# A factor optional in one profile but required in another (e.g. mean_reversion)
# is required in FULL, so it must not also appear in FULL's optional set.
_canonical_optional_union = tuple(
    dict.fromkeys(
        factor
        for profile in _CANONICAL.values()
        for factor in profile.optional_factors
        if factor not in required_set
    )
)
FULL_REQUIRED: tuple[str, ...] = _required_union
FULL_OPTIONAL: tuple[str, ...] = _canonical_optional_union + tuple(
    factor
    for factor in EXPECTED_FACTOR_IDS
    if factor not in required_set and factor not in set(_canonical_optional_union)
)
_CANONICAL["FULL"] = FactorProfile(
    name="FULL", required_factors=FULL_REQUIRED, optional_factors=FULL_OPTIONAL
)


def resolve_profile(name: str) -> FactorProfile:
    profile = _CANONICAL.get(name.upper())
    if profile is None:
        raise ValueError(f"unknown canonical factor profile: {name!r}")
    return profile


@dataclass(frozen=True)
class FactorProfileAssessment:
    profile_name: str
    readiness: str  # READY | DEGRADED | BLOCKED
    blocked_by: tuple[str, ...]
    degraded_by: tuple[str, ...]
    missing_statuses: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "profile_name": self.profile_name,
            "readiness": self.readiness,
            "blocked_by": list(self.blocked_by),
            "degraded_by": list(self.degraded_by),
            "missing_statuses": list(self.missing_statuses),
        }


def assess_profile(profile: FactorProfile, statuses: dict[str, str]) -> FactorProfileAssessment:
    """Deterministic readiness assessment from explicit health states.

    A status entry absent from ``statuses`` is treated as INSUFFICIENT_HISTORY
    (unusable), so a profile can never silently pass on factors that were not
    computed or reported. Severity resolution is order-independent: blocked /
    degraded sets are built first, then classified once.
    """
    missing: list[str] = []
    blocked: list[str] = []
    degraded: list[str] = []

    def _state_of(factor_name: str) -> str | None:
        state = statuses.get(factor_name)
        if state is not None and state not in USABLE_STATES and state not in UNUSABLE_STATES:
            return None  # unrecognized status strings are unusable
        return state

    for factor_name in profile.required_factors:
        state = _state_of(factor_name)
        if state is None:
            blocked.append(factor_name)
            if factor_name not in statuses:
                missing.append(factor_name)
        elif state not in USABLE_STATES:
            blocked.append(factor_name)
    for factor_name in profile.optional_factors:
        state = _state_of(factor_name)
        if state is None:
            degraded.append(factor_name)
            if factor_name not in statuses:
                missing.append(factor_name)
        elif state not in USABLE_STATES:
            degraded.append(factor_name)

    readiness = BLOCKED if blocked else (DEGRADED if degraded else READY)
    return FactorProfileAssessment(
        profile_name=profile.name,
        readiness=readiness,
        blocked_by=tuple(blocked),
        degraded_by=tuple(degraded),
        missing_statuses=tuple(missing),
    )


def assess_profile_from_snapshot(snapshot: FactorSnapshotContract, profile_name: str):
    """Assess a canonical profile against a FactorSnapshotContract.

    Snapshot entries carry their own health status; failed factors are mapped
    through the warning records when available.
    """
    statuses = {entry.factor_name: entry.status for entry in snapshot.factors}
    for factor_id in snapshot.failed_factors:
        state = _state_from_warnings(factor_id, snapshot.calculation_warnings)
        statuses.setdefault(factor_id, state)
    return assess_profile(resolve_profile(profile_name), statuses)


def _state_from_warnings(factor_id: str, warnings: tuple[str, ...]) -> str:
    prefix = f"{factor_id}:"
    for record in warnings:
        if record.startswith(prefix):
            state = record[len(prefix):].split(":", 1)[0]
            return state if state in UNUSABLE_STATES else FactorHealthState.CALCULATION_FAILED
    return FactorHealthState.INSUFFICIENT_HISTORY
