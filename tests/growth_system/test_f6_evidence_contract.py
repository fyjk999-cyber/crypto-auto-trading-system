"""Mission A: F6 causal evidence availability contract."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from crypto_trader.governance.trade_episode import FactualTradeEpisode
from crypto_trader.learning.growth_contracts import EpisodeReviewInput
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



def _refs(ev, **kw):
    kw.setdefault("selected_tools", [])
    return EpisodeReviewInput.model_construct(
        episode_id=ev.episode_id, review_evidence=ev.as_payload(), **kw
    ).derived_refs()


def test_ref_01_full_available():
    ev = GrowthReviewEvidence(
        episode_id="ep-1", decision_id="decision-1",
        decision_availability="AVAILABLE", risk_decision_ids=["risk-1", "risk-2"],
        risk_decision_id="risk-1", risk_availability="AVAILABLE",
        order_ids=["order-1", "order-2"], fill_ids=["fill-1", "fill-2"],
        execution_availability="AVAILABLE", exit_reason="STOP_LOSS",
        exit_availability="AVAILABLE", fees_availability="AVAILABLE",
        funding_availability="AVAILABLE",
    )
    refs = _refs(ev)
    assert refs == {
        "episode:ep-1", "decision:decision-1", "risk:risk-1", "risk:risk-2",
        "order:order-1", "order:order-2", "fill:fill-1", "fill:fill-2",
        "exit:terminal", "accounting:fees", "accounting:funding",
    }


def test_ref_02_decision_gate():
    ev = GrowthReviewEvidence(
        episode_id="ep-1", decision_id="decision-1",
        decision_availability="UNAVAILABLE",
    )
    refs = _refs(ev, entry_decision_id="decision-1")
    assert "decision:decision-1" not in refs


def test_ref_03_execution_gate():
    ev = GrowthReviewEvidence(
        episode_id="ep-1", order_ids=["order-1"], fill_ids=["fill-1"],
        execution_availability="UNAVAILABLE",
    )
    refs = _refs(ev, order_refs=["order-1"], fill_refs=["fill-1"])
    assert "order:order-1" not in refs and "fill:fill-1" not in refs


def test_ref_04_risk_gate():
    ev = GrowthReviewEvidence(
        episode_id="ep-1", risk_decision_ids=["risk-1"],
        risk_availability="UNAVAILABLE",
    )
    assert "risk:risk-1" not in _refs(ev)


@pytest.mark.parametrize(
    "fees,funding,fee_ref,fund_ref",
    [("AVAILABLE", "UNAVAILABLE", True, False),
     ("UNAVAILABLE", "AVAILABLE", False, True)],
)
def test_ref_05_accounting_independent(fees, funding, fee_ref, fund_ref):
    ev = GrowthReviewEvidence(
        episode_id="ep-1", fees_availability=fees,
        funding_availability=funding,
    )
    refs = _refs(ev)
    assert ("accounting:fees" in refs) is fee_ref
    assert ("accounting:funding" in refs) is fund_ref


def test_ref_06_exit_terminal():
    ev = GrowthReviewEvidence(
        episode_id="ep-1", exit_reason="STOP_LOSS",
        exit_availability="AVAILABLE",
    )
    refs = _refs(ev, exit_decision_id="decision-exit")
    assert "exit:terminal" in refs
    assert "decision:decision-exit" not in refs


def test_ref_07_all_causal_unavailable():
    ev = GrowthReviewEvidence(
        episode_id="ep-1",
        decision_availability="UNAVAILABLE",
        risk_availability="UNAVAILABLE",
        execution_availability="UNAVAILABLE",
        exit_availability="UNAVAILABLE",
        fees_availability="UNAVAILABLE",
        funding_availability="UNAVAILABLE",
    )
    assert _refs(ev) == {"episode:ep-1"}



def test_unavailable_ref_rejected_by_structured_review_validation():
    from crypto_trader.learning.growth_contracts import (
        ObservationFact,
        ReferenceValidationError,
        StructuredReview,
        validate_review,
    )
    review = StructuredReview(
        episode_id="ep-hidden",
        observation_facts=[
            ObservationFact(
                statement="Hidden risk caused loss.",
                evidence_refs=["risk:risk-hidden"],
            )
        ],
    )
    with pytest.raises(ReferenceValidationError):
        validate_review(
            review,
            allowed_refs={"episode:ep-hidden"},
            expected_episode_id="ep-hidden",
        )
