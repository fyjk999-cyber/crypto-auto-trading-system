"""Position Sizing V2 policy: capital-aware sizing with hard ceilings.

Authority model (POSITION SIZING V2):

    ChiefTrader  decides WHETHER to take risk (direction / thesis / stop).
    Sizer        decides HOW MUCH risk is appropriate (deterministic).
    RiskEngine   decides whether that size is LEGALLY SAFE.
    Execution    decides how much the factual market can actually fill.

``500%`` of equity is a HARD CEILING.  It is never a target, never a default,
and never derived from an LLM quantity.  ``5x`` leverage is CAPACITY, not a
command to use 5x.

Every parameter lives here (never scattered as a hardcode) and every one of
them is clamped against a project-level hard ceiling, so a misconfigured
deployment cannot widen the safety envelope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from crypto_trader.domain.money import D

#: Absolute project hard ceilings.  These are NOT configurable.  Changing them
#: requires a separate, explicit engineering mission.
HARD_MAX_LEVERAGE = Decimal("5")
HARD_MAX_NOTIONAL_MULTIPLE = Decimal("5")
HARD_MAX_RISK_PER_TRADE = Decimal("0.010")
HARD_MAX_LIQUIDITY_PARTICIPATION = Decimal("1")

#: Reason code recorded when a configured value had to be clamped to a hard
#: ceiling (the clamp is loud, never silent).
CONFIG_CLAMPED_PREFIX = "CONFIG_CLAMPED:"

#: Reason code recorded when a configuration choice REDUCES a non-ceiling
#: protection (for example disabling the economic viability gate). Not a clamp,
#: but never silent either.
CONFIG_NOTE_PREFIX = "CONFIG_NOTE:"


@dataclass(frozen=True)
class PositionSizingPolicy:
    """Deterministic, fully-parameterised sizing policy.

    ``__post_init__`` normalises every field against the project hard ceilings.
    A value that would widen the safety envelope is clamped and the clamp is
    recorded in :attr:`reason_codes`, so the effective policy is always
    auditable and always safe.
    """

    # Risk budget (§7, §8)
    base_risk_per_trade: Decimal = Decimal("0.005")
    max_risk_per_trade: Decimal = Decimal("0.010")
    #: Lower clamp bound for the effective risk fraction.  ``0`` by default:
    #: the clamp must never RAISE risk above ``base x conviction`` — a small
    #: position is rejected by the economic gate, never forced larger.
    min_risk_per_trade: Decimal = Decimal("0")

    # Exposure ceilings, expressed as equity multiples (§12, §13, §14, §15)
    max_single_notional_multiple: Decimal = Decimal("5.0")
    max_total_gross_exposure_multiple: Decimal = Decimal("5.0")
    max_symbol_exposure_multiple: Decimal = Decimal("5.0")
    max_leverage: Decimal = Decimal("5.0")

    # Economic viability gate (§23, §24)
    min_effective_notional_fraction: Decimal = Decimal("0.005")

    # Factual market liquidity (§19, §20, §21)
    liquidity_depth_levels: int = 5
    max_liquidity_participation: Decimal = Decimal("0.15")

    #: Optional pre-existing static order-notional ceiling (RiskConfig).  Kept
    #: as an ADDITIONAL cap only; it never represents the 5x rule (§12).
    static_max_order_notional: Decimal | None = None

    #: Populated by clamping/normalisation.  Never set by callers.
    reason_codes: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        """Normalise every field against the project hard ceilings.

        Clamping is a ONE-WAY RATCHET TOWARD SAFETY, exactly like
        ``RiskConfig``: a value above a hard ceiling is pulled down to the
        ceiling, while a non-positive value is left restrictive and is never
        raised. A non-finite/unparseable value falls back to the documented
        default and records the adjustment. Every adjustment is recorded in
        :attr:`reason_codes`, so a clamp is always loud and never silent.
        """
        notes: list[str] = []

        def _decimal(
            name: str,
            value: Decimal,
            *,
            ceiling: Decimal | None = None,
            floor: Decimal | None = None,
            default: Decimal | None = None,
        ) -> Decimal:
            parsed = _finite_or_none(value)
            if parsed is None:
                notes.append(f"{CONFIG_CLAMPED_PREFIX}{name}")
                return default if default is not None else Decimal("0")
            if ceiling is not None and parsed > ceiling:
                notes.append(f"{CONFIG_CLAMPED_PREFIX}{name}")
                parsed = ceiling
            if floor is not None and parsed < floor:
                notes.append(f"{CONFIG_CLAMPED_PREFIX}{name}")
                parsed = floor
            return parsed

        max_risk = _decimal(
            "max_risk_per_trade",
            self.max_risk_per_trade,
            ceiling=HARD_MAX_RISK_PER_TRADE,
            floor=Decimal("0"),
            default=HARD_MAX_RISK_PER_TRADE,
        )
        base_risk = _decimal(
            "base_risk_per_trade",
            self.base_risk_per_trade,
            ceiling=max_risk,
            floor=Decimal("0"),
            default=Decimal("0"),
        )
        min_risk = _decimal(
            "min_risk_per_trade",
            self.min_risk_per_trade,
            ceiling=max_risk,
            floor=Decimal("0"),
        )
        object.__setattr__(self, "max_risk_per_trade", max_risk)
        object.__setattr__(self, "base_risk_per_trade", base_risk)
        object.__setattr__(self, "min_risk_per_trade", min_risk)

        for name in (
            "max_single_notional_multiple",
            "max_total_gross_exposure_multiple",
            "max_symbol_exposure_multiple",
        ):
            object.__setattr__(
                self,
                name,
                _decimal(
                    name,
                    getattr(self, name),
                    ceiling=HARD_MAX_NOTIONAL_MULTIPLE,
                    floor=Decimal("0"),
                    default=HARD_MAX_NOTIONAL_MULTIPLE,
                ),
            )
        object.__setattr__(
            self,
            "max_leverage",
            _decimal(
                "max_leverage",
                self.max_leverage,
                ceiling=HARD_MAX_LEVERAGE,
                floor=Decimal("0"),
                default=HARD_MAX_LEVERAGE,
            ),
        )
        object.__setattr__(
            self,
            "min_effective_notional_fraction",
            _decimal(
                "min_effective_notional_fraction",
                self.min_effective_notional_fraction,
                ceiling=Decimal("1"),
                floor=Decimal("0"),
                default=Decimal("0"),
            ),
        )
        if self.min_effective_notional_fraction <= 0:
            # §24's gate is configurable, but disabling it is a real reduction in
            # protection. Record it loudly instead of letting it vanish.
            notes.append(f"{CONFIG_NOTE_PREFIX}min_effective_notional_fraction_disabled")
        object.__setattr__(
            self,
            "max_liquidity_participation",
            _decimal(
                "max_liquidity_participation",
                self.max_liquidity_participation,
                ceiling=HARD_MAX_LIQUIDITY_PARTICIPATION,
                floor=Decimal("0"),
                default=Decimal("0"),
            ),
        )
        levels = self.liquidity_depth_levels
        if not isinstance(levels, int) or isinstance(levels, bool) or levels < 1:
            notes.append(f"{CONFIG_CLAMPED_PREFIX}liquidity_depth_levels")
            levels = 1
        object.__setattr__(self, "liquidity_depth_levels", levels)

        static_cap = self.static_max_order_notional
        if static_cap is not None:
            parsed_cap = _finite_or_none(static_cap)
            if parsed_cap is None or parsed_cap <= 0:
                # Same one-way ratchet as every other limit: an unusable static
                # cap is kept STRICT (no order may exceed it), never dropped.
                notes.append(f"{CONFIG_CLAMPED_PREFIX}static_max_order_notional")
                parsed_cap = Decimal("0")
            object.__setattr__(self, "static_max_order_notional", parsed_cap)

        if notes:
            object.__setattr__(
                self, "reason_codes", tuple(dict.fromkeys((*self.reason_codes, *notes)))
            )

    # ------------------------------------------------------------ derived facts
    @property
    def hard_ceiling_violations(self) -> tuple[str, ...]:
        """Configured values that had to be clamped (never silent)."""
        return tuple(code for code in self.reason_codes if code.startswith(CONFIG_CLAMPED_PREFIX))

    def notional_ceiling(self, equity: Decimal) -> Decimal:
        """Absolute maximum single-position notional for this equity (§12)."""
        return D(equity) * self.max_single_notional_multiple

    def gross_ceiling(self, equity: Decimal) -> Decimal:
        """Absolute maximum total gross exposure for this equity (§13)."""
        return D(equity) * self.max_total_gross_exposure_multiple

    def symbol_ceiling(self, equity: Decimal) -> Decimal:
        """Absolute maximum gross exposure in one symbol for this equity (§14)."""
        return D(equity) * self.max_symbol_exposure_multiple

    def min_effective_notional(self, equity: Decimal) -> Decimal:
        """Smallest economically meaningful position notional (§23)."""
        return D(equity) * self.min_effective_notional_fraction

    def to_evidence(self) -> dict:
        return {
            "base_risk_per_trade": str(self.base_risk_per_trade),
            "max_risk_per_trade": str(self.max_risk_per_trade),
            "min_risk_per_trade": str(self.min_risk_per_trade),
            "max_single_notional_multiple": str(self.max_single_notional_multiple),
            "max_total_gross_exposure_multiple": str(
                self.max_total_gross_exposure_multiple
            ),
            "max_symbol_exposure_multiple": str(self.max_symbol_exposure_multiple),
            "max_leverage": str(self.max_leverage),
            "min_effective_notional_fraction": str(self.min_effective_notional_fraction),
            "liquidity_depth_levels": self.liquidity_depth_levels,
            "max_liquidity_participation": str(self.max_liquidity_participation),
            "static_max_order_notional": (
                str(self.static_max_order_notional)
                if self.static_max_order_notional is not None
                else None
            ),
            "hard_max_leverage": str(HARD_MAX_LEVERAGE),
            "hard_max_notional_multiple": str(HARD_MAX_NOTIONAL_MULTIPLE),
            "hard_max_risk_per_trade": str(HARD_MAX_RISK_PER_TRADE),
            "hard_ceiling_violations": list(self.hard_ceiling_violations),
            "reason_codes": list(self.reason_codes),
        }


def _finite_or_none(value) -> Decimal | None:
    try:
        parsed = D(value)
    except Exception:  # noqa: BLE001 - any unparseable config value is invalid
        return None
    if not parsed.is_finite():
        return None
    return parsed
