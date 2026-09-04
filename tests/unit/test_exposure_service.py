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
