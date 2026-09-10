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

async def test_tool_timeout_returns_unavailable_and_does_not_fabricate():
    import asyncio

    async def slow(symbol: str, context: dict) -> ToolEvidence:
        await asyncio.sleep(1.0)
        return ToolEvidence(
            tool_name="slow", symbol=symbol, timestamp=datetime.now(UTC), features={},
            supporting_evidence=[], contrary_evidence=[], confidence_of_measurement=1.0,
            data_quality="HEALTHY", source_refs=[],
        )

    tools = LLMToolRegistry()
    tools.register("slow", slow)
    result = await tools.call("slow", "BTCUSDT", {}, timeout_seconds=0.01)
    assert result.data_quality == "UNAVAILABLE"
    assert result.contrary_evidence == ["tool timeout"]


async def test_tool_budget_rejects_excess_selection():
    async def tool(symbol: str, context: dict) -> ToolEvidence:
        return ToolEvidence(
            tool_name="x", symbol=symbol, timestamp=datetime.now(UTC), features={},
            supporting_evidence=[], contrary_evidence=[], confidence_of_measurement=1.0,
            data_quality="HEALTHY", source_refs=[],
        )

    tools = LLMToolRegistry()
    for name in ("a", "b", "c", "d"):
        tools.register(name, tool)
    try:
        await tools.build_package(
            ["a", "b", "c", "d"], "BTCUSDT", {}, now=datetime.now(UTC), max_tools=2
        )
    except ValueError:
        return
    raise AssertionError("budget should reject excess tool selection")


async def test_tool_budget_partial_failure_preserves_other_factual_items():
    import asyncio

    async def fast(symbol: str, context: dict) -> ToolEvidence:
        return ToolEvidence(
            tool_name="fast", symbol=symbol, timestamp=datetime.now(UTC), features={"ok": 1},
            supporting_evidence=["fact"], contrary_evidence=[], confidence_of_measurement=1.0,
            data_quality="HEALTHY", source_refs=[],
        )

    async def slow(symbol: str, context: dict) -> ToolEvidence:
        await asyncio.sleep(1.0)
        return ToolEvidence(
            tool_name="slow", symbol=symbol, timestamp=datetime.now(UTC), features={},
            supporting_evidence=[], contrary_evidence=[], confidence_of_measurement=1.0,
            data_quality="HEALTHY", source_refs=[],
        )

    tools = LLMToolRegistry()
    tools.register("fast", fast)
    tools.register("slow", slow)
    package = await tools.build_package(
        ["fast", "slow"], "BTCUSDT", {}, now=datetime.now(UTC),
        timeout_seconds=0.01, max_tools=2,
    )
    assert len(package.items) == 2
    fast_item = next(i for i in package.items if i.tool_name == "fast")
    slow_item = next(i for i in package.items if i.tool_name == "slow")
    assert fast_item.data_quality == "HEALTHY"
    assert slow_item.data_quality == "UNAVAILABLE"




async def test_tool_registry_rejects_unknown_tool():
    tools = LLMToolRegistry()
    try:
        await tools.call("missing", "BTCUSDT", {})
    except KeyError:
        return
    raise AssertionError("unknown tool should raise KeyError")



async def test_tool_registry_rejects_duplicate_register():
    tools = LLMToolRegistry()
    async def tool(symbol: str, context: dict) -> ToolEvidence:
        return ToolEvidence(
            tool_name="dup", symbol=symbol, timestamp=datetime.now(UTC), features={},
            supporting_evidence=[], contrary_evidence=[], confidence_of_measurement=1.0,
            data_quality="HEALTHY", source_refs=[],
        )
    tools.register("dup", tool)
    try:
        tools.register("dup", tool)
    except ValueError:
        return
    raise AssertionError("duplicate tool registration should raise ValueError")
