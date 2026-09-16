from sqlalchemy import func, select

from crypto_trader.learning.pattern_profile import (
    COMPRESSION_MIN_SAMPLES,
    GrowthMemoryPipeline,
    resolve_identity,
    strategy_from_plan,
)
from crypto_trader.persistence.models import (
    AICompressedExperienceORM,
    AIMarketPatternORM,
)


def _episode(i, strategy="breakout", net=5.0, contradiction=False, direction="LONG"):
    return {
        "episode_id": f"e{i}",
        "symbol": "BTCUSDT",
        "regime": "TREND_UP",
        "strategy": strategy,
        "horizon": "15m",
        "setup_signature": "s1",
        "direction": direction,
        "post_cost_net_bps": net,
        "win": net > 0,
        "mfe_bps": 20.0,
        "mae_bps": -5.0,
        "contradiction": contradiction,
    }


def test_direction_is_not_strategy_and_identity_is_stable():
    assert strategy_from_plan(None) == "UNKNOWN"
    unknown = resolve_identity({"symbol": "BTCUSDT", "regime": "R", "direction": "LONG"})
    assert unknown.strategy == "UNKNOWN"
    assert unknown.direction if hasattr(unknown, "direction") else True
    assert (
        unknown.key()
        == resolve_identity({"symbol": "BTCUSDT", "regime": "R", "direction": "LONG"}).key()
    )
    breakout = resolve_identity(_episode(1))
    reversion = resolve_identity(_episode(1, strategy="mean_reversion"))
    assert breakout.key() != reversion.key()


async def test_unreviewed_episode_cannot_update_profile_or_pattern(database):
    pipeline = GrowthMemoryPipeline(database.session_factory)
    result = await pipeline.update_from_episode(_episode(1), reviewed=False)
    assert result["status"] == "SKIPPED_UNREVIEWED"
    async with database.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(AIMarketPatternORM)) == 0


async def test_reviewed_episode_updates_pattern_and_profile(database):
    pipeline = GrowthMemoryPipeline(database.session_factory)
    first = await pipeline.update_from_episode(_episode(1), reviewed=True)
    second = await pipeline.update_from_episode(_episode(2), reviewed=True)
    assert first["status"] == "UPDATED" and second["sample_count"] == 2
    async with database.session_factory() as session:
        pattern = (await session.execute(select(AIMarketPatternORM))).scalars().one()
        assert pattern.strategy == "BREAKOUT" and pattern.direction == "LONG"
        assert pattern.sample_count == 2 and pattern.win_rate > 0
    async with database.session_factory() as session:
        from crypto_trader.persistence.models import AICoinProfileORM

        profile = (await session.execute(select(AICoinProfileORM))).scalars().one()
        assert profile.sample_count == 2 and profile.symbol == "BTCUSDT"


async def test_contradiction_demotes_without_erasing_history(database):
    pipeline = GrowthMemoryPipeline(database.session_factory)
    for i in range(3):
        await pipeline.update_from_episode(_episode(i), reviewed=True)
    result = await pipeline.update_from_episode(_episode(9, contradiction=True), reviewed=True)
    async with database.session_factory() as session:
        pattern = (await session.execute(select(AIMarketPatternORM))).scalars().one()
    assert pattern.sample_count == 4  # history preserved
    assert pattern.contradiction_count == 1
    assert result["sample_tier"] == "PROVISIONAL"


async def test_compression_requires_supported_pattern_and_preserves_provenance(database):
    pipeline = GrowthMemoryPipeline(database.session_factory)
    await pipeline.update_from_episode(_episode(1), reviewed=True)
    early = await pipeline.compress("nope")
    assert early["status"] == "NOT_ELIGIBLE"
    for i in range(1, COMPRESSION_MIN_SAMPLES):
        result = await pipeline.update_from_episode(_episode(i), reviewed=True)
    key = result["pattern_key"]
    assert result["sample_tier"] == "CANDIDATE"
    created = await pipeline.compress(key)
    assert created["status"] == "CREATED" and created["provenance"] == [key]
    async with database.session_factory() as session:
        row = (await session.execute(select(AICompressedExperienceORM))).scalars().one()
    assert row.source_pattern_ids_json == [key]
    assert row.source_episode_count == COMPRESSION_MIN_SAMPLES
    assert row.sample_tier == "CANDIDATE"
    assert "UNCERTAINTY" in row.content and "not core law" in row.content
    assert row.policy_version == "memory-policy-v2"
    again = await pipeline.compress(key)
    assert again["status"] == "ALREADY_COMPRESSED"
    content_len = len(row.content)
    async with database.session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(AICompressedExperienceORM))
    assert count == 1 and content_len > 0


async def test_pipeline_writes_immutable_versions_for_as_of(database):
    import asyncio
    from datetime import UTC, datetime

    from crypto_trader.learning.retrieval import GrowthRetriever

    pipeline = GrowthMemoryPipeline(database.session_factory)
    await pipeline.update_from_episode(_episode(1), reviewed=True)
    checkpoint = datetime.now(UTC)
    await asyncio.sleep(0.02)
    second = await pipeline.update_from_episode(_episode(2), reviewed=True)
    retriever = GrowthRetriever(database.session_factory)
    early = await retriever.search(
        symbol="BTCUSDT",
        regime="TREND_UP",
        strategy="breakout",
        horizon="15m",
        setup_signature="s1",
        as_of_timestamp=checkpoint,
    )
    assert early["result_count"] >= 1
    assert all(item["version"] == 1 for item in early["results"])
    assert second["sample_count"] == 2
    async with database.session_factory() as session:
        from crypto_trader.persistence.models import GrowthMemoryVersionORM

        versions = (
            (
                await session.execute(
                    select(GrowthMemoryVersionORM).where(
                        GrowthMemoryVersionORM.object_type == "REGIME_PATTERN"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert sorted(v.version for v in versions) == [1, 2]
