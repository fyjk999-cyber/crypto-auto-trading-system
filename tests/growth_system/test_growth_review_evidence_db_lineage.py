"""A.5.1a-1: real SQLite decision lineage proof."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.learning.growth_review_evidence import GrowthReviewEvidenceLoader
from crypto_trader.persistence.models import (
    LLMDecisionORM,
    RiskDecisionORM,
    TradeEpisodeORM,
)


def _decision(decision_id, action, thesis, created_at):
    return LLMDecisionORM(
        decision_id=decision_id, run_id="run", symbol="BTCUSDT",
        position_state="FLAT", action=action, model_provider="deepseek",
        model="db-test", model_version="v1", prompt_version="p1",
        market_regime="TRENDING", thesis=thesis, created_at=created_at,
    )


async def test_decision_db_lineage_target_excludes_distractors(database):
    assert "crypto_test.db" in str(database.engine.url)
    opened = datetime(2026, 9, 9, 10, tzinfo=UTC)
    closed = opened + timedelta(hours=1)
    episode = TradeEpisodeORM(
        episode_id="ep-db-decision-target", trade_plan_id="plan-db-decision-target",
        symbol="BTCUSDT", direction="LONG", entry_decision_id="decision-target",
        exit_decision_id=None, position_decision_ids_json=[],
        risk_decision_ids_json=[], order_ids_json=[], fill_ids_json=[],
        entry_price=Decimal("100"), exit_price=Decimal("110"),
        opened_quantity=Decimal("1"), closed_quantity=Decimal("1"),
        leverage=Decimal("2"), fees=Decimal("1"), funding_pnl=Decimal("0"),
        gross_pnl=Decimal("10"), net_pnl=Decimal("9"),
        holding_time_seconds=3600.0, entry_market_regime="TRENDING",
        terminal_reason="TAKE_PROFIT", factual=True, review_status="PENDING",
        opened_at=opened, closed_at=closed,
    )
    async with database.session_factory() as session:
        target = _decision(
            "decision-target", "OPEN_LONG", "TARGET_DECISION_THESIS",
            closed - timedelta(minutes=5),
        )
        newer = _decision(
            "decision-distractor-newer", "OPEN_SHORT",
            "DISTRACTOR_NEWER_THESIS", closed + timedelta(minutes=5),
        )
        context = _decision(
            "decision-distractor-context", "HOLD",
            "DISTRACTOR_CONTEXT_THESIS", closed - timedelta(minutes=10),
        )
        session.add_all([episode, target, newer, context])
        await session.commit()
    async with database.session_factory() as session:
        reloaded = (
            await session.execute(
                select(TradeEpisodeORM).where(
                    TradeEpisodeORM.episode_id == "ep-db-decision-target"
                )
            )
        ).scalar_one()
    review_now = closed + timedelta(days=1)
    evidence = await GrowthReviewEvidenceLoader(database.session_factory).load(
        reloaded, account_id="default", mode="PAPER",
        evidence_domain="PAPER", now=review_now,
    )
    assert isinstance(reloaded, TradeEpisodeORM)
    assert evidence.decision_availability == "AVAILABLE"
    assert evidence.decision_id == "decision-target"
    assert evidence.decision_action == "OPEN_LONG"
    assert evidence.decision_thesis == "TARGET_DECISION_THESIS"
    assert evidence.decision_conviction == "UNKNOWN"
    assert "DISTRACTOR" not in evidence.decision_thesis
    assert evidence.risk_availability == "UNAVAILABLE"
    assert evidence.execution_availability == "UNAVAILABLE"
    assert evidence.risk_decision_ids == [] and evidence.order_ids == []
    assert evidence.fill_ids == [] and evidence.weighted_entry_price == "UNKNOWN"
    assert evidence.exit_availability == "AVAILABLE"
    assert evidence.exit_reason == "TAKE_PROFIT"
    assert evidence.known_at == review_now.isoformat()
    assert evidence.reviewed_at == review_now.isoformat()
    evidence.validate_availability()



def _risk_episode(eid, risk_ids):
    closed = datetime(2026, 9, 9, 11, tzinfo=UTC)
    return TradeEpisodeORM(
        episode_id=eid, trade_plan_id=f"plan-{eid}", symbol="BTCUSDT",
        direction="LONG", entry_decision_id=f"dec-{eid}", exit_decision_id=None,
        position_decision_ids_json=[], risk_decision_ids_json=risk_ids,
        order_ids_json=[], fill_ids_json=[], entry_price=Decimal("100"),
        exit_price=Decimal("101"), opened_quantity=Decimal("1"),
        closed_quantity=Decimal("1"), leverage=Decimal("1"),
        fees=Decimal("0"), funding_pnl=Decimal("0"), gross_pnl=Decimal("1"),
        net_pnl=Decimal("1"), holding_time_seconds=60.0,
        entry_market_regime="TRENDING", terminal_reason="EXIT", factual=True,
        review_status="PENDING", opened_at=closed - timedelta(hours=1),
        closed_at=closed,
    )


def _risk(rid, reason):
    return RiskDecisionORM(
        risk_decision_id=rid, client_order_id=f"client-{rid}", symbol="BTCUSDT",
        side="BUY", decision="APPROVED", reason=reason,
        checks_json={"source": rid}, run_id="run-risk-target",
        timestamp=datetime(2026, 9, 9, 10, 30, tzinfo=UTC),
    )


async def test_risk_db_lineage_order_complete_and_distractor(database):
    ep = _risk_episode("ep-db-risk-target", ["risk-target-2", "risk-target-1"])
    decision = _decision(
        "dec-ep-db-risk-target", "OPEN_LONG", "D",
        datetime(2026, 9, 9, 10, tzinfo=UTC),
    )
    async with database.session_factory() as session:
        session.add_all([
            ep, decision,
            _risk("risk-target-1", "SECOND_FACTUAL_RISK"),
            _risk("risk-target-2", "PRIMARY_FACTUAL_RISK"),
            _risk("risk-distractor", "DISTRACTOR_REASON"),
        ])
        await session.commit()
    async with database.session_factory() as session:
        reloaded = (await session.execute(select(TradeEpisodeORM).where(
            TradeEpisodeORM.episode_id == "ep-db-risk-target"))).scalar_one()
    evidence = await GrowthReviewEvidenceLoader(database.session_factory).load(
        reloaded, account_id="default", mode="PAPER",
        now=datetime(2026, 9, 10, 11, tzinfo=UTC),
    )
    assert evidence.risk_availability == "AVAILABLE"
    assert evidence.risk_decision_ids == ["risk-target-2", "risk-target-1"]
    assert evidence.risk_decision_id == "risk-target-2"
    assert evidence.risk_result == "APPROVED"
    assert evidence.risk_reason_codes == ["PRIMARY_FACTUAL_RISK"]
    assert "risk-distractor" not in evidence.risk_decision_ids
    assert evidence.execution_availability == "UNAVAILABLE"
    evidence.validate_availability()


async def test_risk_db_partial_and_duplicate_fail_closed(database):
    partial = _risk_episode("ep-db-risk-partial", ["risk-present", "risk-missing"])
    duplicate = _risk_episode("ep-db-risk-duplicate", ["risk-dup", "risk-dup"])
    async with database.session_factory() as session:
        session.add_all([
            partial, duplicate, _risk("risk-present", "PRESENT"), _risk("risk-dup", "DUP"),
        ])
        await session.commit()
    loader = GrowthReviewEvidenceLoader(database.session_factory)
    async with database.session_factory() as session:
        p = (await session.execute(select(TradeEpisodeORM).where(
            TradeEpisodeORM.episode_id == "ep-db-risk-partial"))).scalar_one()
        d = (await session.execute(select(TradeEpisodeORM).where(
            TradeEpisodeORM.episode_id == "ep-db-risk-duplicate"))).scalar_one()
    pe = await loader.load(p, account_id="default", mode="PAPER")
    de = await loader.load(d, account_id="default", mode="PAPER")
    for ev in (pe, de):
        assert ev.risk_availability == "UNAVAILABLE"
        assert ev.risk_decision_ids == [] and ev.risk_decision_id is None
        assert ev.risk_result == "UNKNOWN"
        ev.validate_availability()
    assert "RISK" in pe.missing_evidence
