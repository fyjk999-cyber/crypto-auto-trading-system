from decimal import Decimal

from crypto_trader.validation.ablation import compare_ablation


def test_ablation_reports_evidence_effect_without_execution_authority():
    result = compare_ablation(
        "factor_removed", baseline=Decimal("10"), ablated=Decimal("7")
    )
    assert result.name == "factor_removed"
    assert result.evidence_effect == Decimal("3")
