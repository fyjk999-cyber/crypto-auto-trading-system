import json
from decimal import Decimal

import httpx

from crypto_trader.api.deps import LLMRuntimeStatus
from crypto_trader.llm_chief.coin_profile import CoinProfileStore
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.conviction import ConvictionEngine
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.knowledge import KnowledgeBase, StrategyCard, ToolRecord
from crypto_trader.llm_chief.memory import ExperienceMemory, MarketPattern, TradeEpisode
from crypto_trader.llm_chief.provider import DeepSeekProvider, LLMResponse


async def test_deepseek_provider_captures_sanitized_operational_diagnostics():
    async def handler(request: httpx.Request) -> httpx.Response:
        import json

        assert request.headers["authorization"] == "Bearer test-secret"
        payload = json.loads(request.content)
        assert payload["max_tokens"] == 64
        assert payload["thinking"] == {"type": "enabled"}
        assert payload["reasoning_effort"] == "low"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"action":"WAIT"}'}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    provider = DeepSeekProvider(
        api_key="test-secret",
        model="deepseek-v4-pro",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.complete_json(prompt="JSON", retries=0, max_tokens=64)
    diagnostics = provider.diagnostics()
    assert result.ok is True
    assert diagnostics["provider"] == "deepseek"
    assert diagnostics["model"] == "deepseek-v4-pro"
    assert diagnostics["last_token_usage"] == {
        "prompt_tokens": 4,
        "completion_tokens": 2,
    }
    assert "test-secret" not in str(diagnostics)


