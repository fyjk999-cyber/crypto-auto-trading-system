"""P0-C: research/memory/pattern retrieval must honor factual scope."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.context_loader import ChiefContextLoader
from crypto_trader.persistence.models import (
    AICompressedExperienceORM,
    AIMarketPatternORM,
    AITradeReviewORM,
    ResearchReportORM,
    TradeEpisodeORM,
)

AS_OF = datetime(2026, 1, 2, tzinfo=UTC)
SYMBOL_SCOPE = {"scope": "SYMBOL_REGIME", "symbols": ["BTCUSDT"], "regimes": ["TREND"]}
WRONG_SYMBOL_SCOPE = {
    "scope": "SYMBOL_REGIME",
    "symbols": ["ETHUSDT"],
    "regimes": ["TREND"],
}
GLOBAL_SCOPE = {"scope": "GLOBAL"}


def _episode(episode_id: str, symbol: str, scope) -> TradeEpisodeORM:
    stamp = AS_OF - timedelta(hours=1)
    return TradeEpisodeORM(
        episode_id=episode_id,
        trade_plan_id=f"plan_{episode_id}",
        symbol=symbol,
        direction="LONG",
        entry_decision_id=f"entry_{episode_id}",
        exit_decision_id=f"exit_{episode_id}",
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        opened_quantity=Decimal("1"),
        closed_quantity=Decimal("1"),
        leverage=Decimal("1"),
        fees=Decimal("0"),
        funding_pnl=Decimal("0"),
        gross_pnl=Decimal("1"),
        net_pnl=Decimal("1"),
        holding_time_seconds=60.0,
        entry_market_regime="TREND",
        terminal_reason="TEST",
        factual=True,
        review_status="REVIEWED",
        applicability_scope_json=scope,
        opened_at=stamp,
        closed_at=stamp,
        created_at=stamp,
    )


async def test_context_loader_filters_symbol_scope_future_and_missing_scope(database):
    future = AS_OF + timedelta(days=1)
    async with database.session_factory() as session:
        session.add_all(
            [
                _episode("keep-episode", "BTCUSDT", SYMBOL_SCOPE),
                _episode("wrong-symbol-episode", "ETHUSDT", WRONG_SYMBOL_SCOPE),
                _episode("missing-scope-episode", "BTCUSDT", None),
                _episode("global-episode", "BTCUSDT", GLOBAL_SCOPE),
                ResearchReportORM(
                    research_id="keep-research",
                    symbol="BTCUSDT",
                    summary="btc trend",
                    conclusion="long",
                    confidence=0.8,
                    applicability_scope_json=SYMBOL_SCOPE,
                    created_at=AS_OF - timedelta(hours=1),
                ),
                ResearchReportORM(
                    research_id="wrong-symbol-research",
                    symbol="ETHUSDT",
                    summary="eth trend",
                    conclusion="long",
                    confidence=0.8,
                    applicability_scope_json=WRONG_SYMBOL_SCOPE,
                    created_at=AS_OF - timedelta(hours=1),
                ),
                ResearchReportORM(
                    research_id="future-research",
                    symbol="BTCUSDT",
                    summary="future",
                    conclusion="long",
                    confidence=0.8,
                    applicability_scope_json=SYMBOL_SCOPE,
                    created_at=future,
                ),
                ResearchReportORM(
                    research_id="missing-scope-research",
                    symbol="BTCUSDT",
                    summary="missing",
                    conclusion="long",
                    confidence=0.8,
                    applicability_scope_json=None,
                    created_at=AS_OF - timedelta(hours=1),
                ),
                AIMarketPatternORM(
                    pattern_id="keep-pattern",
                    symbol="BTCUSDT",
                    regime="TREND",
                    strategy="trend",
                    sample_count=20,
                    applicability_scope_json=SYMBOL_SCOPE,
                    created_at=AS_OF - timedelta(hours=1),
                ),
                AIMarketPatternORM(
                    pattern_id="missing-scope-pattern",
                    symbol="BTCUSDT",
                    regime="TREND",
                    strategy="trend",
                    sample_count=20,
                    applicability_scope_json=None,
                    created_at=AS_OF - timedelta(hours=1),
                ),
                AICompressedExperienceORM(
                    rule_id="keep-rule",
                    symbol="BTCUSDT",
                    title="btc rule",
                    content="content",
                    source_episode_count=3,
                    applicability_scope_json=SYMBOL_SCOPE,
                    created_at=AS_OF - timedelta(hours=1),
                ),
                AICompressedExperienceORM(
                    rule_id="missing-scope-rule",
                    symbol="BTCUSDT",
                    title="missing",
                    content="content",
                    source_episode_count=3,
                    applicability_scope_json=None,
                    created_at=AS_OF - timedelta(hours=1),
                ),
            ]
        )
        await session.commit()

    context = ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={},
        regime="TREND",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        prepared_at=AS_OF.isoformat(),
    )
    enriched = await ChiefContextLoader(database.session_factory, limit=10).enrich(
        context
    )
    assert {row["episode_id"] for row in enriched.similar_episodes} == {
        "keep-episode",
        "global-episode",
    }
    assert {row["research_id"] for row in enriched.knowledge if row["kind"] == "RESEARCH"} == {
        "keep-research"
    }
    patterns = {
        row["pattern_id"]
        for row in enriched.knowledge
        if row["kind"] == "FACTUAL_PATTERN"
    }
    assert patterns == {"keep-pattern"}
    assert {row["rule_id"] for row in enriched.compressed_experience} == {"keep-rule"}


async def test_loader_tool_memory_and_research_apply_same_scope_rules(database):
    loader = ChiefContextLoader(database.session_factory, limit=10)
    async with database.session_factory() as session:
        session.add(
            AICompressedExperienceORM(
                rule_id="tool-keep-rule",
                symbol="BTCUSDT",
                title="btc rule",
                content="content",
                source_episode_count=3,
                applicability_scope_json=SYMBOL_SCOPE,
                created_at=AS_OF - timedelta(hours=1),
            )
        )
        await session.commit()
    context = ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={},
        regime="TREND",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        prepared_at=AS_OF.isoformat(),
    )
    evidence = await loader.load_tool("memory_search", context, as_of=AS_OF)
    assert evidence.data_quality == "FACTUAL_REVIEWED"
    evidence = await loader.load_tool("research_retrieval", context, as_of=AS_OF)
    assert evidence.data_quality == "NO_MATCHES"
    evidence = await loader.load_tool("factor_intelligence", context, as_of=AS_OF)
    assert evidence.data_quality == "NO_MATCHES"


async def test_memory_reviews_inherit_episode_scope_and_reviewed_boundary(database):
    future = AS_OF + timedelta(days=1)
    episodes = [
        _episode("review-keep", "BTCUSDT", SYMBOL_SCOPE),
        _episode("review-wrong-regime", "BTCUSDT", {
            "scope": "SYMBOL_REGIME",
            "symbols": ["BTCUSDT"],
            "regimes": ["RANGE"],
        }),
        _episode("review-missing-scope", "BTCUSDT", None),
        _episode("review-global", "BTCUSDT", GLOBAL_SCOPE),
    ]
    future_episode = _episode("review-future", "BTCUSDT", SYMBOL_SCOPE)
    future_episode.closed_at = future
    future_episode.created_at = future
    episodes.append(future_episode)
    async with database.session_factory() as session:
        session.add_all(episodes)
        session.add_all(
            [
                AITradeReviewORM(
                    episode_id=episode.episode_id,
                    lessons_json=[f"lesson:{episode.episode_id}"],
                    failure_factors_json=[],
                    created_at=AS_OF - timedelta(minutes=30),
                )
                for episode in episodes
            ]
        )
        await session.commit()

    context = ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={},
        regime="TREND",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        prepared_at=AS_OF.isoformat(),
    )
    loader = ChiefContextLoader(database.session_factory, limit=10)
    enriched = await loader.enrich(context)
    assert {ref.split(":")[-1] for ref in enriched.memory_refs} == {
        "review-keep",
        "review-global",
    }
    evidence = await loader.load_tool("memory_search", context, as_of=AS_OF)
    assert evidence.data_quality == "FACTUAL_REVIEWED"
    review_ids = {row["episode_id"] for row in evidence.features["reviews"]}
    assert review_ids == {"review-keep", "review-global"}
    for row in evidence.features["reviews"]:
        assert row["lessons"] == [f"lesson:{row['episode_id']}"]
