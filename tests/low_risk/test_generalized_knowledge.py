from sqlalchemy import select

from crypto_trader.learning.pattern_profile import GrowthMemoryPipeline
from crypto_trader.persistence.models import AIMarketPatternORM, GeneralizedKnowledgeORM


def _pattern(regime, samples, expectancy=5.0, contradictions=0):
    key = f"gk-{regime}"
    import hashlib

    pattern_id = hashlib.sha1(key.encode()).hexdigest()[:16]  # noqa: S324
    return AIMarketPatternORM(
        pattern_id=pattern_id,
        pattern_key=pattern_id,
        regime=regime,
        strategy="BREAKOUT",
        asset="BTCUSDT",
        horizon="1h",
        setup_signature="s1",
        sample_count=samples,
        wins=samples,
        post_cost_expectancy_bps=expectancy,
        contradiction_count=contradictions,
    )


async def _seed(database, rows):
    async with database.session_factory() as session:
        for row in rows:
            session.add(row)
        await session.commit()


async def _evaluate(database):
    return await GrowthMemoryPipeline(database.session_factory).evaluate_generalized(
        asset="BTCUSDT", strategy="BREAKOUT", horizon="1h", setup_signature="s1"
    )


async def test_three_regimes_100plus_positive_validates(database):
    await _seed(
        database, [_pattern("TREND_UP", 40), _pattern("RANGE", 40), _pattern("TREND_DOWN", 40)]
    )
    result = await _evaluate(database)
    assert result["status"] == "VALIDATED"
    assert result["sample_count"] == 120 and result["regime_count"] == 3
    assert result["sample_tier"] == "VALIDATED_KNOWLEDGE"
    async with database.session_factory() as session:
        row = (await session.execute(select(GeneralizedKnowledgeORM))).scalars().one()
    assert row.source_regimes_json == ["RANGE", "TREND_DOWN", "TREND_UP"]
    assert len(row.source_pattern_ids_json) == 3


async def test_single_regime_high_samples_cannot_validate(database):
    await _seed(database, [_pattern("TREND_UP", 500)])
    result = await _evaluate(database)
    assert result["status"] == "NOT_VALIDATED"
    assert "insufficient_regimes" in result["reasons"]


async def test_three_regimes_under_100_samples_cannot_validate(database):
    await _seed(
        database, [_pattern("TREND_UP", 20), _pattern("RANGE", 20), _pattern("TREND_DOWN", 20)]
    )
    result = await _evaluate(database)
    assert result["status"] == "NOT_VALIDATED"
    assert "insufficient_samples" in result["reasons"]


async def test_contradiction_blocks_validation(database):
    await _seed(
        database,
        [
            _pattern("TREND_UP", 40),
            _pattern("RANGE", 40),
            _pattern("TREND_DOWN", 40, contradictions=1),
        ],
    )
    result = await _evaluate(database)
    assert result["status"] == "NOT_VALIDATED"
    assert "unresolved_contradiction" in result["reasons"]


async def test_only_validated_generalized_can_create_validated_compression(database):
    await _seed(
        database, [_pattern("TREND_UP", 40), _pattern("RANGE", 40), _pattern("TREND_DOWN", 40)]
    )
    pipeline = GrowthMemoryPipeline(database.session_factory)
    validated = await pipeline.evaluate_generalized(
        asset="BTCUSDT", strategy="BREAKOUT", horizon="1h", setup_signature="s1"
    )
    assert validated["status"] == "VALIDATED"
    created = await pipeline.compress_validated(validated["generalized_id"])
    assert created["status"] == "CREATED"
    assert created["sample_tier"] == "VALIDATED_COMPRESSED_KNOWLEDGE"
    again = await pipeline.compress_validated(validated["generalized_id"])
    assert again["status"] == "ALREADY_COMPRESSED"


async def test_single_regime_cannot_create_validated_compression(database):
    await _seed(database, [_pattern("TREND_UP", 500)])
    pipeline = GrowthMemoryPipeline(database.session_factory)
    result = await pipeline.evaluate_generalized(
        asset="BTCUSDT", strategy="BREAKOUT", horizon="1h", setup_signature="s1"
    )
    assert result["status"] == "NOT_VALIDATED"
    rejected = await pipeline.compress_validated(result["generalized_id"])
    assert rejected["status"] == "NOT_ELIGIBLE"
    assert "generalized_not_validated" in rejected["reasons"]
