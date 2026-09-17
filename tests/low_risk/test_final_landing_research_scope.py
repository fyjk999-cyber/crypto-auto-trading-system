"""Research applicability is scoped and fail-closed on legacy rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.context_loader import ChiefContextLoader
from crypto_trader.persistence.models import ResearchReportORM

AS_OF = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _ctx() -> ChiefTraderContext:
    return ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={"price": "100"},
        regime="TREND_UP",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        prepared_at=AS_OF.isoformat(),
    )


async def test_research_scope_is_asof_safe_and_legacy_unscoped_is_excluded(database):
    async with database.session_factory() as session:
        session.add_all(
            [
                ResearchReportORM(
                    research_id="global",
                    scope_type="GLOBAL",
                    summary="global",
                    conclusion="ok",
                    confidence=0.8,
                    created_at=AS_OF - timedelta(minutes=10),
                ),
                ResearchReportORM(
                    research_id="symbol-match",
                    scope_type="SYMBOL",
                    symbol="BTCUSDT",
                    summary="btc",
                    conclusion="ok",
                    confidence=0.8,
                    created_at=AS_OF - timedelta(minutes=9),
                ),
                ResearchReportORM(
                    research_id="symbol-other",
                    scope_type="SYMBOL",
                    symbol="ETHUSDT",
                    summary="eth",
                    conclusion="must not leak",
                    confidence=0.8,
                    created_at=AS_OF - timedelta(minutes=8),
                ),
                ResearchReportORM(
                    research_id="regime-match",
                    scope_type="REGIME",
                    regime="TREND_UP",
                    summary="regime",
                    conclusion="ok",
                    confidence=0.8,
                    created_at=AS_OF - timedelta(minutes=7),
                ),
                ResearchReportORM(
                    research_id="legacy-unscoped",
                    scope_type="UNSCOPED",
                    summary="legacy",
                    conclusion="must not be used",
                    confidence=0.8,
                    created_at=AS_OF - timedelta(minutes=6),
                ),
                ResearchReportORM(
                    research_id="future",
                    scope_type="GLOBAL",
                    summary="future",
                    conclusion="must not leak",
                    confidence=0.8,
                    created_at=AS_OF + timedelta(minutes=1),
                ),
            ]
        )
        await session.commit()

    enriched = await ChiefContextLoader(database.session_factory, limit=10).enrich(_ctx())
    research_ids = {
        item["research_id"]
        for item in enriched.knowledge
        if item.get("kind") == "RESEARCH"
    }
    assert research_ids == {"global", "symbol-match", "regime-match"}


async def test_legacy_unscoped_research_evidence_returns_empty(database):
    async with database.session_factory() as session:
        session.add(
            ResearchReportORM(
                research_id="legacy-only",
                scope_type="UNSCOPED",
                summary="legacy",
                conclusion="must not be used",
                confidence=0.8,
                created_at=AS_OF - timedelta(hours=1),
            )
        )
        await session.commit()

    loader = ChiefContextLoader(database.session_factory, limit=10)
    finding, refs, _timestamp = await loader._research_evidence(_ctx())
    assert finding == {}
    assert refs == []
