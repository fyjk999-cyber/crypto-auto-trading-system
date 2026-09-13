"""Mission B: explicit domains, immutable trace, and pure rendering."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from crypto_trader.learning.growth_card_retrieval import (
    CardDecisionTraceStore,
    CardRankingPolicy,
    ExperienceCardRetriever,
    render_experience_domains,
)
from crypto_trader.learning.growth_domains import DOMAIN_WEIGHT_CAPS
from crypto_trader.learning.growth_models import GrowthCardDecisionTraceORM
from crypto_trader.persistence.models import AICompressedExperienceORM
from tests.growth_system_v2.conftest import AS_OF, market_context, seed_card, trigger


async def _set_confidence(v2_db, rule_id: str, confidence: str) -> None:
    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == rule_id
                )
            )
        ).scalar_one()
        row.confidence = Decimal(confidence)
        await session.commit()


async def test_explicit_backtest_visibility_keeps_domains_separate(v2_db):
    await seed_card(v2_db, rule_id="paper-explicit", mode="PAPER")
    await seed_card(v2_db, rule_id="backtest-explicit", mode="BACKTEST")
    await seed_card(v2_db, rule_id="live-hidden", mode="LIVE")
    retriever = ExperienceCardRetriever(
        v2_db.session_factory,
        policy=CardRankingPolicy(
            top_k=3,
            allowed_evidence_domains=("PAPER", "BACKTEST"),
        ),
    )

    result = await retriever.retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
        account_id="default",
        mode="PAPER",
    )

    selected = {item.rule_id: item.card.mode for item in result.selected}
    assert selected == {
        "backtest-explicit": "BACKTEST",
        "paper-explicit": "PAPER",
    }
    assert "live-hidden" not in selected


async def test_explicit_backtest_visibility_preserves_account_isolation(v2_db):
    await seed_card(
        v2_db,
        rule_id="backtest-acct-a",
        mode="BACKTEST",
        account_id="acct-a",
    )
    await seed_card(
        v2_db,
        rule_id="backtest-acct-b",
        mode="BACKTEST",
        account_id="acct-b",
    )
    retriever = ExperienceCardRetriever(
        v2_db.session_factory,
        policy=CardRankingPolicy(
            allowed_evidence_domains=("PAPER", "BACKTEST")
        ),
    )

    result = await retriever.retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
        account_id="acct-a",
        mode="PAPER",
    )

    assert [item.rule_id for item in result.selected] == ["backtest-acct-a"]


async def test_selected_evidence_trace_is_exact_and_reconstructable(v2_db):
    await seed_card(v2_db, rule_id="paper-trace", mode="PAPER")
    await _set_confidence(v2_db, "paper-trace", "0.8")
    policy = CardRankingPolicy()
    result = await ExperienceCardRetriever(
        v2_db.session_factory,
        policy=policy,
    ).retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
        account_id="default",
        mode="PAPER",
    )
    trace = await CardDecisionTraceStore(v2_db.session_factory).record(
        result,
        decision_id="decision-mission-b",
        evidence_package_id="package-mission-b",
    )

    snapshot = trace.selected_evidence_json[0]
    assert snapshot == {
        "schema_version": 1,
        "evidence_ref": "card:paper-trace:v1",
        "card_id": "paper-trace",
        "card_version": 1,
        "evidence_domain": "PAPER",
        "runtime_validated": True,
        "internal_confidence": 0.8,
        "domain_weight": 0.75,
        "effective_weight": 0.6,
        "ranking_score": result.selected[0].score,
        "policy_fingerprint": policy.fingerprint(),
    }
    async with v2_db.session_factory() as session:
        stored = await session.get(GrowthCardDecisionTraceORM, trace.trace_id)
    assert stored.selected_evidence_json == [snapshot]


def test_policy_fingerprint_binds_domain_caps(monkeypatch):
    before = CardRankingPolicy().fingerprint()
    monkeypatch.setitem(DOMAIN_WEIGHT_CAPS, "BACKTEST", 0.39)
    after = CardRankingPolicy().fingerprint()
    assert after != before


def test_domain_renderer_is_pure_and_deterministic():
    cards = [
        {
            "evidence_ref": "card:z-backtest:v2",
            "rule_id": "z-backtest",
            "version": 2,
            "source_evidence_domain": "BACKTEST",
            "runtime_validated": False,
            "internal_confidence": 1.0,
            "domain_weight": 0.4,
            "effective_weight": 0.4,
            "ranking_score": 0.9,
        },
        {
            "evidence_ref": "card:a-paper:v1",
            "rule_id": "a-paper",
            "version": 1,
            "source_evidence_domain": "PAPER",
            "runtime_validated": True,
            "internal_confidence": 0.7,
            "domain_weight": 0.75,
            "effective_weight": 0.525,
            "ranking_score": 0.8,
        },
    ]
    original = [dict(item) for item in cards]

    rendered = render_experience_domains(list(reversed(cards)))

    assert cards == original
    assert "CURRENT_RUNTIME_EXPERIENCE" in rendered
    assert "HISTORICAL_BACKTEST_EVIDENCE" in rendered
    assert "NOT_RUNTIME_VALIDATED" in rendered
    assert "card:a-paper:v1" in rendered
    assert "card:z-backtest:v2" in rendered
    assert rendered == render_experience_domains(cards)

