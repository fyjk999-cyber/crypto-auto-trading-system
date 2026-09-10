from decimal import Decimal

from crypto_trader.validation.oos import evaluate_oos


def test_oos_evaluator_reports_test_only_pass_fail():
    result = evaluate_oos(
        train_metric=Decimal("3"), validation_metric=Decimal("2"),
        test_metric=Decimal("1"), min_test_metric=Decimal("0"),
    )
    assert result.passed is True
    assert result.degradation == Decimal("2")
