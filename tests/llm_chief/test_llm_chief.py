from decimal import Decimal

from crypto_trader.api.deps import LLMRuntimeStatus
from crypto_trader.llm_chief.coin_profile import CoinProfileStore
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.conviction import ConvictionEngine
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.knowledge import KnowledgeBase, StrategyCard, ToolRecord
from crypto_trader.llm_chief.memory import ExperienceMemory, MarketPattern, TradeEpisode
from crypto_trader.llm_chief.provider import DeepSeekProvider


def test_llm_provider_abstraction_without_key():
    provider = DeepSeekProvider(api_key=None)
    assert provider.healthy() is False


def test_deepseek_provider_uses_non_secret_runtime_configuration(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    provider = DeepSeekProvider(api_key=None)
    assert provider.model == "deepseek-v4-pro"
    assert provider.base_url == "https://api.deepseek.com"


async def test_llm_runtime_health_is_explicit_when_not_configured(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    status = LLMRuntimeStatus()
    await status.probe()
    assert status.snapshot()["configured"] is False
    assert status.snapshot()["reachable"] is False
    assert status.snapshot()["last_error"] == "NOT_CONFIGURED"


def test_chief_trader_decision_schema_and_fail_safe():
    decision = ChiefTraderDecision(
        decision_id="d1",
        symbol="BTCUSDT",
        action="NO_TRADE",
        market_regime="RANGE",
        reason_codes=["LLM_UNAVAILABLE"],
    )
    assert decision.action == "NO_TRADE"


def test_chief_trader_engine_parse_decision():
    engine = ChiefTraderEngine()
    ctx = ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={"price": "100"},
        regime="BULL",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
    )
    decision = engine.parse_decision(
        {
            "action": "LONG",
            "raw_llm_confidence": 0.8,
            "position_size_request": 0.1,
            "leverage_request": 3,
        },
        ctx,
    )
    assert decision.action == "LONG"
    assert decision.symbol == "BTCUSDT"
    assert decision.decision_id.startswith("llm_")


def test_knowledge_base_retrieval_versioned():
    kb = KnowledgeBase()
    kb.add_strategy(
        StrategyCard(
            strategy_id="trend",
            name="Trend",
            strategy_family="trend",
            description="Follow trend",
            ideal_regimes=["BULL"],
            bad_regimes=["RANGE"],
            required_evidence=["trend_strength"],
            entry_logic="ema",
            exit_logic="ema",
            invalidation_logic="close",
            position_sizing_guidance="1x",
            leverage_guidance="2x",
            expected_holding_period="1h",
            known_failure_modes=["false breakout"],
            evidence_quality="HIGH",
            version="1",
        )
    )
    kb.add_tool(
        ToolRecord(
            "trend_strength",
            "Trend Strength",
            "Measure trend",
            "when trending",
            "not in range",
            "low",
            "low",
            "1",
        )
    )
    kb.add_document("d1", "Trend Trading", "Buy strength", ["trend", "BULL"], "1")
    results = kb.retrieve(["trend", "BULL"])
    assert len(results) == 1
    assert results[0]["id"] == "d1"


def test_experience_memory_cross_coin_retrieval():
    memory = ExperienceMemory()
    memory.store_episode(
        TradeEpisode(
            episode_id="e1",
            symbol="BTCUSDT",
            market_regime="BULL",
            quant_evidence=[],
            llm_thesis="trend long",
            raw_llm_confidence=0.8,
            conviction_score=0.7,
            result="WIN",
            gross_pnl=Decimal("10"),
            net_pnl=Decimal("8"),
            mistakes=[],
            lessons=["trend works"],
        )
    )
    memory.store_episode(
        TradeEpisode(
            episode_id="e2",
            symbol="SOLUSDT",
            market_regime="BULL",
            quant_evidence=[],
            llm_thesis="momentum long",
            raw_llm_confidence=0.7,
            conviction_score=0.6,
            result="LOSS",
            gross_pnl=Decimal("-5"),
            net_pnl=Decimal("-6"),
            mistakes=["late entry"],
            lessons=["wait confirmation"],
        )
    )
    similar = memory.similar_episodes("ETHUSDT", "BULL")
    assert len(similar) == 2
    compressed = memory.compress_experience(min_samples=2)
    assert len(compressed) >= 1


def test_market_pattern_update_version():
    memory = ExperienceMemory()
    pattern = MarketPattern(
        pattern_id="p1",
        regime="BULL",
        trend_state="UP",
        volatility_state="HIGH",
        volume_state="HIGH",
        strategy_family="trend",
        sample_count=10,
        win_count=6,
        loss_count=4,
        win_rate=Decimal("0.6"),
        profit_factor=Decimal("1.5"),
        average_return=Decimal("0.02"),
    )
    memory.update_pattern(pattern)
    memory.update_pattern(pattern)
    assert memory.patterns["p1"].version == 2


def test_coin_profile_update_and_behavior_tags():
    store = CoinProfileStore()
    profile = store.get_or_create("BTCUSDT")
    episode = TradeEpisode(
        episode_id="e1",
        symbol="BTCUSDT",
        market_regime="BULL",
        quant_evidence=[],
        llm_thesis="long",
        raw_llm_confidence=0.8,
        conviction_score=0.7,
        result="WIN",
        gross_pnl=Decimal("10"),
        net_pnl=Decimal("8"),
        mistakes=[],
        lessons=["trend works"],
    )
    profile.update_from_episode(episode)
    assert profile.sample_count == 1
    assert profile.version == 2
    assert profile.profile_summary == "EXPERIMENTAL"


def test_conviction_engine_caps_leverage():
    engine = ConvictionEngine()
    result = engine.evaluate(
        llm_confidence=0.9,
        calibrated_accuracy=0.6,
        quant_agreement=0.8,
        strategy_sharpe=Decimal("1.2"),
        pattern_win_rate=Decimal("0.6"),
        sample_confidence="MEDIUM",
        liquidity_score=Decimal("80"),
        cost_ratio=Decimal("0.15"),
        requested_leverage=Decimal("10"),
        max_leverage=Decimal("5"),
    )
    assert result.conviction_score > 0
    assert result.approved_leverage <= Decimal("5")
