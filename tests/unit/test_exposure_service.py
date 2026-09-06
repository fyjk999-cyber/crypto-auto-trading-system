from decimal import Decimal

from crypto_trader.domain.models import Position
from crypto_trader.exposure.service import ExposureService, InstrumentExposureSpec


def test_spot_and_linear_swap_notional_use_canonical_contract_size():
    spot = ExposureService.calculate(
        quantity="2", price="100", spec=InstrumentExposureSpec("SPOT"), side="LONG"
    )
    swap = ExposureService.calculate(
        quantity="2",
        price="100",
        spec=InstrumentExposureSpec("SWAP", contract_size=Decimal("0.01")),
        side="SHORT",
    )
    assert spot.gross_notional == Decimal("200")
    assert swap.gross_notional == Decimal("2")
    assert swap.signed_notional == Decimal("-2")


def test_inverse_contract_notional_is_contract_value_not_price_times_quantity():
    inverse = ExposureService.calculate(
        quantity="3",
        price="80000",
        spec=InstrumentExposureSpec(
            "INVERSE_PERP",
            contract_size=Decimal("100"),
            contract_multiplier=Decimal("1"),
        ),
        side="LONG",
    )
    assert inverse.gross_notional == Decimal("300")


def test_portfolio_exposure_uses_one_canonical_mark_price_map():
    positions = {
        "BTCUSDT": Position(
            symbol="BTCUSDT",
            base_asset="BTC",
            quote_asset="USDT",
            quantity=Decimal("2"),
            avg_entry_price=Decimal("100"),
            cost_basis=Decimal("2"),
            instrument_type="LINEAR_PERP",
            contract_size=Decimal("0.01"),
        ),
        "ETHUSDT": Position(
            symbol="ETHUSDT",
            base_asset="ETH",
            quote_asset="USDT",
            quantity=Decimal("-3"),
            avg_entry_price=Decimal("50"),
            cost_basis=Decimal("150"),
        ),
    }
    exposure = ExposureService.for_portfolio(
        positions,
        prices={"BTCUSDT": Decimal("120"), "ETHUSDT": Decimal("60")},
    )
    assert exposure.gross_notional == Decimal("182.4")
    assert exposure.signed_notional == Decimal("-177.6")
