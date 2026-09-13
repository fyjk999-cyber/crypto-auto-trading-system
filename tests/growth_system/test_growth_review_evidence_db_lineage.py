"""A.5.1a-1: real SQLite decision lineage proof."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.learning.growth_review_evidence import GrowthReviewEvidenceLoader
from crypto_trader.persistence.models import LLMDecisionORM, TradeEpisodeORM


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
