import asyncio

from crypto_trader.factors.capture import FactorCaptureEngine
from crypto_trader.factors.catalog import FactorCatalog
from crypto_trader.factors.discovery import FactorDiscovery
from crypto_trader.factors.experiment import ExperimentRunner
from crypto_trader.factors.researcher import FactorResearcher
from crypto_trader.llm.tools.factor_research_tools import FactorResearchTools


def candles(n=30):
    rows = []
    for i in range(n):
        c = 100 + i * 0.5
        rows.append(
            {
                "open": str(c - 0.2),
                "high": str(c + 0.3),
                "low": str(c - 0.4),
                "close": str(c),
                "volume": str(100 + i),
            }
        )
    return rows


def test_factor_catalog_has_required_categories():
    catalog = FactorCatalog()
    entries = catalog.list()
    assert len(entries) >= 20
    categories = {e["category"] for e in entries}
    assert {"price", "volume", "volatility", "orderflow", "derivatives"} <= categories
    assert catalog.set_status("breakout", "VALIDATED") is True
    assert catalog.get("breakout").status == "VALIDATED"


def test_factor_capture_engine_all_groups():
    engine = FactorCaptureEngine()
    results = engine.capture(
        "BTC-USDT-SWAP",
        "15m",
        candles(),
        {
            "bid_volume": "60",
            "ask_volume": "40",
            "cvd": "100",
            "aggressive_total": "30",
            "total_volume": "100",
            "funding_rate": "0.0001",
            "previous_funding_rate": "0.00005",
            "open_interest": "1000",
            "open_interest_previous": "900",
            "price_change": "0.02",
            "liquidation_pressure": "0.3",
        },
    )
    names = {r.factor_name for r in results}
    assert {"return", "momentum", "trend", "breakout", "mean_reversion"} <= names
    assert {"volume_change", "volume_anomaly", "volume_divergence"} <= names
    assert {"atr", "realized_volatility", "volatility_regime"} <= names
    assert {"orderbook_imbalance", "buy_sell_imbalance", "cvd", "aggressive_trading_ratio"} <= names
    assert {
        "funding_rate",
        "funding_change",
        "open_interest",
        "oi_divergence",
        "liquidation_pressure",
    } <= names


def test_factor_researcher_question_flow():
    researcher = FactorResearcher()
    observations = [{"result": "WIN"}] * 40 + [{"result": "LOSS"}] * 10
    result = researcher.research(
        "q1", "orderflow predicts return", "orderflow", "okx", "15m", observations
    )
    assert result.sample_size == 50
    assert result.result == "VALIDATED"


def test_experiment_runner():
    observations = [{"result": "WIN"}] * 40 + [{"result": "LOSS"}] * 10
    experiment = ExperimentRunner().run(
        "e1", "funding extreme predicts reversal", "funding", "okx", "8h", observations
    )
    assert experiment.result == "VALIDATED"
    assert experiment.confidence > 0


def test_factor_discovery():
    candidate = FactorDiscovery().discover(
        factor_id="cvd", observations=[{}, {}], behavior="repeated_pattern"
    )
    assert candidate.score > 0
    assert candidate.category == "discovered"


def test_llm_factor_research_tools_flow():
    async def run():
        tools = FactorResearchTools()
        catalog = await tools.get_factor_catalog()
        assert catalog.ok is True
        assert len(catalog.data) >= 20
        history = await tools.get_factor_history("BTC-USDT-SWAP", "trend", 10)
        assert history.ok is False  # no service
        result = await tools.analyze_factor(
            "q1", "hypothesis", "trend", "okx", "15m", [{"result": "WIN"}] * 30
        )
        assert result.ok is True
        fetched = await tools.get_factor_research_result("q1")
        assert fetched.data["result"] == "VALIDATED"
        experiment = await tools.create_factor_experiment(
            "e1", "hypothesis", "trend", "okx", "15m", [{"result": "WIN"}] * 30
        )
        assert experiment.ok is True

    asyncio.run(run())
