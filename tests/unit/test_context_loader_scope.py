from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.context_loader import ChiefContextLoader
from crypto_trader.persistence.models import ResearchReportORM, TradeEpisodeORM


def _context(as_of: datetime) -> ChiefTraderContext:
    return ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={"source": "OKX_PUBLIC"},
        regime="RANGE",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        prepared_at=as_of.isoformat(),
    )


def _episode(episode_id: str, symbol: str, closed_at: datetime) -> TradeEpisodeORM:
    return TradeEpisodeORM(
        episode_id=episode_id,
        trade_plan_id=f"plan-{episode_id}",
        symbol=symbol,
        direction="LONG",
        entry_decision_id=f"entry-{episode_id}",
        exit_decision_id=f"exit-{episode_id}",
        position_decision_ids_json=[],
        risk_decision_ids_json=[],
        order_ids_json=[],
        fill_ids_json=[],
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        opened_quantity=Decimal("1"),
        closed_quantity=Decimal("1"),
        leverage=Decimal("1"),
        fees=Decimal("0"),
        funding_pnl=Decimal("0"),
        gross_pnl=Decimal("1"),
        net_pnl=Decimal("1"),
        holding_time_seconds=60,
        entry_market_regime="RANGE",
        terminal_reason="EXIT",
        factual=True,
        review_status="REVIEWED",
        opened_at=closed_at - timedelta(minutes=1),
        closed_at=closed_at,
        created_at=closed_at,
    )


async def test_context_tools_filter_time_symbol_and_research_scope(database):
    as_of = datetime(2026, 1, 2, tzinfo=UTC)
    before = as_of - timedelta(minutes=2)
    after = as_of + timedelta(minutes=2)

    async with database.session_factory() as session:
        session.add_all(
            [
                ResearchReportORM(
                    research_id="global",
                    scope_type="GLOBAL",
                    summary="global",
                    conclusion="ok",
                    confidence=0.8,
                    created_at=before,
                ),
                ResearchReportORM(
                    research_id="btc",
                    scope_type="SYMBOL",
                    symbol="BTCUSDT",
                    summary="btc",
                    conclusion="ok",
                    confidence=0.8,
                    created_at=before,
                ),
                ResearchReportORM(
                    research_id="eth",
                    scope_type="SYMBOL",
                    symbol="ETHUSDT",
                    summary="eth",
                    conclusion="wrong symbol",
                    confidence=0.8,
                    created_at=before,
                ),
                ResearchReportORM(
                    research_id="range",
                    scope_type="REGIME",
                    regime="RANGE",
                    summary="range",
                    conclusion="ok",
                    confidence=0.8,
                    created_at=before,
                ),
                ResearchReportORM(
                    research_id="trend",
                    scope_type="REGIME",
                    regime="TREND",
                    summary="trend",
                    conclusion="wrong regime",
                    confidence=0.8,
                    created_at=before,
                ),
                ResearchReportORM(
                    research_id="unscoped",
                    summary="legacy-style",
                    conclusion="must not be used",
                    confidence=0.8,
                    created_at=before,
                ),
                ResearchReportORM(
                    research_id="future",
                    scope_type="GLOBAL",
                    summary="future",
                    conclusion="future",
                    confidence=0.8,
                    created_at=after,
                ),
                _episode("btc-past", "BTCUSDT", before),
                _episode("eth-past", "ETHUSDT", before),
                _episode("btc-future", "BTCUSDT", after),
            ]
        )
        await session.commit()

    loader = ChiefContextLoader(database.session_factory, limit=20)
    context = _context(as_of)

    research = await loader.load_tool("research_retrieval", context, as_of=as_of)
    research_ids = {
        row["research_id"] for row in research.features["research"]
    }
    assert research_ids == {"global", "btc", "range"}

    episodes = await loader.load_tool("episode_search", context, as_of=as_of)
    episode_ids = {
        row["episode_id"] for row in episodes.features["episodes"]
    }
    assert episode_ids == {"btc-past"}
