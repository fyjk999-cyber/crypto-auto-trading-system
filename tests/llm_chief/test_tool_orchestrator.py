from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_trader.llm.tools.registry import LLMToolRegistry, ToolEvidence
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.provider import LLMResponse
from crypto_trader.llm_chief.tool_orchestrator import ToolDrivenChiefTrader


class Provider:
    name = "deepseek"
    model = "deepseek-v4-pro"

    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.calls = 0

    async def complete_json(self, **_kwargs):
        payload = self.payloads[self.calls]
        self.calls += 1
        return LLMResponse(
            text="{}",
            provider=self.name,
            model=self.model,
            latency_ms=1,
            parsed_json=payload,
        )


def context(symbol: str = "BTCUSDT") -> ChiefTraderContext:
    return ChiefTraderContext(
        symbol=symbol,
        market_snapshot={"source": "OKX_PUBLIC"},
        regime="UNKNOWN",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
    )


async def test_same_chief_selects_only_requested_tools_then_makes_final_decision():
    called: list[str] = []

    async def tool(name: str, symbol: str, _context: dict) -> ToolEvidence:
        called.append(name)
        return ToolEvidence(
            tool_name=name,
            symbol=symbol,
            timestamp=datetime.now(UTC),
            features={"value": name},
            supporting_evidence=[name],
            contrary_evidence=[],
            confidence_of_measurement=0.9,
            data_quality="HEALTHY",
            source_refs=[f"okx:{symbol}:{name}"],
        )

    registry = LLMToolRegistry()
    for name in ("trend", "funding", "orderbook"):
        async def execute(symbol, payload, selected=name):
            return await tool(selected, symbol, payload)

        registry.register(name, execute)
    provider = Provider(
        [
            {"tools": ["trend", "orderbook"]},
            {
                "action": "NO_TRADE",
                "market_regime": "RANGE",
                "reason_codes": ["INSUFFICIENT_EDGE"],
            },
        ]
    )
    chief = ChiefTraderEngine(provider=provider)
    decision, package = await ToolDrivenChiefTrader(chief, registry).decide(
        context(), tool_context={}, now=datetime.now(UTC)
    )
    assert provider.calls == 2
    assert called == ["trend", "orderbook"]
    assert package is not None and package.selected_tools == ["trend", "orderbook"]
    assert decision.action == "NO_TRADE"
    assert decision.model_provider == "deepseek"


async def test_tool_failure_is_factual_unavailable_evidence_not_fabricated():
    async def broken(_symbol, _context):
        raise RuntimeError("timeout")

    registry = LLMToolRegistry()
    registry.register("funding", broken)
    provider = Provider(
        [
            {"tools": ["funding"]},
            {"action": "WAIT", "market_regime": "UNKNOWN"},
        ]
    )
    decision, package = await ToolDrivenChiefTrader(
        ChiefTraderEngine(provider=provider), registry
    ).decide(context(), tool_context={}, now=datetime.now(UTC))
    assert decision.action == "WAIT"
    assert package is not None
    assert package.items[0].data_quality == "UNAVAILABLE"
    assert package.items[0].finding == {}
    assert package.items[0].supporting_evidence == []


async def test_stale_evidence_is_marked_and_unknown_tool_fails_closed():
    async def stale(symbol, _context):
        return ToolEvidence(
            tool_name="trend",
            symbol=symbol,
            timestamp=datetime.now(UTC) - timedelta(minutes=5),
            features={"slope": "up"},
            supporting_evidence=[],
            contrary_evidence=[],
            confidence_of_measurement=0.5,
            data_quality="HEALTHY",
            source_refs=["okx:old"],
        )

    registry = LLMToolRegistry()
    registry.register("trend", stale)
    valid_provider = Provider(
        [{"tools": ["trend"]}, {"action": "WAIT", "market_regime": "UNKNOWN"}]
    )
    _, package = await ToolDrivenChiefTrader(
        ChiefTraderEngine(provider=valid_provider), registry
    ).decide(context(), tool_context={}, now=datetime.now(UTC))
    assert package is not None and package.items[0].freshness == "STALE"

    invalid_provider = Provider([{"tools": ["nonexistent"]}])
    decision, package = await ToolDrivenChiefTrader(
        ChiefTraderEngine(provider=invalid_provider), registry
    ).decide(context(), tool_context={}, now=datetime.now(UTC))
    assert decision.action == "FAIL_CLOSED"
    assert package is None
    assert invalid_provider.calls == 1
