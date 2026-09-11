"""Read-only adapters exposing existing factual analytics to ChiefTrader."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from crypto_trader.llm.tools.registry import LLMToolRegistry, ToolEvidence
from crypto_trader.strategy.base import StrategyContext


def build_canonical_tool_registry(evidence) -> LLMToolRegistry:
    """Canonical quant evidence tools.

    ``evidence`` is either a single MultiStrategyAlpha (legacy BTC-only
    wiring) or a PerSymbolEvidenceRouter (MASTER DIRECTIVE §26): per-symbol
    factual evidence with no cross-symbol reuse. When the router cannot
    resolve an engine for the requested symbol, the tool reports
    data_quality=UNAVAILABLE instead of failing the decision cycle (§28).
    """
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
        registry.register(
            name, _tool(evidence, name),
            description=f"Read-only factual {name} evidence for the exact symbol and as-of time",
        )
    return registry


def _tool(evidence, name: str):
    async def execute(symbol: str, context: dict[str, Any]) -> ToolEvidence:
        ctx = context.get("strategy_context")
        if not isinstance(ctx, StrategyContext) or ctx.symbol != symbol:
            raise ValueError("factual StrategyContext required")
        resolve = getattr(evidence, "resolve", None)
        if resolve is not None:
            engine = await resolve(symbol)
            if engine is None:
                return ToolEvidence(
                    tool_name=name,
                    symbol=symbol,
                    timestamp=ctx.clock_time,
                    features={},
                    supporting_evidence=[],
                    contrary_evidence=[],
                    confidence_of_measurement=0.0,
                    data_quality="UNAVAILABLE",
                    source_refs=[f"tool:{name}", "evidence:UNAVAILABLE"],
                )
            analysis = engine.analyze_tool(ctx, name)
        else:
            analysis = evidence.analyze_tool(ctx, name)
        features = analysis.get("features", {})
        sources = [str(ref) for ref in analysis.get("source_refs", [])]
        if f"tool:{name}" not in sources:
            sources.append(f"tool:{name}")
        timestamp = analysis.get("timestamp") or ctx.market_timestamp or ctx.clock_time
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        return ToolEvidence(
            tool_name=name,
            symbol=symbol,
            timestamp=timestamp,
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
