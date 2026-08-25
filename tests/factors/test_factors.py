from decimal import Decimal

from crypto_trader.factors.calculators import (
    funding,
    momentum,
    open_interest,
    orderflow,
    trend,
    volatility,
    volume,
)
from crypto_trader.factors.engine import FactorEngine
from crypto_trader.factors.models import FactorResult
from crypto_trader.factors.registry import FactorRegistry
from crypto_trader.factors.snapshot import SnapshotBuilder
from crypto_trader.llm.context import LLMContextBuilder
from crypto_trader.llm.tools.factor_tools import FactorTools


def candles(n=30, close=100, with_volume=True):
    rows = []
    for i in range(n):
        c = close + i * 0.5
        row = {
            "open": str(c - 0.2),
            "high": str(c + 0.3),
            "low": str(c - 0.4),
            "close": str(c),
            "volume": str(100 + i) if with_volume else None,
        }
        rows.append(row)
    return rows


def test_trend_calculator():
    result = trend.calculate("BTC-USDT-SWAP", "15m", candles())
    assert result["factor_name"] == "trend"
    assert result["value"] > 0


def test_momentum_calculator():
    result = momentum.calculate("BTC-USDT-SWAP", "15m", candles())
    assert result["factor_name"] == "momentum"
    assert result["confidence"] > 0


def test_volatility_calculator():
    result = volatility.calculate("BTC-USDT-SWAP", "15m", candles())
    assert result["factor_name"] == "volatility"
    assert result["value"] >= 0


def test_volume_calculator():
    result = volume.calculate("BTC-USDT-SWAP", "15m", candles())
    assert result["factor_name"] == "volume"
    assert result["metadata"]["volume_change"] is not None


def test_orderflow_calculator():
    result = orderflow.calculate("BTC-USDT-SWAP", "15m", candles(), Decimal("60"), Decimal("40"))
    assert result["value"] > 0


def test_funding_calculator():
    result = funding.calculate("BTC-USDT-SWAP", "15m", Decimal("0.0002"), Decimal("0.0001"))
    assert result["factor_name"] == "funding"


def test_open_interest_calculator():
    result = open_interest.calculate(
        "BTC-USDT-SWAP", "15m", Decimal("1000"), Decimal("900"), Decimal("0.02")
    )
    assert result["factor_name"] == "open_interest"


def test_factor_engine_all():
    engine = FactorEngine()
    results = engine.calculate("BTC-USDT-SWAP", "15m", candles(), {"funding_rate": "0.0001"})
    assert len(results) == 7
    snapshot = SnapshotBuilder().build("BTC-USDT-SWAP", "15m", results)
    assert set(snapshot.market_state.keys()) == {
        "trend",
        "momentum",
        "volatility",
        "orderflow",
        "funding",
        "open_interest",
    }


def test_factor_registry():
    registry = FactorRegistry()
    assert len(registry.list()) == 7


def test_llm_context_accepts_factor_snapshot():
    ctx = LLMContextBuilder().build(symbol="BTC-USDT-SWAP", factor_snapshot={"trend": 0.8})
    assert ctx.factor_snapshot == {"trend": 0.8}


def test_factor_tools_unavailable_without_service():
    import asyncio

    tools = FactorTools()
    result = asyncio.run(tools.get_factor_snapshot("BTC-USDT-SWAP"))
    assert result.ok is False
    assert result.error == "FACTOR_SERVICE_UNAVAILABLE"


def test_factor_result_model():
    result = FactorResult(
        factor_name="trend",
        symbol="BTC-USDT-SWAP",
        timeframe="15m",
        value=Decimal("0.72"),
        confidence=Decimal("0.8"),
    )
    data = result.to_dict()
    assert data["factor_name"] == "trend"
    assert data["value"] == "0.72"


async def test_factor_service_persists(database):
    from crypto_trader.factors.engine import FactorEngine
    from crypto_trader.factors.service import FactorService
    from crypto_trader.factors.snapshot import SnapshotBuilder

    engine = FactorEngine()
    results = engine.calculate("BTC-USDT-SWAP", "15m", candles(), {"funding_rate": "0.0001"})
    snapshot = SnapshotBuilder().build("BTC-USDT-SWAP", "15m", results)
    service = FactorService(database.session_factory)
    await service.save_results(results)
    await service.save_snapshot(snapshot)
    latest = await service.latest_snapshot("BTC-USDT-SWAP")
    assert latest is not None
    assert latest["symbol"] == "BTC-USDT-SWAP"
    history = await service.history("BTC-USDT-SWAP", "trend", limit=10)
    assert len(history) == 1
    await service.ensure_registry()
