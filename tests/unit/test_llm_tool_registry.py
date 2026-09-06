from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from crypto_trader.alpha.ensemble import MultiStrategyAlpha
from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.models import Account
from crypto_trader.llm.tools.alpha import build_canonical_tool_registry
from crypto_trader.llm.tools.registry import LLMToolRegistry, ToolEvidence
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.strategy.base import StrategyContext


async def test_llm_selects_only_requested_quant_tool():
    calls: list[str] = []

    async def trend(symbol: str, context: dict) -> ToolEvidence:
        calls.append(f"trend:{symbol}")
        return ToolEvidence(
            tool_name="trend",
            symbol=symbol,
            timestamp=datetime.now(UTC),
            features={"slope": "positive"},
            supporting_evidence=["higher highs"],
            contrary_evidence=[],
            confidence_of_measurement=0.8,
            data_quality="HEALTHY",
            source_refs=["OKX:BTC-USDT-SWAP"],
        )

    async def funding(symbol: str, context: dict) -> ToolEvidence:
        calls.append(f"funding:{symbol}")
        raise RuntimeError("not requested in this test")

    tools = LLMToolRegistry()
    tools.register("trend", trend)
    tools.register("funding", funding)

    result = await tools.call("trend", "BTCUSDT", {"market": "fresh"})
    assert tools.available() == ["funding", "trend"]
    assert result.supporting_evidence == ["higher highs"]
    assert calls == ["trend:BTCUSDT"]


async def test_tool_failure_returns_unavailable_evidence_without_fabrication():
    async def unavailable(symbol: str, context: dict) -> ToolEvidence:
        raise RuntimeError("provider timeout")

    tools = LLMToolRegistry()
    tools.register("funding", unavailable)
    result = await tools.call("funding", "BTCUSDT", {})
    assert result.data_quality == "UNAVAILABLE"
    assert result.features == {}
    assert result.confidence_of_measurement == 0


async def test_alpha_adapter_executes_only_the_tool_selected_by_chief():
    class SelectiveAlpha:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def analyze_tool(self, ctx, name: str):
            self.calls.append(name)
            return {
                "tool_name": name,
                "features": {"selected": name},
                "supporting_evidence": [f"{name}:fact"],
                "contrary_evidence": [],
                "confidence_of_measurement": 1.0,
                "data_quality": "FACTUAL_OKX",
                "source_refs": [f"tool:{name}"],
            }

        def analyze_evidence(self, _ctx):
            raise AssertionError("selective tools must not run the full quant ensemble")

    alpha = SelectiveAlpha()
    tools = build_canonical_tool_registry(alpha)  # type: ignore[arg-type]
    now = datetime.now(UTC)
    book = OrderBook(symbol="ETHUSDT", exchange="OKX")
    book.apply_snapshot(
        1,
        [(Decimal("100"), Decimal("1"))],
        [(Decimal("101"), Decimal("1"))],
        now=now,
    )
    ctx = StrategyContext(
        symbol="ETHUSDT",
        book=book,
        account=Account(equity=Decimal("1000")),
        positions={},
        clock_time=now,
        funding=Decimal("0.0001"),
    )

    result = await tools.call("funding", "ETHUSDT", {"strategy_context": ctx})

    assert alpha.calls == ["funding"]
    assert result.features == {"selected": "funding"}


async def test_real_alpha_selective_strategy_does_not_evaluate_unselected_strategies():
    calls: list[str] = []

    class Strategy:
        def __init__(self, name: str) -> None:
            self.name = name

        def evaluate(self, _ctx):
            calls.append(self.name)
            return SimpleNamespace(
                strategy=self.name,
                version="test",
                side=OrderSide.BUY,
                confidence=Decimal("0.8"),
                reason_codes=[self.name],
                metadata={},
            )

    alpha = MultiStrategyAlpha(symbol="ETHUSDT")
    alpha.sub_strategies = [
        Strategy("trend_following"),
        Strategy("momentum"),
        Strategy("breakout"),
        Strategy("mean_reversion"),
    ]
    now = datetime.now(UTC)
    book = OrderBook(symbol="ETHUSDT", exchange="OKX")
    book.apply_snapshot(
        1,
        [(Decimal("100"), Decimal("1"))],
        [(Decimal("101"), Decimal("1"))],
        now=now,
    )
    ctx = StrategyContext(
        symbol="ETHUSDT",
        book=book,
        account=Account(equity=Decimal("1000")),
        positions={},
        clock_time=now,
    )

    result = await build_canonical_tool_registry(alpha).call(
        "trend", "ETHUSDT", {"strategy_context": ctx}
    )

    assert calls == ["trend_following"]
    assert result.features["strategy_evidence"][0]["strategy"] == "trend_following"
