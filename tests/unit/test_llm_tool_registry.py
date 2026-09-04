from __future__ import annotations

from datetime import UTC, datetime

from crypto_trader.llm.tools.registry import LLMToolRegistry, ToolEvidence


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
