from crypto_trader.daily_report.generator import DailyAIReportGenerator
from crypto_trader.decision_replay.snapshot import DecisionSnapshot
from crypto_trader.llm_runtime.executor import LLMExecutor
from crypto_trader.paper_training.evaluator import AITrainingEvaluator
from crypto_trader.prompt_evolution.engine import PromptEvolutionEngine
from crypto_trader.self_critic.critic import SelfCriticAgent
from crypto_trader.strategy_research.agent import StrategyResearchAgent
from crypto_trader.vector_memory.embedding_provider import LocalHashEmbeddingProvider
from crypto_trader.vector_memory.retrieval import HybridRetriever
from crypto_trader.vector_memory.schemas import MemoryVector
from crypto_trader.vector_memory.vector_store import MemoryVectorStore


def test_vector_store_and_retrieval():
    store = MemoryVectorStore()
    provider = LocalHashEmbeddingProvider()
    embedding = provider.embed("BTC trend breakout high volume")
    store.add(
        MemoryVector(
            id="v1",
            object_type="TRADE_EPISODE",
            object_id="e1",
            content_hash="h1",
            embedding=embedding,
            metadata={
                "symbol": "BTCUSDT",
                "regime": "BULL",
                "pattern": "TREND_BREAKOUT",
                "result": "WIN",
                "quality": 0.8,
            },
        )
    )
    retriever = HybridRetriever(store, provider)
    result = retriever.retrieve(
        query_text="BTC trend breakout high volume", symbol="BTCUSDT", regime="BULL", top_k=3
    )
    assert result["similar_cases"]
    assert result["similar_cases"][0]["symbol"] == "BTCUSDT"


def test_llm_runtime_failsafe_no_trade():
    import asyncio

    result = asyncio.run(LLMExecutor(provider=None).execute("prompt"))
    assert result.decision["action"] == "NO_TRADE"


def test_prompt_evolution_best_version():
    engine = PromptEvolutionEngine()
    engine.add("v1", "simple prompt", 0.5)
    engine.add("v2", "prompt with failure cases", 0.8)
    assert engine.best().version == "v2"


def test_decision_replay_ready():
    snapshot = DecisionSnapshot(
        snapshot_id="s1",
        market_data={"price": "100"},
        quant_evidence={"trend": "LONG"},
        knowledge={},
        memory={},
        coin_profile={},
        prompt_version="v2",
        llm_response={"action": "LONG"},
        risk_decision={"decision": "APPROVE"},
    )
    assert snapshot.replay_ready() is True


def test_self_critic_agent():
    report = SelfCriticAgent().review("ep1", was_win=True, ignored_btc_divergence=True)
    assert "ignored BTC divergence" in report.mistakes
    assert report.confidence_adjustment_pct == -0.15


def test_strategy_research_agent():
    proposal = StrategyResearchAgent().research("p1", "SOLUSDT", "orderflow breakout")
    assert proposal.status == "PROPOSED"
    assert "SOLUSDT" in proposal.hypothesis


def test_daily_report_and_paper_training_evaluator():
    report = DailyAIReportGenerator().generate(
        date="2026-08-25",
        regime="TREND_BULL",
        risks=["funding extreme"],
        opportunities=["BTC LONG"],
        coin_status={"BTC": "bullish"},
        strategy_status={"trend": "active"},
        learning_updates=["lesson 1"],
    )
    assert report.regime == "TREND_BULL"
    evaluator = AITrainingEvaluator()
    result = evaluator.evaluate(
        episodes=[
            {"symbol": "BTCUSDT", "result": "CORRECT", "confidence": 0.8, "actual": 1.0},
            {
                "symbol": "SOLUSDT",
                "result": "WRONG",
                "confidence": 0.9,
                "actual": 0.0,
                "failure_reason": "LATE_ENTRY",
            },
        ]
    )
    assert result.episode_count == 2
    assert result.coverage_symbols == ["BTCUSDT", "SOLUSDT"]
    assert result.failure_reasons["LATE_ENTRY"] == 1
