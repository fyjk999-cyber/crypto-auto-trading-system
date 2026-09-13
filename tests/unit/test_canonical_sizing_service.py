"""Canonical deterministic sizing contract for Live-LLM entry proposals (V2).

The LLM's raw quantity is ADVISORY ONLY: these tests pin the deterministic,
capital-aware contract that replaced the old
``min(requested_quantity, risk_quantity)`` model.
"""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.models import Account, Instrument, Position
from crypto_trader.sizing.service import LiveEntrySizingService
from crypto_trader.valuation.domain import ValuationBatch


def instrument(contract_size: str = "1", lot: str = "0.001") -> Instrument:
    return Instrument(
        symbol="ETHUSDT",
        base_asset="ETH",
        quote_asset="USDT",
        instrument_type="LINEAR_PERP",
        contract_size=contract_size,
        step_size=lot,
    )


def batch(equity: str = "1000", margin: str | None = "1000") -> ValuationBatch:
    return ValuationBatch(
        valuation_id="val-canonical-sizing",
        account_id="default",
        currency="USDT",
        quality="HEALTHY",
        raw_mtm_equity=Decimal(equity),
        available_margin=None if margin is None else Decimal(margin),
    )


def size(**overrides):
    values = {
        "side": "LONG",
        "requested_quantity": Decimal("10"),
        "requested_leverage": Decimal("5"),
        "account": Account(equity=Decimal("1000")),
        "positions": {},
        "instrument": instrument(),
        "price": Decimal("100"),
        "stop_price": Decimal("95"),
        "liquidity_depth_qty": Decimal("1000000"),
        # Explicit conviction: the risk budget is base x conviction multiplier,
        # so an unspecified conviction is the LOWEST band by construction.
        "conviction": Decimal("0.80"),
        "valuation": batch(),
    }
    values.update(overrides)
    return LiveEntrySizingService(
        risk_fraction=Decimal("0.01"),
        max_order_notional=Decimal("10000"),
        max_leverage=Decimal("3"),
    ).size(**values)


def test_sizing_is_long_short_symmetric_and_never_invents_fixed_quantity():
    long = size(side="LONG")
    short = size(side="SHORT")
    # equity 1,000 x 1% = 10 risk budget; a 5% stop is a 5-unit risk unit.
    assert long.normalized_quantity == short.normalized_quantity == Decimal("2")
    assert long.max_loss_estimate == short.max_loss_estimate == Decimal("10")
    assert long.binding_cap == "RISK_BUDGET"


def test_sizing_rejects_an_unusable_side_instead_of_defaulting_one():
    invalid = size(side="SIDEWAYS")
    assert invalid.normalized_quantity == 0
    assert invalid.rejected is True
    assert "INVALID_SIZING_INPUT" in invalid.sizing_reason_codes


def test_sizing_uses_account_equity_volatility_contract_and_minimum_lot():
    small = size(valuation=batch(equity="100"))
    large = size(valuation=batch(equity="10000"))
    assert small.normalized_quantity < large.normalized_quantity
    contract = size(instrument=instrument("0.01", "1"))
    # notional per unit = 100 x 0.01 = 1; risk unit = 5.0 x 0.01 = 0.05, so a
    # 10-unit risk budget buys 200 contracts (200 notional).
    assert contract.normalized_quantity == Decimal("200")
    assert contract.risk_normalized_notional == Decimal("200")
    below_lot = size(valuation=batch(equity="1"), instrument=instrument("1", "1"))
    assert below_lot.normalized_quantity == 0
    # A 10% realized volatility also raises the entry minimum stop distance to
    # 10% of price, so the stop must be at least that far away to be sized.
    volatile = size(volatility=Decimal("0.10"), stop_price=Decimal("90"))
    assert volatile.rejected is False
    assert volatile.risk_bounded_leverage == 1


def test_existing_exposure_reduces_remaining_portfolio_capacity():
    position = Position(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("1"),
        cost_basis=Decimal("500"),
    )
    result = size(
        positions={"BTCUSDT": position},
        valuation=batch(equity="1000", margin="1000000"),
        # 0.1% of 100 - exactly the deterministic minimum, so the stop guard
        # passes and PORTFOLIO is what binds (the asserted numbers are unchanged).
        stop_price=Decimal("99.9"),
        liquidity_depth_qty=Decimal("1000000"),
    )
    assert result.rejected is False
    # equity 1,000 x 5 = 5,000 gross ceiling; 500 is already committed, so only
    # 4,500 of notional remains -> 45 units, and PORTFOLIO is what binds.
    assert result.audit.existing_gross_exposure == Decimal("500")
    assert result.audit.portfolio_cap_qty == Decimal("45")
    assert result.normalized_quantity == Decimal("45")
    assert result.risk_normalized_notional == Decimal("4500")
    assert result.portfolio_exposure_after_trade == Decimal("5000")
    assert result.binding_cap == "PORTFOLIO"
    # The legacy static order-notional ceiling is still carried as a policy cap.
    assert result.audit.policy["static_max_order_notional"] == "10000"


def test_llm_advisory_exposure_is_recorded_but_never_authoritative():
    result = size(requested_quantity=Decimal("0"), requested_exposure=Decimal("500"))
    # Advisory exposure is preserved for audit...
    assert result.audit.llm_requested_exposure == Decimal("500")
    # ...and the deterministic risk-derived size is what gets authorised.
    assert result.normalized_quantity == Decimal("2")
    assert result.risk_normalized_notional == Decimal("200")


def test_sizing_values_existing_same_symbol_position_at_current_price():
    position = Position(
        symbol="ETHUSDT",
        base_asset="ETH",
        quote_asset="USDT",
        quantity=Decimal("1"),
        avg_entry_price=Decimal("50"),
        cost_basis=Decimal("50"),
    )
    result = size(positions={"ETHUSDT": position})
    assert result.symbol_exposure_after_trade == Decimal("300")
    assert result.audit.existing_symbol_exposure == Decimal("100")
