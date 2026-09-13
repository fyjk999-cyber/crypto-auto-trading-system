"""POSITION SIZING V2 — capital-aware 5x-max exposure acceptance tests.

Covers the master-directive acceptance matrix: stop-distance math, LLM
quantity independence, account scaling, the 500% hard ceiling, the risk cap,
conviction mapping, factual liquidity, margin/leverage bounds, fail-closed
valuation and liquidity, direction authority, and the IOST diagnostic.

All facts are deterministic test fixtures. Nothing here reads a live runtime,
a production database, or a network provider.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from crypto_trader.domain.enums import ExecutionDecision, OrderSide
from crypto_trader.domain.models import Account, Instrument, Position, SignalIntent
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.risk.engine import RiskConfig, RiskEngine
from crypto_trader.sizing.audit import BINDING_ECONOMIC_MINIMUM
from crypto_trader.sizing.conviction import (
    CONVICTION_MULTIPLIER_FLOOR,
    conviction_multiplier,
    risk_fraction_for_conviction,
)
from crypto_trader.sizing.policy import (
    HARD_MAX_LEVERAGE,
    HARD_MAX_NOTIONAL_MULTIPLE,
    HARD_MAX_RISK_PER_TRADE,
    PositionSizingPolicy,
)
from crypto_trader.sizing.service import CanonicalSize, LiveEntrySizingService
from crypto_trader.valuation.domain import ValuationBatch

EQUITY = Decimal("100000")
ONE_PCT_STOP = Decimal("99")


# --------------------------------------------------------------------- fixtures
def valuation(
    equity: Decimal | str = EQUITY,
    margin: Decimal | str | None = EQUITY,
    quality: str = "HEALTHY",
) -> ValuationBatch:
    healthy = quality == "HEALTHY"
    return ValuationBatch(
        valuation_id="val-sizing-v2",
        account_id="default",
        currency="USDT",
        quality=quality,
        raw_mtm_equity=Decimal(str(equity)) if healthy else None,
        available_margin=(
            None if not healthy or margin is None else Decimal(str(margin))
        ),
    )


def instrument(
    contract_size: str = "1",
    contract_multiplier: str = "1",
    lot: str = "0.001",
    symbol: str = "BTCUSDT",
) -> Instrument:
    return Instrument(
        symbol=symbol,
        base_asset=symbol.split("USDT")[0] or "BTC",
        quote_asset="USDT",
        instrument_type="LINEAR_PERP",
        contract_size=contract_size,
        contract_multiplier=contract_multiplier,
        step_size=lot,
    )


def size(**overrides) -> CanonicalSize:
    """Size one LONG entry with generous facts; override only what matters."""
    values: dict = {
        "side": "LONG",
        # The LLM's advisory size. It must never cap the result (§6, §42).
        "requested_quantity": Decimal("4366"),
        "requested_leverage": Decimal("5"),
        "account": Account(equity=EQUITY),
        "positions": {},
        "instrument": instrument(),
        "price": Decimal("100"),
        "stop_price": ONE_PCT_STOP,
        "liquidity_depth_qty": Decimal("1000000"),
        "conviction": Decimal("0.80"),
        "valuation": valuation(),
    }
    values.update(overrides)
    return LiveEntrySizingService().size(**values)


# ======================================================= §41 / §70 stop distance
@pytest.mark.parametrize(
    ("stop_price", "expected_notional"),
    [
        (Decimal("99"), Decimal("50000")),  # Case A — 1% stop -> 50% equity
        (Decimal("99.5"), Decimal("100000")),  # Case B — 0.5% stop -> 100%
        (Decimal("99.8"), Decimal("250000")),  # Case C — 0.2% stop -> 250%
        (Decimal("99.9"), Decimal("500000")),  # Case D — 0.1% stop -> 500%
    ],
)
def test_stop_distance_determines_notional_as_pct_of_equity(stop_price, expected_notional):
    result = size(stop_price=stop_price)

    assert result.rejected is False
    assert result.risk_normalized_notional == expected_notional
    # Only lot-size rounding may perturb the exact target.
    step_notional = Decimal("0.001") * Decimal("100")
    assert abs(result.risk_normalized_notional - expected_notional) <= step_notional
    assert result.audit.risk_budget == Decimal("500")
    assert result.audit.stop_distance == Decimal("100") - stop_price


def test_case_e_a_stop_below_the_minimum_is_rejected_not_capped():
    """Case E — SUPERSEDED by the entry minimum-stop-distance guard (§10, §13).

    Previously a 0.05% stop inflated risk_qty to 1,000,000 and the 500% ceiling
    bound the result. Capping still handed the LLM the MAXIMUM permitted size
    for an INVALID stop, which is exactly the manipulation the guard closes: a
    tighter stop shrinks the risk unit, so the risk budget alone cannot defend
    against it. A 0.05% stop is now below the 0.1% deterministic minimum and the
    entry is REJECTED outright - it never reaches the ceiling.
    """
    result = size(stop_price=Decimal("99.95"))

    assert result.rejected is True
    assert result.risk_normalized_notional == Decimal("0")
    assert result.sizing_reason_codes[-1] == "STOP_DISTANCE_BELOW_MINIMUM"
    assert result.audit.stop_distance == Decimal("0.05")
    assert result.audit.minimum_stop_distance == Decimal("0.1")
    assert result.audit.stop_distance_source == "LLM_REQUESTED"


def test_large_stop_distance_always_produces_a_smaller_notional():
    notionals = [
        size(stop_price=stop).risk_normalized_notional
        for stop in (Decimal("99"), Decimal("98"), Decimal("95"), Decimal("90"))
    ]
    assert notionals == sorted(notionals, reverse=True)
    assert notionals[0] > notionals[-1]


def test_500_percent_is_a_ceiling_and_never_a_default():
    """The default entry is sized by RISK, not pushed to the ceiling."""
    assert size().risk_normalized_notional == Decimal("50000")
    assert size().binding_cap == "RISK_BUDGET"
    assert PositionSizingPolicy().to_evidence()["base_risk_per_trade"] == "0.005"


# ==================================================== §42 LLM quantity authority
def test_llm_raw_quantity_is_advisory_only_and_never_caps_final_quantity():
    small = size(requested_quantity=Decimal("1"))
    huge = size(requested_quantity=Decimal("1000000"))

    assert small.normalized_quantity == huge.normalized_quantity
    assert huge.normalized_quantity > 0
    # ... and the raw LLM numbers are preserved for analysis (§32).
    assert small.audit.llm_requested_quantity == Decimal("1")
    assert huge.audit.llm_requested_quantity == Decimal("1000000")
    # The deterministic quantity is unrelated to either raw request.
    assert huge.normalized_quantity != huge.audit.llm_requested_quantity
    assert small.normalized_quantity != small.audit.llm_requested_quantity

    # LLM_RAW_QUANTITY_IS_NOT_AUTHORITY = PASS
    assert small.final_quantity == huge.final_quantity


def test_llm_requested_exposure_is_also_advisory_only():
    tiny = size(requested_quantity=Decimal("0"), requested_exposure=Decimal("3"))
    enormous = size(
        requested_quantity=Decimal("0"), requested_exposure=Decimal("10000000")
    )

    assert tiny.normalized_quantity == enormous.normalized_quantity
    assert tiny.audit.llm_requested_exposure == Decimal("3")
    assert enormous.audit.llm_requested_exposure == Decimal("10000000")


# ============================================================ §43 account scaling
def test_sizing_is_capital_aware_across_account_sizes():
    small = size(
        valuation=valuation(equity="10000", margin="10000"),
        account=Account(equity=Decimal("10000")),
        liquidity_depth_qty=Decimal("1000000"),
    )
    large = size(valuation=valuation(equity="100000", margin="100000"))

    assert small.rejected is False and large.rejected is False
    assert large.risk_normalized_notional == small.risk_normalized_notional * 10
    assert small.risk_normalized_notional == Decimal("5000")
    assert large.risk_normalized_notional == Decimal("50000")


# =============================================================== §44 / §45 caps
def test_five_x_ceiling_holds_for_any_stop_and_confidence():
    """Every VALID stop, at every conviction, stays inside the 5x ceiling.

    The stops are >= the deterministic minimum (0.1% of 100). Stops BELOW it are
    rejected before cap math and are covered by the stop-distance guard tests -
    using them here would make this assertion pass vacuously on a zero notional.
    """
    for stop in (Decimal("99.9"), Decimal("99.8"), Decimal("99"), Decimal("95")):
        for conviction in (Decimal("0.0"), Decimal("0.80"), Decimal("1.0")):
            result = size(
                stop_price=stop,
                conviction=conviction,
                valuation=valuation(equity=Decimal("100000"), margin=Decimal("1000000")),
                liquidity_depth_qty=Decimal("1000000000"),
            )
            assert result.rejected is False
            assert result.risk_normalized_notional > 0
            assert result.risk_normalized_notional <= EQUITY * HARD_MAX_NOTIONAL_MULTIPLE
    # The tightest valid stop still reaches the ceiling - the ceiling is real.
    tightest = size(
        stop_price=Decimal("99.9"),
        valuation=valuation(equity=Decimal("100000"), margin=Decimal("1000000")),
        liquidity_depth_qty=Decimal("1000000000"),
    )
    assert tightest.risk_normalized_notional == EQUITY * HARD_MAX_NOTIONAL_MULTIPLE


def test_stop_loss_risk_stays_inside_the_effective_risk_budget():
    stops = (Decimal("99"), Decimal("99.5"), Decimal("99.8"), Decimal("99.9"), Decimal("99.85"))
    for stop in stops:
        for conviction in (Decimal("0.0"), Decimal("0.80"), Decimal("1.0")):
            result = size(
                stop_price=stop,
                conviction=conviction,
                valuation=valuation(equity=Decimal("100000"), margin=Decimal("1000000")),
                liquidity_depth_qty=Decimal("1000000000"),
            )
            assert result.rejected is False
            assert result.max_loss_estimate > 0
            assert result.max_loss_estimate <= result.audit.risk_budget
            assert result.audit.risk_budget <= EQUITY * HARD_MAX_RISK_PER_TRADE


# ============================================================= §46 conviction
@pytest.mark.parametrize(
    ("confidence", "multiplier"),
    [
        ("0.00", "0.50"),
        ("0.54", "0.50"),
        ("0.55", "0.65"),
        ("0.64", "0.65"),
        ("0.65", "0.80"),
        ("0.74", "0.80"),
        ("0.75", "1.00"),
        ("0.84", "1.00"),
        ("0.85", "1.20"),
        ("0.91", "1.20"),
        ("0.92", "1.40"),
        ("1.00", "1.40"),
    ],
)
def test_conviction_bands_are_deterministic(confidence, multiplier):
    assert conviction_multiplier(Decimal(confidence)) == Decimal(multiplier)


def test_conviction_never_increases_risk_beyond_one_percent():
    fractions = [
        risk_fraction_for_conviction(
            confidence=Decimal(c),
            base_risk_per_trade=Decimal("0.005"),
            max_risk_per_trade=Decimal("0.010"),
        ).effective_fraction
        for c in ("0.0", "0.55", "0.65", "0.75", "0.85", "0.92", "1.0")
    ]
    assert fractions == sorted(fractions)  # monotone non-decreasing
    assert max(fractions) <= HARD_MAX_RISK_PER_TRADE


def test_lower_conviction_never_produces_a_larger_risk_budget():
    low = size(conviction=Decimal("0.50"))
    high = size(conviction=Decimal("0.95"))

    assert low.audit.risk_budget < high.audit.risk_budget
    assert low.audit.risk_budget == Decimal("250")
    assert high.audit.risk_budget == Decimal("700")
    assert high.audit.effective_risk_fraction <= HARD_MAX_RISK_PER_TRADE


def test_misconfigured_base_risk_above_the_ceiling_is_clamped_not_trusted():
    decision = risk_fraction_for_conviction(
        confidence=Decimal("1.0"),
        base_risk_per_trade=Decimal("0.5"),
        max_risk_per_trade=Decimal("0.5"),
    )
    assert decision.effective_fraction <= HARD_MAX_RISK_PER_TRADE
    assert decision.multiplier == Decimal("1.40")


def test_confidence_is_never_used_as_leverage():
    """A maximum-conviction request must not become 5x by construction."""
    result = size(conviction=Decimal("1.0"), requested_leverage=Decimal("1"))
    assert result.risk_bounded_leverage == Decimal("1")
    assert result.risk_bounded_leverage != HARD_MAX_LEVERAGE


# ============================================================== §47 liquidity
def test_liquidity_caps_quantity_at_participation_of_factual_depth():
    result = size(
        price=Decimal("1"),
        # 0.1% of 1.0 - exactly the deterministic minimum for a price of 1, so
        # the stop guard passes and LIQUIDITY is what binds.
        stop_price=Decimal("0.999"),
        requested_leverage=Decimal("1"),
        liquidity_depth_qty=Decimal("100000"),
        valuation=valuation(equity=Decimal("100000"), margin=Decimal("100000")),
    )

    assert result.rejected is False
    assert result.audit.minimum_stop_distance == Decimal("0.001")
    assert result.audit.risk_qty == Decimal("500000")
    assert result.audit.liquidity_cap_qty == Decimal("15000")
    assert result.normalized_quantity <= Decimal("15000")
    assert "LIQUIDITY" in result.binding_caps
    assert "LIQUIDITY_CAP" in result.sizing_reason_codes


def test_orderbook_depth_aggregates_the_best_factual_levels():
    book = OrderBook(symbol="IOSTUSDT", exchange="OKX")
    book.apply_snapshot(
        1,
        [(Decimal("0.00087"), Decimal("100")), (Decimal("0.00086"), Decimal("200"))],
        [
            (Decimal("0.00088"), Decimal("10")),
            (Decimal("0.00089"), Decimal("20")),
            (Decimal("0.00090"), Decimal("30")),
            (Decimal("0.00091"), Decimal("40")),
            (Decimal("0.00092"), Decimal("50")),
            (Decimal("0.00093"), Decimal("60")),
        ],
    )

    # Best-first on the consumed side: LOWEST asks for a LONG.
    assert book.depth_quantity(side="ASK", levels=3) == Decimal("60")
    assert book.depth_quantity(side="ASK", levels=5) == Decimal("150")
    assert book.depth_quantity(side="ASK", levels=25) == Decimal("210")
    # Highest bids for a SHORT.
    assert book.depth_quantity(side="BID", levels=2) == Decimal("300")


def test_orderbook_depth_is_unknown_when_books_cannot_supply_facts():
    unhealthy = OrderBook(symbol="IOSTUSDT", exchange="OKX")
    unhealthy.apply_snapshot(1, [(Decimal("1"), Decimal("5"))], [(Decimal("2"), Decimal("5"))])
    unhealthy.invalidate()
    assert unhealthy.depth_quantity(side="ASK", levels=5) is None

    empty = OrderBook(symbol="IOSTUSDT", exchange="OKX")
    empty.apply_snapshot(1, [], [])
    assert empty.depth_quantity(side="ASK", levels=5) is None

    zero_depth = OrderBook(symbol="IOSTUSDT", exchange="OKX")
    zero_depth.apply_snapshot(1, [(Decimal("1"), Decimal("1"))], [(Decimal("2"), Decimal("0"))])
    assert zero_depth.depth_quantity(side="BID", levels=5) == Decimal("1")
    assert zero_depth.depth_quantity(side="ASK", levels=5) is None

    book = OrderBook(symbol="IOSTUSDT", exchange="OKX")
    book.apply_snapshot(1, [(Decimal("1"), Decimal("1"))], [(Decimal("2"), Decimal("1"))])
    assert book.depth_quantity(side="ASK", levels=0) is None
    assert book.depth_quantity(side="NOPE", levels=5) is None


def test_liquidity_participation_is_configurable_but_bounded_by_facts():
    policy = PositionSizingPolicy(max_liquidity_participation=Decimal("0.05"))
    result = LiveEntrySizingService(policy=policy).size(
        side="LONG",
        requested_leverage=Decimal("5"),
        account=Account(equity=EQUITY),
        positions={},
        instrument=instrument(),
        price=Decimal("100"),
        stop_price=ONE_PCT_STOP,
        liquidity_depth_qty=Decimal("1000"),
        conviction=Decimal("0.80"),
        valuation=valuation(),
    )
    assert result.audit.liquidity_cap_qty == Decimal("50")


# ======================================================== §48 economic minimum
def test_economically_meaningless_position_is_rejected_never_upsized():
    result = size(
        price=Decimal("1"),
        stop_price=Decimal("0.99"),
        liquidity_depth_qty=Decimal("1400"),
    )

    assert result.rejected is True
    assert result.normalized_quantity == Decimal("0")
    assert result.risk_normalized_notional == Decimal("0")
    assert "BELOW_ECONOMIC_NOTIONAL" in result.sizing_reason_codes
    assert result.binding_cap == BINDING_ECONOMIC_MINIMUM
    # The rejected size is still explainable: it was NOT inflated to 500.
    assert result.audit.final_notional == Decimal("210")
    assert result.audit.min_effective_notional == Decimal("500")
    assert result.audit.final_notional < result.audit.min_effective_notional


def test_position_at_the_economic_minimum_is_accepted():
    result = size(
        price=Decimal("1"),
        stop_price=Decimal("0.99"),
        liquidity_depth_qty=Decimal("3400"),
    )
    assert result.rejected is False
    assert result.risk_normalized_notional == Decimal("510")


# ===================================================== §49 / §50 margin & leverage
def test_margin_cap_uses_approved_leverage_not_max_leverage():
    result = size(
        requested_leverage=Decimal("2"),
        stop_price=Decimal("99.9"),
        valuation=valuation(equity=Decimal("100000"), margin=Decimal("10000")),
    )

    assert result.risk_bounded_leverage == Decimal("2")
    assert result.risk_normalized_notional == Decimal("20000")
    # Never AvailableMargin(10,000) x max_leverage(5) = 50,000.
    assert result.risk_normalized_notional != Decimal("50000")
    assert "MARGIN" in result.binding_caps


def test_requested_leverage_above_the_hard_cap_is_clamped():
    result = size(requested_leverage=Decimal("10"))

    assert result.requested_leverage == Decimal("10")
    assert result.risk_bounded_leverage == HARD_MAX_LEVERAGE
    assert "LEVERAGE_CLAMPED" in result.sizing_reason_codes


def test_volatility_and_illiquidity_clamp_leverage_to_one():
    # A 10% realized volatility also raises the minimum stop distance to 10% of
    # price, so the entry must carry a stop at least that far away.
    volatile = size(volatility=Decimal("0.10"), stop_price=Decimal("90"))
    illiquid = size(liquidity=Decimal("0"))
    assert volatile.rejected is False
    assert volatile.risk_bounded_leverage == Decimal("1")
    assert illiquid.risk_bounded_leverage == Decimal("1")


# ==================================================== §29 / §51 valuation + margin
@pytest.mark.parametrize("quality", ["UNAVAILABLE", "DEGRADED"])
def test_sizing_fails_closed_without_a_proven_valuation(quality):
    result = size(valuation=valuation(quality=quality))

    assert result.rejected is True
    assert result.normalized_quantity == Decimal("0")
    assert "VALUATION_BATCH_UNAVAILABLE" in result.sizing_reason_codes


def test_sizing_fails_closed_when_no_valuation_batch_is_supplied():
    result = size(valuation=None)

    assert result.normalized_quantity == Decimal("0")
    assert "VALUATION_BATCH_REQUIRED" in result.sizing_reason_codes


def test_sizing_never_guesses_an_unknown_available_margin():
    result = size(valuation=valuation(equity=Decimal("100000"), margin=None))

    assert result.normalized_quantity == Decimal("0")
    assert "AVAILABLE_MARGIN_UNKNOWN" in result.sizing_reason_codes


def test_non_positive_available_margin_refuses_new_risk():
    result = size(valuation=valuation(equity=Decimal("100000"), margin="0"))

    assert result.normalized_quantity == Decimal("0")
    assert "INSUFFICIENT_AVAILABLE_MARGIN" in result.sizing_reason_codes


def test_valuation_equity_not_ledger_cash_drives_the_risk_budget():
    """Sizing equity is the proven batch equity, not account.equity (§28)."""
    result = size(
        account=Account(equity=Decimal("999999")),
        valuation=valuation(equity=Decimal("100000"), margin=Decimal("100000")),
    )
    assert result.sizing_equity == Decimal("100000")
    assert result.audit.risk_budget == Decimal("500")


# ========================================================= §52 unknown liquidity
@pytest.mark.parametrize("depth", [None, Decimal("0"), Decimal("-5")])
def test_unknown_or_non_positive_liquidity_is_no_new_risk(depth):
    result = size(liquidity_depth_qty=depth)

    assert result.rejected is True
    assert result.normalized_quantity == Decimal("0")
    assert "LIQUIDITY_UNKNOWN" in result.sizing_reason_codes


# ========================================================= §53 direction authority
def test_sizer_output_cannot_express_a_direction_at_all():
    fields = {f.name for f in dataclasses.fields(CanonicalSize)}
    for forbidden in ("side", "direction", "action", "strategy_selected"):
        assert forbidden not in fields


def test_sizer_is_direction_symmetric_and_never_defaults_a_direction():
    long = size(side="LONG")
    short = size(side="SHORT")

    assert long.normalized_quantity == short.normalized_quantity > 0
    assert long.max_loss_estimate == short.max_loss_estimate
    # An unusable side is refused, never silently defaulted to a direction.
    for invalid in ("SIDEWAYS", "", "NONE", "BUY"):
        rejected = size(side=invalid)
        assert rejected.normalized_quantity == Decimal("0")
        assert "INVALID_SIZING_INPUT" in rejected.sizing_reason_codes


def test_sizer_cannot_create_direction_from_a_flat_portfolio():
    """The sizer only ever emits a quantity — never a tradable direction."""
    result = size(positions={})
    assert isinstance(result, CanonicalSize)
    assert result.normalized_quantity > 0
    assert not hasattr(result, "strategy_selected")
    assert not hasattr(result, "direction")


# ==================================================== §12/§13/§14 portfolio caps
def test_existing_portfolio_gross_exposure_reduces_remaining_capacity():
    position = Position(
        symbol="ETHUSDT",
        base_asset="ETH",
        quote_asset="USDT",
        quantity=Decimal("4000"),
        avg_entry_price=Decimal("100"),
        cost_basis=Decimal("400000"),
    )
    result = size(
        positions={"ETHUSDT": position},
        price=Decimal("100"),
        stop_price=Decimal("99.9"),
        requested_leverage=Decimal("1"),
    )
    # equity x 5 = 500,000; 400,000 already used -> 100,000 of room left.
    assert result.audit.existing_gross_exposure == Decimal("400000")
    assert result.audit.portfolio_cap_qty == Decimal("1000")
    assert result.risk_normalized_notional <= Decimal("100000")


def test_no_new_risk_when_portfolio_gross_capacity_is_exhausted():
    position = Position(
        symbol="ETHUSDT",
        base_asset="ETH",
        quote_asset="USDT",
        quantity=Decimal("6000"),
        avg_entry_price=Decimal("100"),
        cost_basis=Decimal("600000"),
    )
    result = size(positions={"ETHUSDT": position}, requested_leverage=Decimal("1"))

    assert result.normalized_quantity == Decimal("0")
    assert "NO_PORTFOLIO_GROSS_CAPACITY" in result.sizing_reason_codes


def test_contract_size_and_multiplier_are_respected():
    result = size(
        instrument=instrument(contract_size="0.01", contract_multiplier="2"),
        price=Decimal("100"),
        stop_price=Decimal("99"),
    )
    # notional per unit = 100 * 0.01 * 2 = 2; risk 500 / (1 * 0.02) = 25,000 units
    assert result.audit.risk_qty == Decimal("25000")
    assert result.audit.capital_cap_qty == Decimal("250000")
    assert result.risk_normalized_notional == Decimal("50000")


# ============================================================== §59 / §60 config
def test_policy_clamps_every_attempt_to_widen_the_safety_envelope():
    policy = PositionSizingPolicy(
        max_single_notional_multiple=Decimal("20"),
        max_total_gross_exposure_multiple=Decimal("20"),
        max_symbol_exposure_multiple=Decimal("20"),
        max_leverage=Decimal("20"),
        max_risk_per_trade=Decimal("0.5"),
        max_liquidity_participation=Decimal("5"),
        liquidity_depth_levels=0,
    )

    assert policy.max_single_notional_multiple == HARD_MAX_NOTIONAL_MULTIPLE
    assert policy.max_total_gross_exposure_multiple == HARD_MAX_NOTIONAL_MULTIPLE
    assert policy.max_symbol_exposure_multiple == HARD_MAX_NOTIONAL_MULTIPLE
    assert policy.max_leverage == HARD_MAX_LEVERAGE
    assert policy.max_risk_per_trade == HARD_MAX_RISK_PER_TRADE
    assert policy.max_liquidity_participation == Decimal("1")
    assert policy.liquidity_depth_levels == 1
    assert set(policy.hard_ceiling_violations) == {
        "CONFIG_CLAMPED:max_single_notional_multiple",
        "CONFIG_CLAMPED:max_total_gross_exposure_multiple",
        "CONFIG_CLAMPED:max_symbol_exposure_multiple",
        "CONFIG_CLAMPED:max_leverage",
        "CONFIG_CLAMPED:max_risk_per_trade",
        "CONFIG_CLAMPED:max_liquidity_participation",
        "CONFIG_CLAMPED:liquidity_depth_levels",
    }


def test_config_cannot_widen_the_notional_ceiling_through_the_sizer():
    widened = LiveEntrySizingService(
        policy=PositionSizingPolicy(max_single_notional_multiple=Decimal("20"))
    )
    result = widened.size(
        side="LONG",
        requested_quantity=Decimal("1"),
        requested_leverage=Decimal("5"),
        account=Account(equity=EQUITY),
        positions={},
        instrument=instrument(),
        price=Decimal("100"),
        stop_price=Decimal("99.999"),
        liquidity_depth_qty=Decimal("1000000000"),
        conviction=Decimal("1.0"),
        valuation=valuation(equity=Decimal("100000"), margin=Decimal("1000000")),
    )

    assert result.risk_normalized_notional <= EQUITY * HARD_MAX_NOTIONAL_MULTIPLE
    assert result.audit.policy["max_single_notional_multiple"] == "5"


def test_risk_config_clamps_above_project_hard_ceilings():
    config = RiskConfig(
        max_single_notional_multiple=Decimal("20"),
        max_total_gross_exposure_multiple=Decimal("20"),
        max_symbol_exposure_multiple=Decimal("20"),
        max_leverage=Decimal("20"),
        max_risk_per_trade=Decimal("0.9"),
    )

    assert config.max_single_notional_multiple == HARD_MAX_NOTIONAL_MULTIPLE
    assert config.max_leverage == HARD_MAX_LEVERAGE
    assert config.max_risk_per_trade == HARD_MAX_RISK_PER_TRADE
    assert set(config.hard_ceiling_clamps) == {
        "max_single_notional_multiple",
        "max_total_gross_exposure_multiple",
        "max_symbol_exposure_multiple",
        "max_leverage",
        "max_risk_per_trade",
    }


def test_clamping_is_a_one_way_ratchet_toward_safety():
    """A degenerate (zero) limit must stay restrictive, never be raised.

    Raising a configured 0 up to a 5x ceiling would be a silent fail-OPEN.
    """
    config = RiskConfig(
        max_single_notional_multiple=Decimal("0"),
        max_total_gross_exposure_multiple=Decimal("0"),
        max_symbol_exposure_multiple=Decimal("0"),
        max_leverage=Decimal("0"),
        max_risk_per_trade=Decimal("0"),
    )
    assert config.max_single_notional_multiple == Decimal("0")
    assert config.max_total_gross_exposure_multiple == Decimal("0")
    assert config.max_symbol_exposure_multiple == Decimal("0")
    assert config.max_leverage == Decimal("0")
    assert config.max_risk_per_trade == Decimal("0")
    assert set(config.hard_ceiling_clamps) == {
        "max_single_notional_multiple",
        "max_total_gross_exposure_multiple",
        "max_symbol_exposure_multiple",
        "max_leverage",
        "max_risk_per_trade",
    }
    # A zero notional multiple can never approve any new entry.
    decision = RiskEngine(config).check(
        risk_intent(quantity=Decimal("1")),
        account=Account(equity=Decimal("100000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        **PROVEN,
    )
    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "MAX_SINGLE_NOTIONAL_EQUITY_MULTIPLE"

    # A zero leverage ceiling alone blocks every leveraged new entry.
    leverage_only = RiskEngine(RiskConfig(max_leverage=Decimal("0")))
    assert leverage_only.config.max_leverage == Decimal("0")
    blocked = leverage_only.check(
        risk_intent(quantity=Decimal("1")),
        account=Account(equity=Decimal("100000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        **PROVEN,
    )
    assert blocked.decision == ExecutionDecision.REJECT
    assert blocked.reason == "MAX_LEVERAGE"


def test_policy_clamping_never_raises_a_zero_limit():
    policy = PositionSizingPolicy(
        max_single_notional_multiple=Decimal("0"),
        max_leverage=Decimal("0"),
        max_risk_per_trade=Decimal("0"),
    )
    assert policy.max_single_notional_multiple == Decimal("0")
    assert policy.max_leverage == Decimal("0")
    assert policy.max_risk_per_trade == Decimal("0")
    assert "CONFIG_CLAMPED:base_risk_per_trade" in policy.reason_codes

    result = LiveEntrySizingService(policy=policy).size(
        side="LONG",
        requested_quantity=Decimal("1"),
        requested_leverage=Decimal("5"),
        account=Account(equity=EQUITY),
        positions={},
        instrument=instrument(),
        price=Decimal("100"),
        stop_price=ONE_PCT_STOP,
        liquidity_depth_qty=Decimal("1000000"),
        conviction=Decimal("0.80"),
        valuation=valuation(),
    )
    assert result.normalized_quantity == Decimal("0")
    assert result.rejected is True


def test_static_order_notional_remains_an_additional_cap():
    """The static 1,000,000 ceiling still applies, but is not the 5x rule."""
    policy = PositionSizingPolicy(static_max_order_notional=Decimal("30000"))
    result = LiveEntrySizingService(policy=policy).size(
        side="LONG",
        requested_leverage=Decimal("5"),
        account=Account(equity=EQUITY),
        positions={},
        instrument=instrument(),
        price=Decimal("100"),
        stop_price=ONE_PCT_STOP,
        liquidity_depth_qty=Decimal("1000000"),
        conviction=Decimal("0.80"),
        valuation=valuation(),
    )
    assert result.risk_normalized_notional <= Decimal("30000")
    assert (
        "ORDER_NOTIONAL_LIMIT" in result.binding_caps
        or "ORDER_NOTIONAL_LIMIT" in result.sizing_reason_codes
    )


# ================================================= §30 / §31 / §62 audit contract
def test_every_accepted_entry_records_a_complete_explainable_audit():
    result = size()
    evidence = result.audit.to_evidence()

    for key in (
        "equity",
        "valuation_id",
        "entry_price",
        "stop_price",
        "stop_distance",
        "stop_distance_pct",
        "base_risk_fraction",
        "conviction",
        "conviction_multiplier",
        "effective_risk_fraction",
        "risk_budget",
        "requested_quantity_from_llm",
        "requested_exposure_from_llm",
        "risk_qty",
        "capital_cap_qty",
        "margin_cap_qty",
        "portfolio_cap_qty",
        "symbol_cap_qty",
        "liquidity_cap_qty",
        "final_qty",
        "final_notional",
        "requested_leverage",
        "approved_leverage",
        "max_loss_estimate",
        "binding_cap",
        "binding_caps",
        "sizing_reason_codes",
    ):
        assert key in evidence, key
    assert evidence["equity"] == "100000"
    assert evidence["valuation_id"] == "val-sizing-v2"
    assert evidence["final_qty"] == str(result.normalized_quantity)
    assert evidence["binding_cap"] == result.binding_cap
    assert evidence["sizing_reason_codes"] == list(result.sizing_reason_codes)


def test_reason_chain_names_every_cap_layer_not_only_the_last_one():
    result = size(
        requested_leverage=Decimal("10"),
        liquidity_depth_qty=Decimal("1000"),
        stop_price=Decimal("99.9"),
        valuation=valuation(equity=Decimal("100000"), margin=Decimal("10000")),
    )

    codes = set(result.sizing_reason_codes)
    assert "RISK_BUDGET" in codes
    assert "STOP_DISTANCE_RISK_BUDGET" in codes
    assert "LEVERAGE_CLAMPED" in codes
    assert "LIQUIDITY_CAP" in codes
    assert "ECONOMIC_NOTIONAL_PASS" in codes


def test_rejected_entry_still_reports_why():
    result = size(valuation=valuation(quality="UNAVAILABLE"))
    evidence = result.audit.to_evidence()

    assert result.rejected is True
    assert evidence["sizing_reason_codes"]
    assert evidence["equity"] is None
    assert evidence["valuation_quality"] == "UNAVAILABLE"


# ================================================== §57 / §58 IOST diagnostic
def test_iost_like_low_price_asset_is_not_sized_by_its_price():
    """A 0.0008783-priced asset must NOT collapse to a few USDT notional."""
    price = Decimal("0.0008783")
    lot = "0.1"
    result = size(
        instrument=instrument(symbol="IOSTUSDT", lot=lot),
        price=price,
        stop_price=price * Decimal("0.99"),  # a 1% stop
        requested_quantity=Decimal("4366"),
        requested_leverage=Decimal("5"),
        liquidity_depth_qty=Decimal("1000000000"),
        valuation=valuation(equity=Decimal("100000"), margin=Decimal("100000")),
    )

    assert result.rejected is False
    # OLD MODEL would have produced roughly 4366 x 0.0008783 = ~3.83 USDT.
    assert result.audit.llm_requested_exposure < Decimal("4")
    assert result.normalized_quantity != Decimal("4366")
    # NEW MODEL is capital-aware: a 1% stop risks 0.5% of a 100,000 account.
    # Only lot-size rounding (0.1 IOST) may perturb the exact 50,000 target.
    assert abs(result.risk_normalized_notional - Decimal("50000")) <= price * Decimal(lot)
    assert result.max_loss_estimate <= Decimal("500")
    assert result.binding_cap == "RISK_BUDGET"


def test_iost_like_asset_only_stays_small_when_facts_really_forbid_size():
    """If facts only allow a few USDT, refuse — never force a bigger order."""
    price = Decimal("0.0008783")
    result = size(
        instrument=instrument(symbol="IOSTUSDT", lot="0.1"),
        price=price,
        stop_price=price * Decimal("0.99"),
        requested_quantity=Decimal("4366"),
        # A thin factual book: 4366 units of visible depth.
        liquidity_depth_qty=Decimal("4366"),
        valuation=valuation(equity=Decimal("100000"), margin=Decimal("100000")),
    )

    assert result.rejected is True
    assert "BELOW_ECONOMIC_NOTIONAL" in result.sizing_reason_codes
    assert result.audit.final_notional < result.audit.min_effective_notional
    assert result.normalized_quantity == Decimal("0")


# ============================================== §33 / §34 RiskEngine independent
PROVEN = {
    "drawdown": Decimal("0"),
    "current_equity": Decimal("100000"),
    "peak_equity": Decimal("100000"),
    "valuation_id": "val-risk-v2",
    "valuation_quality": "HEALTHY",
}


def risk_intent(**overrides) -> SignalIntent:
    values: dict = {
        "signal_id": "sizing-v2-risk",
        "strategy_id": "live_llm",
        "symbol": "BTCUSDT",
        "side": OrderSide.BUY,
        "quantity": Decimal("100"),
        "limit_price": Decimal("100"),
        "metadata": {"direction": "LONG", "requested_leverage": "2"},
    }
    values.update(overrides)
    return SignalIntent(**values)


def check(intent: SignalIntent, **overrides):
    values: dict = {
        "account": Account(equity=Decimal("100000")),
        "positions": {},
        "market_price": Decimal("100"),
        "open_order_count": 0,
        **PROVEN,
    }
    values.update(overrides)
    return RiskEngine().check(intent, **values)


def test_risk_engine_rejects_notional_above_five_times_equity():
    decision = check(risk_intent(quantity=Decimal("6000")))

    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "MAX_SINGLE_NOTIONAL_EQUITY_MULTIPLE"


def test_risk_engine_rejects_gross_exposure_above_five_times_equity():
    existing = Position(
        symbol="ETHUSDT",
        base_asset="ETH",
        quote_asset="USDT",
        quantity=Decimal("4900"),
        avg_entry_price=Decimal("100"),
        cost_basis=Decimal("490000"),
    )
    decision = check(
        risk_intent(quantity=Decimal("200")),
        positions={"ETHUSDT": existing},
        market_prices={"ETHUSDT": Decimal("100")},
    )

    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "MAX_GROSS_EXPOSURE_EQUITY_MULTIPLE"


def test_risk_engine_rejects_a_size_claim_that_exceeds_the_risk_ceiling():
    """A buggy Sizer cannot smuggle an oversized loss past RiskEngine."""
    decision = check(
        risk_intent(
            metadata={
                "direction": "LONG",
                "requested_leverage": "2",
                "sizing_version": "v2",
                "llm_size_authority": "ADVISORY_ONLY",
                "sizing_risk_budget": "500",
                "sizing_effective_risk_fraction": "0.005",
                "sizing_approved_leverage": "2",
                "sizing_binding_cap": "RISK_BUDGET",
                "max_loss_estimate": "9000",
                # qty 100 x |100 - 90| = 1000, which fits the 1000 ceiling; the
                # oversized CLAIM is what must be rejected here.
                "sizing_stop_price": "90",
            }
        )
    )

    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "MAX_LOSS_EXCEEDS_RISK_BUDGET"


def test_risk_engine_rejects_a_v2_entry_that_omits_its_sizing_evidence():
    decision = check(
        risk_intent(
            metadata={
                "direction": "LONG",
                "requested_leverage": "2",
                "sizing_version": "v2",
                "llm_size_authority": "ADVISORY_ONLY",
            }
        )
    )

    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "SIZING_EVIDENCE_INCOMPLETE"


def test_risk_engine_rejects_a_v2_entry_that_grants_the_llm_quantity_authority():
    decision = check(
        risk_intent(
            metadata={
                "direction": "LONG",
                "requested_leverage": "2",
                "sizing_version": "v2",
                "llm_size_authority": "AUTHORITATIVE",
            }
        )
    )

    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "SIZING_AUTHORITY_CONTRACT_VIOLATION"


def test_risk_engine_rejects_a_risk_fraction_above_the_hard_ceiling():
    decision = check(
        risk_intent(
            metadata={
                "direction": "LONG",
                "requested_leverage": "2",
                "sizing_version": "v2",
                "llm_size_authority": "ADVISORY_ONLY",
                "sizing_risk_budget": "100",
                "sizing_effective_risk_fraction": "0.5",
                "sizing_approved_leverage": "2",
                "sizing_binding_cap": "RISK_BUDGET",
                "max_loss_estimate": "10",
                "sizing_stop_price": "99",
            }
        )
    )

    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "MAX_RISK_FRACTION_EXCEEDS_CEILING"


def test_risk_engine_accepts_a_well_formed_v2_entry_and_records_verification():
    decision = check(
        risk_intent(
            metadata={
                "direction": "LONG",
                "requested_leverage": "2",
                "sizing_version": "v2",
                "llm_size_authority": "ADVISORY_ONLY",
                "sizing_risk_budget": "500",
                "sizing_effective_risk_fraction": "0.005",
                "sizing_approved_leverage": "2",
                "sizing_binding_cap": "RISK_BUDGET",
                "max_loss_estimate": "100",
                "sizing_stop_price": "99",
            }
        )
    )

    assert decision.decision == ExecutionDecision.APPROVE
    assert decision.checks["sizing_risk_budget_verified"] == "500"
    assert decision.checks["sizing_max_loss_claimed"] == "100"
    assert decision.checks["sizing_max_loss_rederived"] == "100"
    assert decision.checks["sizing_llm_authority"] == "ADVISORY_ONLY"
    assert decision.checks["equity_baseline"] == "100000"
    assert decision.checks["hard_max_notional_multiple"] == "5"


def test_risk_engine_keeps_direction_and_never_rewrites_it():
    for side, direction in ((OrderSide.BUY, "LONG"), (OrderSide.SELL, "SHORT")):
        decision = check(
            risk_intent(
                side=side,
                metadata={"direction": direction, "requested_leverage": "1"},
            )
        )
        assert decision.side == side
        assert decision.checks["original_direction"] == direction


def test_risk_engine_still_only_proves_new_risk_from_a_valuation_batch():
    decision = RiskEngine().check(
        risk_intent(),
        account=Account(equity=Decimal("100000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        drawdown=Decimal("0"),
        valuation_quality="UNAVAILABLE",
    )

    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "VALUATION_UNAVAILABLE"


def test_risk_engine_hard_ceiling_gates_are_not_weakened_by_config():
    """Even a deliberately loose RiskConfig cannot widen 5x equity."""
    engine = RiskEngine(
        RiskConfig(
            max_order_notional=Decimal("100000000"),
            max_position_notional=Decimal("100000000"),
            max_account_exposure=Decimal("100000000"),
            max_exchange_exposure=Decimal("100000000"),
            max_symbol_exposure=Decimal("100000000"),
            max_single_notional_multiple=Decimal("50"),
            max_leverage=Decimal("50"),
        )
    )
    config = engine.config
    assert config.max_single_notional_multiple == HARD_MAX_NOTIONAL_MULTIPLE
    assert config.max_leverage == HARD_MAX_LEVERAGE

    decision = engine.check(
        risk_intent(quantity=Decimal("6000")),
        account=Account(equity=Decimal("100000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        **PROVEN,
    )
    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "MAX_SINGLE_NOTIONAL_EQUITY_MULTIPLE"


def test_conviction_multiplier_floor_is_the_documented_value():
    assert conviction_multiplier(Decimal("0.10")) == CONVICTION_MULTIPLIER_FLOOR
    assert conviction_multiplier(None) == CONVICTION_MULTIPLIER_FLOOR
    assert conviction_multiplier(Decimal("2")) == Decimal("1.40")


# ================================ adversarial hardening (independent review)
def test_risk_engine_rederives_the_stop_loss_risk_from_the_order_itself():
    """H1: a Sizer that UNDER-REPORTS its own loss must still be blocked.

    The claims below are internally consistent (loss 500 <= budget 500) and
    would pass a self-referential check, but the ORDER is 5x equity notional
    with a 10% stop, i.e. a 50,000 loss on a 100,000 account.
    """
    decision = check(
        risk_intent(
            quantity=Decimal("5000"),
            limit_price=Decimal("100"),
            metadata={
                "direction": "LONG",
                "requested_leverage": "1",
                "sizing_version": "v2",
                "llm_size_authority": "ADVISORY_ONLY",
                "sizing_risk_budget": "500",
                "sizing_effective_risk_fraction": "0.005",
                "sizing_approved_leverage": "1",
                "sizing_binding_cap": "RISK_BUDGET",
                "max_loss_estimate": "500",
                "sizing_stop_price": "90",
            },
        )
    )

    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason in {
        "DERIVED_MAX_LOSS_EXCEEDS_RISK_CEILING",
        "MAX_SINGLE_NOTIONAL_EQUITY_MULTIPLE",
    }


def test_risk_engine_rederivation_catches_a_zero_loss_claim():
    """The same order claiming a ZERO loss is still rejected."""
    decision = check(
        risk_intent(
            quantity=Decimal("5000"),
            limit_price=Decimal("100"),
            metadata={
                "direction": "LONG",
                "requested_leverage": "1",
                "sizing_version": "v2",
                "llm_size_authority": "ADVISORY_ONLY",
                "sizing_risk_budget": "500",
                "sizing_effective_risk_fraction": "0.005",
                "sizing_approved_leverage": "1",
                "sizing_binding_cap": "RISK_BUDGET",
                "max_loss_estimate": "0",
                "sizing_stop_price": "90",
            },
        )
    )

    assert decision.decision == ExecutionDecision.REJECT


def test_risk_engine_accepts_an_honest_re_derived_loss():
    """A truthful Sizer passes, and the re-derived loss is recorded."""
    decision = check(
        risk_intent(
            quantity=Decimal("25"),
            limit_price=Decimal("101"),
            metadata={
                "direction": "LONG",
                "requested_leverage": "2",
                "sizing_version": "v2",
                "llm_size_authority": "ADVISORY_ONLY",
                "sizing_risk_budget": "50",
                "sizing_effective_risk_fraction": "0.005",
                "sizing_approved_leverage": "2",
                "sizing_binding_cap": "RISK_BUDGET",
                "max_loss_estimate": "50",
                "sizing_stop_price": "99",
            },
        )
    )

    assert decision.decision == ExecutionDecision.APPROVE
    # qty 25 x |101 - 99| x 1 x 1 = 50, re-derived independently.
    assert decision.checks["sizing_max_loss_rederived"] == "50"
    assert Decimal(decision.checks["sizing_risk_ceiling"]) == Decimal("1000")
    assert decision.checks["sizing_max_loss_claimed"] == "50"


def test_risk_engine_rejects_a_v2_entry_without_the_stop_needed_to_verify():
    decision = check(
        risk_intent(
            metadata={
                "direction": "LONG",
                "requested_leverage": "1",
                "sizing_version": "v2",
                "llm_size_authority": "ADVISORY_ONLY",
                "sizing_risk_budget": "50",
                "sizing_effective_risk_fraction": "0.005",
                "sizing_approved_leverage": "1",
                "sizing_binding_cap": "RISK_BUDGET",
                "max_loss_estimate": "50",
            }
        )
    )

    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "SIZING_EVIDENCE_INCOMPLETE"


@pytest.mark.parametrize(
    "bad_stop", [Decimal("Infinity"), Decimal("-Infinity"), Decimal("NaN")]
)
def test_a_non_finite_stop_is_refused_and_never_rewritten(bad_stop):
    """M1: a non-finite stop must fail closed, never become a stop at 0."""
    rejected = size(side="SHORT", stop_price=bad_stop)
    assert rejected.rejected is True
    assert rejected.normalized_quantity == Decimal("0")
    assert "STOP_DISTANCE_UNAVAILABLE" in rejected.sizing_reason_codes
    # The audit must not assert a stop price that does not exist.
    assert rejected.audit.stop_price is None


def test_a_missing_stop_is_still_refused():
    rejected = size(stop_price=None)
    assert rejected.normalized_quantity == Decimal("0")
    assert "STOP_DISTANCE_UNAVAILABLE" in rejected.sizing_reason_codes


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("equity", "INVALID_SIZING_INPUT"),
        ("margin", "AVAILABLE_MARGIN_UNKNOWN"),
    ],
)
def test_non_finite_valuation_facts_fail_closed_instead_of_raising(field, reason):
    """M2: NaN/Infinity valuation facts must be a clean rejection + audit."""
    batch = valuation()
    if field == "equity":
        batch = dataclasses.replace(batch, raw_mtm_equity=Decimal("NaN"))
    else:
        batch = dataclasses.replace(batch, available_margin=Decimal("Infinity"))

    rejected = size(valuation=batch)

    assert rejected.rejected is True
    assert rejected.normalized_quantity == Decimal("0")
    assert reason in rejected.sizing_reason_codes
    assert rejected.audit.to_evidence()["sizing_reason_codes"]


def test_a_degenerate_static_order_cap_stays_restrictive():
    """L1: an unusable static cap must not vanish — it must stay strict."""
    policy = PositionSizingPolicy(static_max_order_notional=Decimal("0"))
    assert policy.static_max_order_notional == Decimal("0")
    assert "CONFIG_CLAMPED:static_max_order_notional" in policy.reason_codes

    result = LiveEntrySizingService(policy=policy).size(
        side="LONG",
        requested_leverage=Decimal("1"),
        account=Account(equity=EQUITY),
        positions={},
        instrument=instrument(),
        price=Decimal("100"),
        stop_price=ONE_PCT_STOP,
        liquidity_depth_qty=Decimal("1000000"),
        conviction=Decimal("0.80"),
        valuation=valuation(),
    )
    assert result.normalized_quantity == Decimal("0")
    assert result.rejected is True


def test_a_floor_above_the_ceiling_can_never_raise_risk():
    """L2: min_risk_per_trade must never push risk past the hard ceiling."""
    decision = risk_fraction_for_conviction(
        confidence=Decimal("0.30"),
        base_risk_per_trade=Decimal("0.005"),
        max_risk_per_trade=Decimal("0.010"),
        min_risk_per_trade=Decimal("0.5"),
    )
    assert decision.effective_fraction <= HARD_MAX_RISK_PER_TRADE
    assert decision.effective_fraction == Decimal("0.010")


def test_disabling_the_economic_gate_is_recorded_loudly():
    policy = PositionSizingPolicy(min_effective_notional_fraction=Decimal("0"))
    assert policy.min_effective_notional_fraction == Decimal("0")
    assert "CONFIG_NOTE:min_effective_notional_fraction_disabled" in policy.reason_codes


# =============================== §13/§14 ENTRY MINIMUM STOP DISTANCE GUARD (T1-T10)
# An invalid ultra-tight stop must NOT be a path to maximum size. A tighter stop
# shrinks the risk unit, so the risk budget alone cannot defend the account: it
# INFLATES the notional the budget buys until the 500% ceiling is what stops it.
# The entry is therefore REJECTED, never silently widened (sizing on a wider
# distance while executing the tighter stop would keep the theoretical loss
# identical while manufacturing systematic noise stop-outs).


def test_T1_a_normal_stop_is_unchanged_by_the_guard():
    """T1: stop comfortably above the minimum -> identical sizing."""
    result = size(stop_price=Decimal("99"))

    assert result.rejected is False
    assert result.risk_normalized_notional == Decimal("50000")
    assert result.audit.stop_distance == Decimal("1.0")
    assert result.audit.minimum_stop_distance == Decimal("0.1")
    # The effective sizing distance IS the requested distance.
    assert result.audit.stop_distance_source == "LLM_REQUESTED"


def test_T2_a_stop_exactly_at_the_minimum_is_accepted():
    """T2: the boundary is inclusive (>=), not exclusive."""
    result = size(stop_price=Decimal("99.9"))

    assert result.rejected is False
    assert result.audit.stop_distance == result.audit.minimum_stop_distance
    assert result.risk_normalized_notional == Decimal("500000")


@pytest.mark.parametrize("stop", ["99.9001", "99.95", "99.99", "99.999", "99.9999"])
def test_T3_a_stop_below_the_minimum_is_rejected(stop):
    """T3: anything closer than the minimum is refused, not resized."""
    result = size(stop_price=Decimal(stop))

    assert result.rejected is True
    assert result.risk_normalized_notional == Decimal("0")
    assert result.normalized_quantity == Decimal("0")
    assert result.sizing_reason_codes[-1] == "STOP_DISTANCE_BELOW_MINIMUM"


def test_T4_an_absurd_stop_cannot_buy_the_500_percent_ceiling():
    """T4: 0.01% - the theoretical 5,000,000 notional is unreachable."""
    result = size(stop_price=Decimal("99.99"))

    assert result.rejected is True
    assert result.risk_normalized_notional == Decimal("0")
    assert result.audit.minimum_stop_distance == Decimal("0.1")
    # The invalid stop never even reaches cap math.
    assert result.binding_cap == "NONE"


def test_T5_high_volatility_expands_the_minimum_stop():
    """T5: a factual 2% realized volatility raises the floor to 2% of price."""
    volatile = size(stop_price=Decimal("99"), volatility=Decimal("0.02"))

    assert volatile.rejected is True
    assert volatile.audit.minimum_stop_distance == Decimal("2.0")
    assert volatile.sizing_reason_codes[-1] == "STOP_DISTANCE_BELOW_MINIMUM"

    wide_enough = size(stop_price=Decimal("98"), volatility=Decimal("0.02"))
    assert wide_enough.rejected is False
    assert wide_enough.audit.minimum_stop_distance == Decimal("2.0")


def test_T6_low_volatility_still_uses_the_absolute_floor():
    """T6: a quiet market never relaxes the absolute fraction floor."""
    for volatility in (Decimal("0"), Decimal("0.0000001")):
        result = size(stop_price=Decimal("99.95"), volatility=volatility)
        assert result.rejected is True
        assert result.audit.minimum_stop_distance == Decimal("0.1")


def test_T7_the_guard_does_not_weaken_the_5x_cap():
    """T7: the tightest VALID stop still stops exactly at 5x equity."""
    result = size(
        stop_price=Decimal("99.9"),
        valuation=valuation(equity=Decimal("100000"), margin=Decimal("10000000")),
        liquidity_depth_qty=Decimal("1000000000"),
    )

    assert result.rejected is False
    assert result.risk_normalized_notional == EQUITY * HARD_MAX_NOTIONAL_MULTIPLE
    assert result.audit.notional_pct_of_equity == HARD_MAX_NOTIONAL_MULTIPLE


def test_T8_the_guard_does_not_weaken_the_one_percent_risk_cap():
    """T8: max loss at the stop still cannot exceed 1% of equity."""
    for stop in (Decimal("99.9"), Decimal("99"), Decimal("95")):
        for conviction in (Decimal("0.0"), Decimal("0.80"), Decimal("1.0")):
            result = size(stop_price=stop, conviction=conviction)
            assert result.max_loss_estimate <= EQUITY * HARD_MAX_RISK_PER_TRADE


def test_T9_the_guard_preserves_account_scaling():
    """T9: the floor is a FRACTION of price, so scaling is untouched."""
    small = size(
        valuation=valuation(equity="10000", margin="10000"),
        account=Account(equity=Decimal("10000")),
        liquidity_depth_qty=Decimal("1000000"),
    )
    large = size(stop_price=Decimal("99"), valuation=valuation(equity="100000"))

    assert small.rejected is False and large.rejected is False
    assert small.audit.minimum_stop_distance == large.audit.minimum_stop_distance
    assert large.risk_normalized_notional == small.risk_normalized_notional * 10


def test_T10_the_guard_does_not_enable_scale_in():
    """T10: this guard is a defensive entry rule; ADD stays disabled."""
    from crypto_trader.scale_in import ADD_EXECUTION_ENABLED, ScaleInPolicy
    from crypto_trader.scale_in.policy import ENABLE_LLM_AUTOMATIC_SCALE_IN

    assert ENABLE_LLM_AUTOMATIC_SCALE_IN is False
    assert ADD_EXECUTION_ENABLED is False
    assert ScaleInPolicy().enabled is False
    assert ScaleInPolicy().average_down_enabled is False


def test_the_guard_floor_cannot_be_configured_downward():
    """One-way ratchet: config may tighten the floor, never weaken it."""
    from crypto_trader.sizing.policy import HARD_MIN_STOP_DISTANCE_FRACTION

    lowered = PositionSizingPolicy(min_stop_distance_fraction=Decimal("0.00001"))
    assert lowered.min_stop_distance_fraction == HARD_MIN_STOP_DISTANCE_FRACTION
    assert "CONFIG_CLAMPED:min_stop_distance_fraction" in lowered.reason_codes

    tightened = PositionSizingPolicy(min_stop_distance_fraction=Decimal("0.01"))
    assert tightened.min_stop_distance_fraction == Decimal("0.01")
    assert tightened.hard_ceiling_violations == ()

    # A wildly tight stop is refused even by a policy that tries to allow it.
    service = LiveEntrySizingService(
        policy=PositionSizingPolicy(min_stop_distance_fraction=Decimal("0.00001"))
    )
    assert service.policy.min_stop_distance_fraction == HARD_MIN_STOP_DISTANCE_FRACTION
