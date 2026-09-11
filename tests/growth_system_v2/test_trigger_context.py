"""G10 trigger/context contract tests (TEST_ONLY)."""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_trader.learning.growth_card_retrieval import (
    CardRankingPolicy,
    evaluate_hard_applicability,
)
from crypto_trader.learning.growth_v2_contracts import (
    UNKNOWN,
    ContextSignature,
    TriggerSignature,
)
from tests.growth_system_v2.conftest import AS_OF, market_context, trigger

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def test_same_input_is_deterministic_and_order_independent():
    states = [
        {"factor_id": "funding_rate", "state": "EXTREME_HIGH", "definition_version": "v1"},
        {"factor_id": "open_interest", "state": "RISING", "definition_version": "v2"},
    ]
    first = TriggerSignature.from_factor_states(states, as_of=NOW)
    second = TriggerSignature.from_factor_states(list(reversed(states)), as_of=NOW)
    assert first.signature_hash() == second.signature_hash()
    assert [factor.factor_id for factor in first.factors] == [
        "FUNDING_RATE",
        "OPEN_INTEREST",
    ]


def test_unknown_input_is_unknown_never_guessed():
    signature = TriggerSignature.from_factor_states(
        [
            {"factor_id": "funding_rate", "state": None, "definition_version": None},
            {"state": "RISING", "definition_version": "v1"},
        ],
        as_of=NOW,
    )
    assert signature.complete is False
    funding = [factor for factor in signature.factors if factor.factor_id == "FUNDING_RATE"][0]
    assert funding.state == UNKNOWN and funding.definition_version == UNKNOWN
    assert "FUNDING_RATE" in signature.incomplete_factors


def test_conflicting_duplicate_factor_degrades_to_unknown():
    signature = TriggerSignature.from_factor_states(
        [
            {"factor_id": "funding_rate", "state": "HIGH", "definition_version": "v1"},
            {"factor_id": "funding_rate", "state": "LOW", "definition_version": "v1"},
        ],
        as_of=NOW,
    )
    assert "FUNDING_RATE" in signature.conflicts
    factor = signature.factors[0]
    assert factor.state == UNKNOWN


def test_factor_definition_version_is_preserved():
    signature = trigger(definition_version="funding-def-v7")
    payload = signature.to_json()
    funding = [item for item in payload["factors"] if item["factor_id"] == "FUNDING_RATE"][0]
    assert funding["definition_version"] == "funding-def-v7"


def test_unknown_context_field_is_explicit_not_inferred():
    context = ContextSignature.from_market_state(
        {"regime": "BULL"}, as_of=NOW, symbol="BTCUSDT"
    )
    assert context.regime == "BULL"
    assert context.instrument_class == UNKNOWN
    assert "instrument_class" in context.unknown_fields


async def test_same_trigger_different_regime_changes_applicability(v2_db):
    from tests.growth_system_v2.conftest import seed_card

    await seed_card(v2_db, rule_id="card_regime", status="ACTIVE")
    from crypto_trader.learning.growth_experience import AdaptiveCardStore

    card = await AdaptiveCardStore(v2_db.session_factory).get_card("card_regime")
    policy = CardRankingPolicy()
    same = evaluate_hard_applicability(
        card, trigger(), market_context(regime="BULL"), as_of=AS_OF, policy=policy
    )
    other = evaluate_hard_applicability(
        card, trigger(), market_context(regime="RANGE"), as_of=AS_OF, policy=policy
    )
    assert same.allowed is True
    assert other.allowed is False
    assert any(reason.startswith("CONTEXT_MISMATCH:regime") for reason in other.reasons)


async def test_context_unknown_cannot_match_specific_card(v2_db):
    from tests.growth_system_v2.conftest import seed_card

    await seed_card(v2_db, rule_id="card_ctx_unknown", status="ACTIVE")
    from crypto_trader.learning.growth_experience import AdaptiveCardStore

    card = await AdaptiveCardStore(v2_db.session_factory).get_card("card_ctx_unknown")
    unknown_context = ContextSignature.from_market_state(
        {"trend_state": "UP"}, as_of=AS_OF, symbol="BTCUSDT"
    )
    result = evaluate_hard_applicability(
        card, trigger(), unknown_context, as_of=AS_OF, policy=CardRankingPolicy()
    )
    assert result.allowed is False
    assert any(reason.startswith("CONTEXT_UNKNOWN:regime") for reason in result.reasons)
