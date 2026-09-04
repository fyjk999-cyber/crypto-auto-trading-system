from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.models import Account, Instrument, Position
from crypto_trader.sizing.service import LiveEntrySizingService


def instrument(contract_size: str = "1", lot: str = "0.001") -> Instrument:
    return Instrument(
        symbol="ETHUSDT",
        base_asset="ETH",
        quote_asset="USDT",
        instrument_type="LINEAR_PERP",
        contract_size=contract_size,
        step_size=lot,
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
    assert long.normalized_quantity == short.normalized_quantity == Decimal("2")
    assert long.max_loss_estimate == short.max_loss_estimate == Decimal("10")
    invalid = size(requested_quantity=Decimal("0"))
    assert invalid.normalized_quantity == 0
    assert invalid.sizing_reason_codes == ("INVALID_SIZING_INPUT",)


def test_sizing_uses_account_equity_volatility_contract_and_minimum_lot():
    small = size(account=Account(equity=Decimal("100")))
    large = size(account=Account(equity=Decimal("10000")))
    assert small.normalized_quantity < large.normalized_quantity
    contract = size(instrument=instrument("0.01", "1"), requested_quantity=Decimal("500"))
    assert contract.normalized_quantity == Decimal("200")
    below_lot = size(
        account=Account(equity=Decimal("1")),
        instrument=instrument("1", "1"),
    )
    assert below_lot.normalized_quantity == 0
    volatile = size(volatility=Decimal("0.10"))
    assert volatile.risk_bounded_leverage == 1


def test_sizing_reports_existing_exposure_and_caps_requested_notional():
    position = Position(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("1"),
        cost_basis=Decimal("500"),
    )
    result = size(
        positions={"BTCUSDT": position},
        requested_quantity=Decimal("1000"),
        stop_price=None,
    )
    assert result.requested_notional == Decimal("100000")
    assert result.risk_normalized_notional == Decimal("10000")
    assert result.portfolio_exposure_after_trade == Decimal("10500")
    assert "MAX_ORDER_NOTIONAL" in result.sizing_reason_codes
