"""F6/CP/TR closure regressions."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from crypto_trader.learning.growth_card_retrieval import (
    CardDecisionTraceStore,
    render_experience_domains,
)
from crypto_trader.learning.growth_domains import effective_evidence_weight
from crypto_trader.learning.growth_models import GrowthCardDecisionTraceORM, create_growth_schema
from crypto_trader.learning.growth_review_evidence import GrowthReviewEvidence
from crypto_trader.learning.growth_v2_contracts import (
    AdaptiveExperienceCard,
    CardRetrievalResult,
    ContextSignature,
    RetrievedCard,
    TriggerSignature,
)


@pytest.fixture
async def growth_db(database):
    await create_growth_schema(database.engine)
    return database

def test_cp_grouped_domain_presentation():
    cards = [
        {"rule_id": "paper", "version": 1, "source_evidence_domain": "PAPER",
         "domain_weight": 0.75, "effective_weight": 0.3},
        {"rule_id": "bt", "version": 2, "source_evidence_domain": "BACKTEST",
         "domain_weight": 0.4, "effective_weight": 0.2},
    ]
    rendered = render_experience_domains(cards)
    assert "RUNTIME EXPERIENCE" in rendered
    assert "PAPER EXPERIENCE" in rendered
    assert "HISTORICAL BACKTEST RESEARCH" in rendered
    assert "BACKTEST_ONLY" in rendered and "NOT_RUNTIME_VALIDATED" in rendered
    assert "bt" not in rendered.split("HISTORICAL BACKTEST RESEARCH")[0]

def test_unknown_not_zero_in_evidence_envelope():
    evidence = GrowthReviewEvidence(episode_id="ep", mfe="UNKNOWN", mae="UNKNOWN")
    payload = evidence.as_payload()
    assert payload["mfe"] == "UNKNOWN" and payload["mae"] == "UNKNOWN"

def test_domain_weight_caps_backtest_below_live():
    assert effective_evidence_weight(0.99, "BACKTEST") <= 0.40
    assert effective_evidence_weight(0.99, "LIVE") <= 1.0

async def test_trace_selected_evidence_is_typed_and_exact(growth_db):
    now = datetime(2026, 9, 13, tzinfo=UTC)
    card = AdaptiveExperienceCard(
        rule_id="card_t",
        title="t",
        content="x",
        mode="PAPER",
        confidence=Decimal("0.5"),
    )
    result = CardRetrievalResult(
        as_of=now,
        trigger=TriggerSignature.from_factor_states([], as_of=now),
        context=ContextSignature.from_market_state({}, as_of=now, symbol="BTCUSDT"),
        selected=[
            RetrievedCard(
                rule_id="card_t",
                version=1,
                status="ACTIVE",
                score=0.5,
                components={},
                why=[],
                card=card,
            )
        ],
        metrics={"policy_fingerprint": "p1"},
    )
    trace = await CardDecisionTraceStore(growth_db.session_factory).record(
        result, decision_id=None, evidence_package_id=None, account_id="default", mode="PAPER"
    )
    async with growth_db.session_factory() as session:
        row = await session.get(GrowthCardDecisionTraceORM, trace.trace_id)
    assert row.selected_evidence_json[0]["evidence_ref"] == "card:card_t:v1"
    assert row.selected_evidence_json[0]["evidence_domain"] == "PAPER"
    assert row.selected_evidence_json[0]["domain_weight"] == 0.75
