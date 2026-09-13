"""Scale-in (ADD) policy: staged rollout, DEFAULT DISABLED, ceiling-bounded.

MASTER DIRECTIVE §76-§140 — FUTURE LLM AUTOMATIC SCALE-IN.

This module designs the ADD capability without enabling it:

* ``ScaleInPolicy.enabled`` defaults to ``False`` (§137).
* Even when ``enabled`` is True, this build creates NO order: ADD execution is
  not wired into the runtime at all (§136, §138). The value of this phase is the
  contract, the campaign risk model, the data lineage and the sizer interface.
* Every limit is a ONE-WAY ratchet toward safety, exactly like
  :class:`crypto_trader.sizing.policy.PositionSizingPolicy`: configuration can
  tighten but never widen the project hard ceilings.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from decimal import Decimal

from crypto_trader.domain.money import D

#: §137 — the feature flag. MUST default to False.
ENABLE_LLM_AUTOMATIC_SCALE_IN = False

#: §136/§138 — no runtime path in this build reads the flag as permission to
#: create an ADD order. Flipping this requires a separate acceptance mission.
SCALE_IN_EXECUTION_WIRED_IN_RUNTIME = False

#: Project hard ceilings for ADD. Configuration may only tighten these.
HARD_MAX_SCALE_IN_COUNT = 3
HARD_MIN_SCALE_IN_INTERVAL_SECONDS = 60.0
HARD_MIN_SCALE_IN_ORDER_TTL_SECONDS = 5.0
HARD_MAX_INITIAL_ENTRY_RISK_SHARE = Decimal("1")

CONFIG_CLAMPED_PREFIX = "CONFIG_CLAMPED:"

#: §103 — drawdown multiplier bands, ``(upper_bound, multiplier)`` ascending.
#: A drawdown at or above the last bound DISABLES adding entirely.
DRAWDOWN_BANDS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("0.02"), Decimal("1.00")),
    (Decimal("0.05"), Decimal("0.75")),
    (Decimal("0.08"), Decimal("0.50")),
    (Decimal("0.10"), Decimal("0.25")),
)
DRAWDOWN_DISABLED_AT = Decimal("0.10")
DRAWDOWN_MULTIPLIER_MIN = Decimal("0.25")
DRAWDOWN_MULTIPLIER_MAX = Decimal("1.00")


@dataclass(frozen=True)
class ScaleInPolicy:
    """Deterministic ADD policy. All ADD numbers live here, not inline."""

    #: §137 feature flag. Default FALSE and never widened by config parsing.
    enabled: bool = ENABLE_LLM_AUTOMATIC_SCALE_IN

    #: §91 — hard cap on ADD layers. Initial entry + #1 + #2 by default.
    max_scale_in_count: int = 2

    #: §92 — minimum interval between ADDs.
    min_scale_in_interval_seconds: float = 300.0

    #: §112 — ADD orders carry a finite lifetime like short-term entries.
    scale_in_order_ttl_seconds: float = 60.0

    #: §79 — blind averaging down is OFF unless explicitly authorised.
    average_down_enabled: bool = False

    #: §87/§88 — campaign risk split. The initial entry must NOT consume the
    #: whole campaign budget, otherwise no safe room for an ADD remains.
    initial_entry_risk_share: Decimal = Decimal("0.50")
    scale_in_risk_share: Decimal = Decimal("0.50")

    #: §97/§98 — deterministic minimum stop distance. Prevents using an
    #: absurdly tight stop to buy a 500% notional position.
    min_stop_distance_fraction: Decimal = Decimal("0.001")
    min_stop_distance_volatility_multiple: Decimal = Decimal("1.0")

    #: §94 — allowed adverse excursion before an ADD needs structure, expressed
    #: as a fraction of the entry price. Never a pure PnL condition.
    adverse_tolerance_fraction: Decimal = Decimal("0.005")

    reason_codes: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        notes: list[str] = []
        policy = self

        count = policy.max_scale_in_count
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            notes.append(f"{CONFIG_CLAMPED_PREFIX}max_scale_in_count")
            count = 0
        elif count > HARD_MAX_SCALE_IN_COUNT:
            notes.append(f"{CONFIG_CLAMPED_PREFIX}max_scale_in_count")
            count = HARD_MAX_SCALE_IN_COUNT
        object.__setattr__(policy, "max_scale_in_count", count)

        interval = _positive_float(policy.min_scale_in_interval_seconds)
        if interval is None or interval < HARD_MIN_SCALE_IN_INTERVAL_SECONDS:
            notes.append(f"{CONFIG_CLAMPED_PREFIX}min_scale_in_interval_seconds")
            interval = HARD_MIN_SCALE_IN_INTERVAL_SECONDS
        object.__setattr__(policy, "min_scale_in_interval_seconds", interval)

        ttl = _positive_float(policy.scale_in_order_ttl_seconds)
        if ttl is None or ttl < HARD_MIN_SCALE_IN_ORDER_TTL_SECONDS:
            notes.append(f"{CONFIG_CLAMPED_PREFIX}scale_in_order_ttl_seconds")
            ttl = HARD_MIN_SCALE_IN_ORDER_TTL_SECONDS
        object.__setattr__(policy, "scale_in_order_ttl_seconds", ttl)

        initial = _share(policy.initial_entry_risk_share, notes, "initial_entry_risk_share")
        scale_in = _share(policy.scale_in_risk_share, notes, "scale_in_risk_share")
        if initial + scale_in > Decimal("1"):
            # §88 — the planned stop-loss total may never exceed one campaign
            # budget. Shrinking is the only safe repair.
            notes.append(f"{CONFIG_CLAMPED_PREFIX}campaign_risk_split")
            scale_in = max(Decimal("0"), Decimal("1") - initial)
        object.__setattr__(policy, "initial_entry_risk_share", initial)
        object.__setattr__(policy, "scale_in_risk_share", scale_in)

        stop_fraction = _share(
            policy.min_stop_distance_fraction, notes, "min_stop_distance_fraction"
        )
        object.__setattr__(policy, "min_stop_distance_fraction", stop_fraction)
        vol_multiple = _share(
            policy.min_stop_distance_volatility_multiple,
            notes,
            "min_stop_distance_volatility_multiple",
        )
        object.__setattr__(policy, "min_stop_distance_volatility_multiple", vol_multiple)
        tolerance = _share(
            policy.adverse_tolerance_fraction, notes, "adverse_tolerance_fraction"
        )
        object.__setattr__(policy, "adverse_tolerance_fraction", tolerance)

        if not isinstance(policy.enabled, bool):
            notes.append(f"{CONFIG_CLAMPED_PREFIX}enabled")
            object.__setattr__(policy, "enabled", ENABLE_LLM_AUTOMATIC_SCALE_IN)
        if not isinstance(policy.average_down_enabled, bool):
            notes.append(f"{CONFIG_CLAMPED_PREFIX}average_down_enabled")
            object.__setattr__(policy, "average_down_enabled", False)

        if notes:
            object.__setattr__(
                policy, "reason_codes", tuple(dict.fromkeys((*policy.reason_codes, *notes)))
            )

    # --------------------------------------------------------------- derived
    @property
    def hard_ceiling_violations(self) -> tuple[str, ...]:
        return tuple(
            code for code in self.reason_codes if code.startswith(CONFIG_CLAMPED_PREFIX)
        )

    @property
    def execution_enabled(self) -> bool:
        """Whether this BUILD may create an ADD order.

        Always ``False`` in this round: the flag alone is not sufficient, the
        runtime wiring is deliberately absent (§136, §138).
        """
        return bool(self.enabled) and SCALE_IN_EXECUTION_WIRED_IN_RUNTIME

    def campaign_risk_budget(self, equity: Decimal, max_risk_per_trade: Decimal) -> Decimal:
        """Total planned stop-loss risk allowed across a whole campaign (§88)."""
        return D(equity) * D(max_risk_per_trade)

    def scale_in_risk_budget(self, equity: Decimal, max_risk_per_trade: Decimal) -> Decimal:
        """The share of the campaign budget reserved for ADDs (§87)."""
        return self.campaign_risk_budget(equity, max_risk_per_trade) * (
            self.scale_in_risk_share
        )

    def minimum_stop_distance(
        self, *, price: Decimal, volatility: Decimal | None
    ) -> Decimal:
        """Deterministic floor for the stop distance (§97/§98).

        ``EffectiveStopDistance = max(LLM stop distance, MinimumValidStopDistance)``
        so a tight stop can never manufacture an oversized position.
        """
        price_value = D(price)
        if price_value <= 0:
            return Decimal("0")
        floor = price_value * self.min_stop_distance_fraction
        if volatility is not None:
            volatility_value = _non_negative(volatility)
            floor = max(
                floor,
                price_value * volatility_value * self.min_stop_distance_volatility_multiple,
            )
        return floor

    def drawdown_multiplier(self, drawdown_ratio: Decimal | None) -> Decimal:
        """§103 — ADD shrinks as drawdown grows, and stops past the hard band."""
        if drawdown_ratio is None:
            # UNKNOWN drawdown is NOT zero drawdown: §83 requires a fresh
            # proven risk fact before adding, so no credit is given at all.
            return Decimal("0")
        ratio = abs(_non_negative(drawdown_ratio))
        if ratio >= DRAWDOWN_DISABLED_AT:
            return Decimal("0")
        for upper, multiplier in DRAWDOWN_BANDS:
            if ratio < upper:
                return multiplier
        return Decimal("0")

    def to_evidence(self) -> dict:
        return {
            "enabled": self.enabled,
            "execution_enabled": self.execution_enabled,
            "average_down_enabled": self.average_down_enabled,
            "max_scale_in_count": self.max_scale_in_count,
            "min_scale_in_interval_seconds": self.min_scale_in_interval_seconds,
            "scale_in_order_ttl_seconds": self.scale_in_order_ttl_seconds,
            "initial_entry_risk_share": str(self.initial_entry_risk_share),
            "scale_in_risk_share": str(self.scale_in_risk_share),
            "min_stop_distance_fraction": str(self.min_stop_distance_fraction),
            "min_stop_distance_volatility_multiple": str(
                self.min_stop_distance_volatility_multiple
            ),
            "adverse_tolerance_fraction": str(self.adverse_tolerance_fraction),
            "hard_max_scale_in_count": HARD_MAX_SCALE_IN_COUNT,
            "hard_min_scale_in_interval_seconds": HARD_MIN_SCALE_IN_INTERVAL_SECONDS,
            "drawdown_disabled_at": str(DRAWDOWN_DISABLED_AT),
            "execution_wired_in_runtime": SCALE_IN_EXECUTION_WIRED_IN_RUNTIME,
            "hard_ceiling_violations": list(self.hard_ceiling_violations),
            "reason_codes": list(self.reason_codes),
        }

    def replace(self, **changes) -> ScaleInPolicy:
        return dataclasses.replace(self, **changes)


def _non_negative(value) -> Decimal:
    try:
        parsed = D(value)
    except Exception:  # noqa: BLE001 - an unparseable number is not a fact
        return Decimal("0")
    if not parsed.is_finite() or parsed < 0:
        return Decimal("0")
    return parsed


def _share(value, notes: list[str], name: str) -> Decimal:
    parsed = _non_negative(value)
    if parsed > Decimal("1"):
        notes.append(f"{CONFIG_CLAMPED_PREFIX}{name}")
        parsed = Decimal("1")
    return parsed


def _positive_float(value) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")) or parsed <= 0:
        return None
    return parsed
