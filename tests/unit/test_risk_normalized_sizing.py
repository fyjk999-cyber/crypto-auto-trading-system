from decimal import Decimal

from crypto_trader.sizing.risk_normalized import calculate_risk_normalized_size


def test_risk_normalized_size_uses_equity_stop_and_contract_size():
    result = calculate_risk_normalized_size(
        equity="1000",
        risk_fraction="0.01",
        price="100",
        stop_distance="5",
        contract_size="0.01",
        lot_size="1",
    )
    assert result.risk_budget == Decimal("10")
    assert result.quantity == Decimal("200")
    assert result.gross_notional == Decimal("200")


def test_invalid_risk_inputs_never_produce_fixed_fallback_size():
    result = calculate_risk_normalized_size(
        equity="0", risk_fraction="0.01", price="100", stop_distance="5"
    )
    assert result.quantity == 0
