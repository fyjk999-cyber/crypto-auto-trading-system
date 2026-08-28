from datetime import UTC, datetime

from crypto_trader.decision_replay.evidence import DecisionEvidence
from crypto_trader.llm_runtime.contracts import LLMResponse, ModelRoute
from crypto_trader.llm_runtime.domain_models import DomainModelRuntime, TradingAnalysisResult


class CapturingGateway:
    def __init__(self) -> None:
        self.routes = {
            name: ModelRoute(route_name=name, provider_id="deepseek", model_name="deepseek-chat")
            for name in (
                "live_analysis",
                "daily_review",
                "daily_lesson_extraction",
                "evolution_research",
                "evolution_hypothesis",
                "evolution_candidate_reasoning",
            )
        }
        self.request = None
        self.response_model = None

    async def invoke(self, request, response_model):
        self.request = request
        self.response_model = response_model
        return LLMResponse(
            invocation_id="domain-test",
            ok=True,
            route=request.route,
            provider="deepseek",
            model="deepseek-chat",
            content={"decision_id": "d1", "symbol": "BTCUSDT", "action": "NO_TRADE"},
        )


async def test_live_domain_model_wraps_canonical_context_and_uses_structured_schema():
    gateway = CapturingGateway()
    runtime = DomainModelRuntime(gateway)
    response = await runtime.invoke(
        route="live_analysis",
        context={
            "MarketSnapshot": {"symbol": "BTCUSDT"},
            "FactorSnapshot": [],
            "FactorHealth": {},
            "FactorProfile": "FULL",
            "PortfolioState": {},
            "PositionState": {},
            "RiskContext": {},
            "RelevantMemory": {},
            "TradingRelease": {},
        },
        response_model=TradingAnalysisResult,
    )
    assert response.ok is True
    assert gateway.response_model is TradingAnalysisResult
    assert '"domain_model":"CryptoTrader-Live-v1"' in gateway.request.prompt
    assert '"MarketSnapshot"' in gateway.request.prompt
    assert "You ARE the entry decision authority" in gateway.request.prompt
    assert "THE RISK ENGINE DECIDES WHETHER IT MAY BE EXECUTED" in gateway.request.prompt
    assert gateway.request.route == "live_analysis"
    assert gateway.request.brain == "LIVE"


def test_base_provider_models_and_domain_models_are_distinct_and_versioned():
    profiles = DomainModelRuntime(CapturingGateway()).describe()
    assert [profile["display_name"] for profile in profiles] == [
        "CryptoTrader-Live-v1",
        "CryptoTrader-Learning-v1",
        "CryptoTrader-Evolution-v1",
    ]
    assert profiles[0]["routes"][0]["base_model"] == "deepseek-chat"
    assert profiles[0]["display_name"] != profiles[0]["routes"][0]["base_model"]
    for profile in profiles:
        assert all(
            profile[key]
            for key in (
                "prompt_version",
                "context_profile_version",
                "factor_profile_version",
                "tool_policy_version",
                "output_schema_version",
            )
        )


def test_decision_evidence_serializes_domain_model_version():
    evidence = DecisionEvidence(
        decision_id="domain-evidence",
        timestamp_utc=datetime.now(UTC).isoformat(),
        symbol="BTCUSDT",
        timeframe="1m",
        strategy_id="llm_chief_trader",
        strategy_version="1",
        model_version="deepseek-chat",
        prompt_version="live-prompt-v1",
        factor_snapshot_id="f1",
        factor_set_version="factorset-v1",
        factor_profile="FULL",
        market_data_reference="m1",
        analysis_evidence={},
        decision={},
        risk_decision={},
        domain_model_version="CryptoTrader-Live-v1",
    )
    assert evidence.to_dict()["domain_model_version"] == "CryptoTrader-Live-v1"


async def test_live_prompt_carries_output_schema_and_decision_correlation_id():
    gateway = CapturingGateway()
    runtime = DomainModelRuntime(gateway)
    await runtime.invoke(
        route="live_analysis",
        context={"MarketSnapshot": {}, "FactorSnapshot": [], "FactorHealth": {},
                 "FactorProfile": "FULL", "PortfolioState": {}, "PositionState": {},
                 "RiskContext": {}, "RelevantMemory": {}, "TradingRelease": {}},
        response_model=TradingAnalysisResult,
    )
    assert '"output_schema_example"' in gateway.request.prompt
    assert '"action":"LONG|SHORT|NO_TRADE|WAIT"' in gateway.request.prompt
    assert '"DecisionId"' in gateway.request.prompt
    prompt = gateway.request.prompt
    assert prompt.index("output_schema_example") < prompt.index('"context"')


def test_learning_and_evolution_prompts_carry_their_own_schema_examples():
    from crypto_trader.llm_runtime.domain_models import ROUTE_OUTPUT_EXAMPLES

    for route in ("daily_review", "daily_lesson_extraction", "evolution_research",
                  "evolution_hypothesis", "evolution_candidate_reasoning"):
        assert route in ROUTE_OUTPUT_EXAMPLES
    assert "decision_id" not in ROUTE_OUTPUT_EXAMPLES["daily_review"]
