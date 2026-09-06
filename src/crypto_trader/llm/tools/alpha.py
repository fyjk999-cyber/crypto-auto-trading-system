"""Read-only adapters exposing existing factual analytics to ChiefTrader."""

from __future__ import annotations

from typing import Any

from crypto_trader.alpha.ensemble import MultiStrategyAlpha
from crypto_trader.llm.tools.registry import LLMToolRegistry, ToolEvidence
from crypto_trader.strategy.base import StrategyContext


def build_canonical_tool_registry(alpha: MultiStrategyAlpha) -> LLMToolRegistry:
    registry = LLMToolRegistry()
    for name in (
        "trend",
        "momentum",
        "breakout",
        "mean_reversion",
        "market_regime",
        "volatility",
        "funding",
        "open_interest",
        "basis",
        "orderbook",
        "liquidity",
    ):
        registry.register(name, _tool(alpha, name))
    return registry


def _tool(alpha: MultiStrategyAlpha, name: str):
    async def execute(symbol: str, context: dict[str, Any]) -> ToolEvidence:
        ctx = context.get("strategy_context")
        if not isinstance(ctx, StrategyContext) or ctx.symbol != symbol:
            raise ValueError("factual StrategyContext required")
        analysis = alpha.analyze_tool(ctx, name)
        features = analysis.get("features", {})
        sources = [str(ref) for ref in analysis.get("source_refs", [])]
        if f"tool:{name}" not in sources:
            sources.append(f"tool:{name}")
        return ToolEvidence(
            tool_name=name,
            symbol=symbol,
            timestamp=ctx.clock_time,
            features=features,
            supporting_evidence=[
                str(reason) for reason in analysis.get("supporting_evidence", [])
            ],
            contrary_evidence=[
                str(reason) for reason in analysis.get("contrary_evidence", [])
            ],
            confidence_of_measurement=float(
                analysis.get("confidence_of_measurement", 0.0)
            ),
            data_quality=str(analysis.get("data_quality", "UNAVAILABLE")),
            source_refs=sources,
        )

    return execute
