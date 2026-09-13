"""P0-2: recovery must never infer "never existed" from "not found".

    ORDER NOT FOUND != ORDER NEVER EXISTED

Only a positive pre-broker proof may terminalise an order as REJECTED. Every
other case stays unresolved, and NO case resubmits.
"""

from __future__ import annotations

from crypto_trader.order.recovery_classification import (
    CLASS_AMBIGUOUS,
    CLASS_BROKER_ID_MISSING,
    CLASS_DURABLE_FILL_PRESENT,
    CLASS_LOOKUP_UNREADABLE,
    CLASS_PROVEN_PRE_BROKER,
    DISPOSITION_MISSING,
    DISPOSITION_PRESERVE_FILL,
    DISPOSITION_REJECT,
    DISPOSITION_UNKNOWN,
    classify_recovery_lookup_outcome,
)


def _classify(**overrides):
    facts = {
        "lookup_ok": True,
        "exchange_order_id": None,
        "filled_quantity": 0,
        "durable_fill_count": 0,
        "failure_reason": None,
        "pre_broker_lineage_proven": False,
        "has_client_order_id": True,
    }
    facts.update(overrides)
    return classify_recovery_lookup_outcome(**facts)


# --------------------------------------------------------------------- A


def test_A_proven_pre_broker_is_rejected():
    verdict = _classify(
        failure_reason="MARKET_DATA_UNAVAILABLE",
        pre_broker_lineage_proven=True,
    )
    assert verdict.classification == CLASS_PROVEN_PRE_BROKER
    assert verdict.disposition == DISPOSITION_REJECT
    assert verdict.may_terminalise_as_rejected is True
    assert verdict.may_resubmit is False


def test_A_requires_positive_proof_not_just_a_null_exchange_id():
    """The base candidate's error: NULL exchange id alone is NOT proof."""
    verdict = _classify(exchange_order_id=None, failure_reason=None)
    assert verdict.disposition == DISPOSITION_UNKNOWN
    assert verdict.may_terminalise_as_rejected is False


# --------------------------------------------------------------------- B


def test_B_ambiguous_timeout_stays_unknown():
    verdict = _classify(failure_reason="TIMEOUT")
    assert verdict.classification == CLASS_AMBIGUOUS
    assert verdict.disposition == DISPOSITION_UNKNOWN
    assert verdict.may_terminalise_as_rejected is False


def test_B_connection_reset_stays_unknown():
    assert (
        _classify(failure_reason="CONNECTION RESET").disposition
        == DISPOSITION_UNKNOWN
    )


def test_B_pre_broker_reason_without_lineage_stays_unknown():
    """A matching reason string is not enough - the lineage must prove it too."""
    verdict = _classify(failure_reason="MARKET_DATA_UNAVAILABLE")
    assert verdict.disposition == DISPOSITION_UNKNOWN
    assert verdict.may_terminalise_as_rejected is False


# --------------------------------------------------------------------- C


def test_C_broker_id_present_and_missing_is_not_rejected():
    verdict = _classify(exchange_order_id="sim_abc123", failure_reason="TIMEOUT")
    assert verdict.classification == CLASS_BROKER_ID_MISSING
    assert verdict.disposition == DISPOSITION_MISSING
    assert verdict.may_terminalise_as_rejected is False
    assert verdict.may_resubmit is False


# --------------------------------------------------------------------- D


def test_D_durable_fill_wins_over_not_found():
    verdict = _classify(durable_fill_count=1, exchange_order_id="sim_abc")
    assert verdict.classification == CLASS_DURABLE_FILL_PRESENT
    assert verdict.disposition == DISPOSITION_PRESERVE_FILL
    assert verdict.may_terminalise_as_rejected is False


def test_D_durable_fill_wins_even_with_pre_broker_proof():
    """Factual execution evidence outranks every other signal."""
    verdict = _classify(
        durable_fill_count=2,
        failure_reason="MARKET_DATA_UNAVAILABLE",
        pre_broker_lineage_proven=True,
    )
    assert verdict.disposition == DISPOSITION_PRESERVE_FILL


# --------------------------------------------------------------------- E


def test_E_lookup_failure_is_unknown():
    verdict = _classify(lookup_ok=False)
    assert verdict.classification == CLASS_LOOKUP_UNREADABLE
    assert verdict.disposition == DISPOSITION_UNKNOWN
    assert verdict.may_terminalise_as_rejected is False


# ----------------------------------------------------------------- invariants


def test_no_case_ever_resubmits():
    """NO_BLIND_RESUBMIT across the whole matrix."""
    matrix = [
        _classify(failure_reason="MARKET_DATA_UNAVAILABLE", pre_broker_lineage_proven=True),
        _classify(failure_reason="TIMEOUT"),
        _classify(exchange_order_id="sim_x"),
        _classify(durable_fill_count=1),
        _classify(lookup_ok=False),
        _classify(),
        _classify(filled_quantity=5),
    ]
    assert all(v.may_resubmit is False for v in matrix)


def test_nonzero_filled_quantity_blocks_rejection():
    verdict = _classify(
        filled_quantity=1,
        failure_reason="MARKET_DATA_UNAVAILABLE",
        pre_broker_lineage_proven=True,
    )
    assert verdict.may_terminalise_as_rejected is False


def test_only_proven_pre_broker_class_may_reject():
    matrix = [
        _classify(failure_reason="MARKET_DATA_UNAVAILABLE", pre_broker_lineage_proven=True),
        _classify(failure_reason="TIMEOUT"),
        _classify(exchange_order_id="sim_x"),
        _classify(durable_fill_count=1),
        _classify(lookup_ok=False),
    ]
    rejecting = [v for v in matrix if v.may_terminalise_as_rejected]
    assert len(rejecting) == 1
    assert rejecting[0].classification == CLASS_PROVEN_PRE_BROKER
