from datetime import UTC, datetime, timedelta

from crypto_trader.learning.retrieval import GrowthRetriever, record_version
from crypto_trader.llm_chief.growth_context import (
    apply_context_refs,
    build_growth_context,
    split_context_refs,
)

T = datetime(2026, 9, 16, 0, 0, tzinfo=UTC)


async def _seed(session_factory, available_at):
    await record_version(
        session_factory,
        object_type="REGIME_PATTERN",
        object_id="p1",
        available_at=available_at,
        sample_count=80,
        sample_tier="CANDIDATE",
        memory_speed="PATTERN",
        quality=0.7,
        post_cost_expectancy_bps=6.0,
        contradictions=0,
        payload_json={
            "symbol": "BTCUSDT",
            "regime": "TREND_UP",
            "strategy": "breakout",
            "direction": "LONG",
            "horizon": "1h",
            "setup_signature": "s1",
        },
        source_refs_json={"episodes": ["e1"]},
    )
    await record_version(
        session_factory,
        object_type="GENERALIZED_KNOWLEDGE",
        object_id="g1",
        available_at=available_at,
        sample_count=120,
        sample_tier="VALIDATED_KNOWLEDGE",
        memory_speed="VALIDATED_KNOWLEDGE",
        quality=0.9,
        post_cost_expectancy_bps=8.0,
        payload_json={
            "asset": "BTCUSDT",
            "strategy": "breakout",
            "horizon": "1h",
            "setup_signature": "s1",
            "regime_count": 3,
        },
        source_refs_json={"source_regimes": ["TREND_UP", "RANGE", "TREND_DOWN"]},
    )


async def test_growth_context_uses_retriever_and_typed_refs(database):
    await _seed(database.session_factory, T + timedelta(hours=1))
    retriever = GrowthRetriever(database.session_factory)
    context = await build_growth_context(
        retriever,
        symbol="BTCUSDT",
        regime="TREND_UP",
        strategy="breakout",
        horizon="1h",
        setup_signature="s1",
        as_of_timestamp=T + timedelta(hours=2),
    )
    assert context["strategy"] == "breakout"
    assert context["direction"] == "LONG"  # separate from strategy
    pattern = next(item for item in context["patterns"] if item["id"] == "p1")
    assert pattern["strategy"] == "breakout" and pattern["direction"] == "LONG"
    assert pattern["version"] == 1 and pattern["sample_tier"] == "CANDIDATE"
    assert pattern["retrieval_score"] > 0 and "score_components" in pattern
    assert context["generalized_knowledge"][0]["sample_tier"] == "VALIDATED_KNOWLEDGE"
    assert "pattern:p1:v1" in context["memory_refs"]
    assert "generalized:g1:v1" in context["memory_refs"]


async def test_growth_context_as_of_excludes_future_versions(database):
    await _seed(database.session_factory, T + timedelta(hours=1))
    retriever = GrowthRetriever(database.session_factory)
    context = await build_growth_context(
        retriever, symbol="BTCUSDT", strategy="breakout", as_of_timestamp=T
    )  # before any version became available
    assert context["patterns"] == [] and context["generalized_knowledge"] == []
    assert context["memory_refs"] == []


def test_typed_refs_persist_additively():
    from crypto_trader.persistence.models import LLMDecisionORM

    refs = [
        "pattern:p1:v2",
        "generalized:g1:v1",
        "episode:e1:v3",
        "review:r1:v1",
        "profile:BTCUSDT:v4",
        "compressed:c1:v1",
        "research:news-1",
    ]
    payload = split_context_refs(refs)
    assert "episode:e1:v3" in payload["episode_refs_json"]
    assert "review:r1:v1" in payload["episode_refs_json"]
    assert payload["research_refs_json"] == ["research:news-1"]
    decision = LLMDecisionORM(decision_id="d1")
    apply_context_refs(decision, {"memory_refs": refs})
    apply_context_refs(decision, {"memory_refs": ["pattern:p1:v2"]})
    assert sorted(decision.memory_refs_json) == sorted(refs)  # idempotent
    assert len(decision.episode_refs_json) == 2


async def test_existing_chief_loader_exposes_growth_memory(database):
    from types import SimpleNamespace

    from crypto_trader.llm_chief.context_loader import ChiefContextLoader

    await _seed(database.session_factory, T + timedelta(hours=1))
    loader = ChiefContextLoader(database.session_factory, limit=5)
    context = SimpleNamespace(
        symbol="BTCUSDT", regime="TREND_UP", strategy="breakout", horizon="1h", setup_signature="s1"
    )
    evidence = await loader.load_tool("growth_memory", context)
    assert evidence.features["strategy"] == "breakout"
    assert evidence.features["direction"] == "LONG"  # never direction=row.strategy
    assert evidence.features["patterns"][0]["direction"] == "LONG"
    assert evidence.source_refs[0]["memory_ref"].startswith(("pattern:", "generalized:"))
