from decimal import Decimal

from crypto_trader.risk.leverage import clamp_leverage


def test_leverage_is_bounded_without_using_confidence():
    assert clamp_leverage(requested="20", max_leverage="5") == Decimal("5")
    assert clamp_leverage(requested="0", max_leverage="5") == Decimal("1")
    assert clamp_leverage(requested="5", max_leverage="5", volatility="0.1") == Decimal("1")
    assert clamp_leverage(requested="5", max_leverage="5", liquidity="0") == Decimal("1")
