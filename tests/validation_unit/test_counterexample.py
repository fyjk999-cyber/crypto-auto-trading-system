from crypto_trader.validation.counterexample import retain_counterexample


def test_counterexample_is_retained_even_when_unfavorable():
    item = retain_counterexample(
        "factor_hit_loss",
        evidence_present=True,
        outcome="LOSS",
        note="factor fired but trade lost",
    )
    assert item.evidence_present is True
    assert item.outcome == "LOSS"
