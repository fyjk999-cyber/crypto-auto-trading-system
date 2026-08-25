from decimal import Decimal

from crypto_trader.llm_chief.coin_profile import CoinProfile
from crypto_trader.llm_chief.engines import (
    CoinBehaviorEngine,
    CoinClusterEngine,
    ContextBudgetManager,
    ExperienceCompressionEngine,
    MarketPatternEngine,
    MemoryRetrievalEngine,
    TradeReviewEngine,
)
from crypto_trader.llm_chief.memory import ExperienceMemory, TradeEpisode
from crypto_trader.llm_chief.persistence import LLMMemoryStore


def make_episode(episode_id, symbol="BTCUSDT", result="WIN"):
    return TradeEpisode(
        episode_id=episode_id,
        symbol=symbol,
        market_regime="BULL",
        quant_evidence=[{"signal": "trend", "confidence": 0.8}],
        llm_thesis="trend long",
        raw_llm_confidence=0.8,
        conviction_score=0.7,
        result=result,
        gross_pnl=Decimal("10"),
        net_pnl=Decimal("8"),
        mistakes=[],
        lessons=["confirm trend"],
    )


async def test_memory_persistence_roundtrip(database):
    store = LLMMemoryStore(database.session_factory)
    episode = make_episode("ep_persist", "SOLUSDT", "LOSS")
    await store.save_episode(episode)
    rows = await store.load_episodes(limit=10)
    assert any(r["episode_id"] == "ep_persist" for r in rows)
    await store.save_compressed("rule1", "Trend confirmation", "Volume + trend", 1)
    compressed = await store.load_compressed(limit=10)
    assert compressed[0]["rule_id"] == "rule1"


async def test_review_pattern_coin_persistence(database):
    store = LLMMemoryStore(database.session_factory)
    await store.save_review(
        "ep1",
        ["TREND"],
        ["LATE"],
        ["late entry"],
        ["wait confirmation"],
        ["confirm first"],
        Decimal("0.6"),
    )
    pattern = MarketPatternEngine().build_pattern(
        pattern_id="pat1",
        regime="BULL",
        features={"trend": "UP", "volatility": "HIGH", "volume": "HIGH"},
        strategy="trend",
        sample_count=10,
        win_count=6,
        loss_count=4,
        profit_factor=Decimal("1.5"),
    )
    await store.save_pattern(pattern)
    await store.save_coin_profile("BTCUSDT", 5, "LOW", ["TREND_FRIENDLY"], 2)
    episodes = await store.load_episodes(limit=10)
    assert isinstance(episodes, list)


def test_trade_review_engine():
    episode = make_episode("ep1", "BTCUSDT", "LOSS")
    report = TradeReviewEngine().review(episode)
    assert report.episode_id == "ep1"
    assert report.failure_factors
    assert report.lessons


def test_cross_coin_memory_retrieval():
    memory = ExperienceMemory()
    memory.store_episode(make_episode("e1", "BTCUSDT"))
    memory.store_episode(make_episode("e2", "SOLUSDT"))
    engine = MemoryRetrievalEngine()
    rows = engine.retrieve(symbol="ETHUSDT", regime="BULL", memory=memory)
    assert len(rows) == 2


def test_experience_compression_and_budget():
    memory = ExperienceMemory()
    memory.store_episode(make_episode("e1", "BTCUSDT"))
    memory.store_episode(make_episode("e2", "SOLUSDT"))
    memory.store_episode(make_episode("e3", "AVAXUSDT", "LOSS"))
    rules = ExperienceCompressionEngine().compress(list(memory.episodes.values()))
    assert len(rules) >= 1
    budget = ContextBudgetManager()
    assert budget.fit(4000) is True
    assert budget.fit(6000) is False
    assert budget.fit(11000, deep_research=True) is True


def test_coin_behavior_and_cluster():
    profile = CoinProfile(symbol="SOLUSDT")
    episode = make_episode("e1", "SOLUSDT")
    CoinBehaviorEngine().update_profile(profile, episode)
    assert profile.sample_count == 1
    cluster = CoinClusterEngine().cluster([], {"beta": 1.5, "momentum": 0.4})
    assert cluster == "HIGH_BETA_MOMENTUM_ALT"
