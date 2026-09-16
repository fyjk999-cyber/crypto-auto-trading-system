from datetime import UTC, datetime, timedelta

from crypto_trader.learning.retrieval import GrowthRetriever, record_version

T = datetime(2026, 9, 16, 0, 0, tzinfo=UTC)


async def _seed(session_factory):
    base = dict(
        sample_count=60,
        sample_tier="CANDIDATE",
        memory_speed="PATTERN",
        quality=0.6,
        post_cost_expectancy_bps=5.0,
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
        object_type="REGIME_PATTERN",
        object_id="BTCUSDT-TREND_UP-s1",
        available_at=T,
        **base,
    )
    promoted = dict(
        base,
        sample_count=120,
        sample_tier="VALIDATED_KNOWLEDGE",
        quality=0.9,
        post_cost_expectancy_bps=8.0,
    )
    await record_version(
        session_factory,
        object_type="REGIME_PATTERN",
        object_id="BTCUSDT-TREND_UP-s1",
        available_at=T + timedelta(hours=1),
        **promoted,
    )


async def test_as_of_v1_does_not_leak_future_promotion(database):
    await _seed(database.session_factory)
    retriever = GrowthRetriever(database.session_factory)
    early = await retriever.search(
        symbol="BTCUSDT",
        regime="TREND_UP",
        strategy="breakout",
        horizon="1h",
        setup_signature="s1",
        as_of_timestamp=T,
    )
    assert early["result_count"] == 1
    assert early["results"][0]["version"] == 1
    assert early["results"][0]["sample_tier"] == "CANDIDATE"
    late = await retriever.search(
        symbol="BTCUSDT",
        regime="TREND_UP",
        strategy="breakout",
        horizon="1h",
        setup_signature="s1",
        as_of_timestamp=T + timedelta(hours=2),
    )
    assert late["results"][0]["version"] == 2
    assert late["results"][0]["sample_tier"] == "VALIDATED_KNOWLEDGE"


async def test_zero_hit_and_strategy_direction_separated(database):
    await _seed(database.session_factory)
    retriever = GrowthRetriever(database.session_factory)
    empty = await retriever.search(symbol="SOLUSDT", as_of_timestamp=T + timedelta(hours=2))
    assert empty["result_count"] == 0
    hit = await retriever.search(symbol="BTCUSDT", as_of_timestamp=T)
    item = hit["results"][0]
    assert item["strategy"] == "breakout" and item["direction"] == "LONG"
    assert item["score_components"]["post_cost_expectancy"] == 5.0


async def test_cache_hit_invalidation_and_as_of_safety(database):
    await _seed(database.session_factory)
    retriever = GrowthRetriever(database.session_factory)
    await retriever.search(symbol="BTCUSDT", as_of_timestamp=T)
    self_metrics = retriever.cache_metrics()
    assert self_metrics["misses"] == 1 and self_metrics["hits"] == 0
    await retriever.search(symbol="BTCUSDT", as_of_timestamp=T)
    assert retriever.cache_metrics()["hits"] == 1
    retriever.invalidate("promotion")
    await retriever.search(symbol="BTCUSDT", as_of_timestamp=T)
    metrics = retriever.cache_metrics()
    assert metrics["invalidations"] == 1 and metrics["hits"] == 1
