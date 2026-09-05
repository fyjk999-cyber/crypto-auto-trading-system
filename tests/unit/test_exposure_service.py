from decimal import Decimal

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