async def test_deepseek_provider_fails_closed_without_retrying_nonretryable_http():
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": "unsafe external detail"})

    provider = DeepSeekProvider(
        api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    result = await provider.complete_json(prompt="JSON", retries=3)
    assert result.ok is False
    assert result.error == "HTTP_400"
    assert calls == 1
    assert "unsafe external detail" not in str(provider.diagnostics())


async def test_deepseek_provider_classifies_prose_contamination_without_parsing_it():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "```json\n{}\n```"}}],
                "usage": {"completion_tokens": 3},
            },
        )

    provider = DeepSeekProvider(
        api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    result = await provider.complete_json(prompt="JSON", retries=0)
    assert result.ok is False
    assert result.error == "PROSE_CONTAMINATION"
    assert provider.diagnostics()["last_token_usage"] == {"completion_tokens": 3}


async def test_deepseek_provider_retries_invalid_json_then_accepts_valid_json():
    calls = 0
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        requests.append(json.loads(request.content))
        content = "" if calls == 1 else '{"action":"WAIT"}'
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"completion_tokens": calls},
            },
        )

    provider = DeepSeekProvider(
        api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    result = await provider.complete_json(prompt="JSON", retries=1)
    assert result.ok is True
    assert result.parsed_json == {"action": "WAIT"}
    assert calls == 2
    assert requests[0]["thinking"] == {"type": "enabled"}
    assert requests[1]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in requests[1]
    assert provider.diagnostics()["last_attempt_count"] == 2


async def test_deepseek_provider_exhausts_invalid_json_fail_closed():
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": ""}}]},
        )

    provider = DeepSeekProvider(
        api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    result = await provider.complete_json(prompt="JSON", retries=1)
    assert result.ok is False
    assert result.error == "EMPTY_CONTENT"
    assert calls == 2
    assert provider.diagnostics()["last_attempt_count"] == 2



async def test_deepseek_provider_timeout_fails_closed_after_bounded_retries():
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.TimeoutException("slow provider")

    provider = DeepSeekProvider(
        api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    result = await provider.complete_json(prompt="JSON", retries=1)
    assert result.ok is False
    assert result.error == "LLM_TIMEOUT"
    assert calls == 2
    assert provider.diagnostics()["last_attempt_count"] == 2


async def test_deepseek_provider_malformed_payload_fails_closed():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    provider = DeepSeekProvider(
        api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    result = await provider.complete_json(prompt="JSON", retries=0)
    assert result.ok is False
    assert result.error == "MALFORMED_PROVIDER_RESPONSE"


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


async def test_llm_health_does_not_mislabel_probe_as_trading_decision(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload["messages"][0]["content"].startswith("Return only valid JSON"):
            assert payload["thinking"] == {"type": "disabled"}
            assert payload["max_tokens"] == 64
            assert "reasoning_effort" not in payload
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"status":"ok"}'}}]},
        )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-pro")
    provider = DeepSeekProvider(
        api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    status = LLMRuntimeStatus(provider_instance=provider)
    await status.probe()
    after_probe = status.snapshot()
    assert after_probe["reachable"] is True
    assert after_probe["decision_last_success_ts"] is None

    await provider.complete_json(
        prompt="canonical final decision",
        retries=0,
        operation="trading_decision",
    )
    after_decision = status.snapshot()
    assert after_decision["decision_last_success_ts"] is not None
    assert after_decision["decision_last_error"] is None
    assert after_decision["decision_last_attempt_count"] == 1


async def test_trading_decision_health_preserves_last_success_across_failure():
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = '{"action":"WAIT"}' if calls == 1 else ""
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    provider = DeepSeekProvider(
        api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    await provider.complete_json(
        prompt="first", retries=0, operation="trading_decision"
    )
    success_ts = provider.diagnostics()["operations"]["trading_decision"][
        "last_success_ts"
    ]
    await provider.complete_json(
        prompt="second", retries=0, operation="trading_decision"
    )
    decision_health = provider.diagnostics()["operations"]["trading_decision"]
    assert decision_health["last_success_ts"] == success_ts
    assert decision_health["last_error"] == "EMPTY_CONTENT"


def test_chief_trader_decision_schema_and_fail_safe():
    decision = ChiefTraderDecision(
        decision_id="d1",
        symbol="BTCUSDT",
        action="NO_TRADE",
        market_regime="RANGE",
        reason_codes=["LLM_UNAVAILABLE"],
    )
    assert decision.action == "NO_TRADE"


async def test_chief_trader_reserves_output_budget_after_reasoning_tokens():
    class CapturingProvider:
        name = "deepseek"
        model = "deepseek-v4-pro"

        async def complete_json(self, **kwargs):
            self.kwargs = kwargs
            return LLMResponse(
                text="",
                provider=self.name,
                model=self.model,
                latency_ms=1,
                ok=False,
                error="EMPTY_CONTENT",
            )

    provider = CapturingProvider()
    context = ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={"price": "100"},
        regime="RANGE",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
    )
    decision = await ChiefTraderEngine(provider=provider).decide(context)
    assert provider.kwargs["max_tokens"] == 2400
    assert decision.action == "FAIL_CLOSED"
    assert decision.reason_codes == ["EMPTY_CONTENT"]


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
                "thesis": "factual directional thesis",
                "stop_loss": 90,
        },
        ctx,
    )
    assert decision.action == "LONG"
    assert decision.symbol == "BTCUSDT"
    assert decision.decision_id.startswith("llm_")


def test_chief_trader_owns_identity_timestamp_and_model_version():
    engine = ChiefTraderEngine(model_version="canonical-live-v1")
    ctx = ChiefTraderContext(
        symbol="ETHUSDT",
        market_snapshot={"price": "2000"},
        regime="RANGE",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
    )
    decision = engine.parse_decision(
        {
            "decision_id": "model-controlled-id",
            "symbol": "WRONGUSDT",
            "position_state": "OPEN",
            "action": "WAIT",
            "created_at": "2000-01-01T00:00:00+00:00",
            "model_version": "model-controlled-version",
        },
        ctx,
        provider="deepseek",
        model="deepseek-v4-pro",
    )
    assert decision.decision_id.startswith("llm_")
    assert decision.decision_id != "model-controlled-id"
    assert decision.symbol == "ETHUSDT"
    assert decision.position_state == "FLAT"
    assert decision.model_version == "canonical-live-v1"
    assert decision.created_at != "2000-01-01T00:00:00+00:00"


async def test_chief_trader_missing_action_is_durable_fail_closed_input():
    class MissingActionProvider:
        name = "deepseek"
        model = "deepseek-v4-pro"

        async def complete_json(self, **_kwargs):
            return LLMResponse(
                text='{"market_regime":"RANGE"}',
                provider=self.name,
                model=self.model,
                latency_ms=1,
                parsed_json={"market_regime": "RANGE"},
            )

    ctx = ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={"price": "100"},
        regime="RANGE",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
    )
    decision = await ChiefTraderEngine(MissingActionProvider()).decide(ctx)
    assert decision.action == "FAIL_CLOSED"
    assert decision.reason_codes == ["INVALID_LLM_OUTPUT"]


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
