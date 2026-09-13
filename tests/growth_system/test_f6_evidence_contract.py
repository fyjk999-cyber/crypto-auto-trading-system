"""Mission A: F6 causal evidence availability contract."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from crypto_trader.governance.trade_episode import FactualTradeEpisode
from crypto_trader.learning.growth_review_evidence import (
    CausalEvidenceUnavailable,
    GrowthReviewEvidence,
    validate_causal_evidence_refs,
)
from crypto_trader.learning.growth_runtime_learning import _episode_review_input


def _evidence(**kw):
    return GrowthReviewEvidence(episode_id="ep", **kw)


def test_f6_available_zero_is_factual_zero():
    ev = _evidence(
        fees=Decimal("0"), fees_availability="AVAILABLE",
        funding=Decimal("0"), funding_availability="AVAILABLE",
    )
    ev.validate_availability()
    assert ev.fees == 0 and ev.funding == 0


def test_f6_unavailable_zero_fails_invariant():
    ev = _evidence(slippage=0, slippage_availability="UNAVAILABLE")
    with pytest.raises(ValueError):
        ev.validate_availability()


def test_f6_available_missing_ref_fails_invariant():
    ev = _evidence(risk_availability="AVAILABLE", risk_decision_id=None)
    with pytest.raises(ValueError):
        ev.validate_availability()


def test_f6_unavailable_causal_ref_blocked():
    ev = _evidence(slippage_availability="UNAVAILABLE")
    with pytest.raises(CausalEvidenceUnavailable):
        validate_causal_evidence_refs(ev, ["slippage"])


def test_f6_available_causal_ref_accepted():
    ev = _evidence(
        risk_availability="AVAILABLE", risk_decision_id="risk:1",
        fees_availability="AVAILABLE",
    )
    validate_causal_evidence_refs(ev, ["risk:1", "accounting:fees"])


def test_f6_mixed_unavailable_ref_blocked():
    ev = _evidence(
        risk_availability="AVAILABLE", risk_decision_id="risk:1",
        slippage_availability="UNAVAILABLE",
    )
    with pytest.raises(CausalEvidenceUnavailable):
        validate_causal_evidence_refs(ev, ["risk:1", "slippage"])


def test_f6_envelope_reaches_review_input_with_availability():
    episode = FactualTradeEpisode(
        episode_id="ep_f6", trade_plan_id="p", symbol="BTCUSDT", direction="LONG",
        entry_decision_id="d", exit_decision_id=None, position_decision_ids=[],
        risk_decision_ids=[], order_ids=[], fill_ids=[], entry_price=Decimal("1"),
        exit_price=Decimal("1"), opened_quantity=Decimal("1"),
        closed_quantity=Decimal("1"), leverage=Decimal("1"), fees=Decimal("0"),
        funding_pnl=Decimal("0"), gross_pnl=Decimal("0"), net_pnl=Decimal("0"),
        holding_time_seconds=1.0, entry_market_regime="TREND",
        terminal_reason="EXIT", opened_at=datetime(2026, 1, 1, tzinfo=UTC),
        closed_at=datetime(2026, 1, 1, 1, tzinfo=UTC),
    )
    evidence = GrowthReviewEvidence(
        episode_id="ep_f6",
        factor_snapshot_availability="UNAVAILABLE",
        slippage_availability="UNAVAILABLE",
        fees_availability="AVAILABLE",
        missing_evidence=["FACTOR_SNAPSHOT", "SLIPPAGE"],
    )
    payload = _episode_review_input(
        episode,
        account_id="default",
        mode="PAPER",
        currency="USDT",
        review_evidence=evidence,
    )
    assert payload.review_evidence == evidence.as_payload()
    assert payload.review_evidence["factor_snapshot_availability"] == "UNAVAILABLE"
    assert payload.review_evidence["slippage_availability"] == "UNAVAILABLE"
    assert payload.review_evidence["fees_availability"] == "AVAILABLE"
    assert payload.missing_evidence == ["FACTOR_SNAPSHOT", "SLIPPAGE"]


def test_risk_04_invariant():
    ev = GrowthReviewEvidence(
        episode_id="ep", risk_availability="AVAILABLE",
        risk_decision_ids=[], risk_decision_id=None,
    )
    try:
        ev.validate_availability()
    except ValueError:
        pass
    else:
        raise AssertionError("available risk without id list must fail")
    ev2 = GrowthReviewEvidence(
        episode_id="ep", risk_availability="AVAILABLE",
        risk_decision_ids=["risk-1"], risk_decision_id="risk-2",
    )
    try:
        ev2.validate_availability()
    except ValueError:
        pass
    else:
        raise AssertionError("primary risk mismatch must fail")


@pytest.mark.parametrize(
    "order_ids,fill_ids",
    [([], ["f1"]), (["o1"], []), ([], [])],
)
def test_execution_invariant_blocks_incomplete_lineage(order_ids, fill_ids):
    ev = GrowthReviewEvidence(
        episode_id="ep",
        execution_availability="AVAILABLE",
        order_ids=order_ids,
        fill_ids=fill_ids,
    )
    with pytest.raises(ValueError):
        ev.validate_availability()


def test_execution_invariant_positive_control():
    ev = GrowthReviewEvidence(
        episode_id="ep",
        execution_availability="AVAILABLE",
        order_ids=["o1"],
        fill_ids=["f1"],
    )
    ev.validate_availability()
