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
        analysis = alpha.analyze_evidence(ctx)
        features = _finding(name, analysis, ctx)
        sources = [str(ref) for ref in analysis.get("source_refs", [])]
        sources.append(f"tool:{name}")
        return ToolEvidence(
            tool_name=name,
            symbol=symbol,
            timestamp=ctx.clock_time,
            features=features,
            supporting_evidence=_reasons(name, analysis),
            contrary_evidence=[],
            confidence_of_measurement=float(
                analysis.get("confidence_of_measurement", 0.0)
            ),
            data_quality=str(analysis.get("data_quality", "UNAVAILABLE")),
            source_refs=sources,
        )

    return execute


def _finding(name: str, analysis: dict[str, Any], ctx: StrategyContext) -> dict[str, Any]:
    if name in {"trend", "momentum", "breakout", "mean_reversion"}:
        return {
            "strategy_evidence": [
                signal
                for signal in analysis.get("signals", [])
                if signal.get("strategy") == name
            ]
        }
    if name == "market_regime":
        return {"regime": analysis.get("regime", {})}
    if name == "volatility":
        features = analysis.get("features", {})
        return {key: value for key, value in features.items() if "vol" in key.lower()}
    if name == "funding":
        return {"funding": str(ctx.funding) if ctx.funding is not None else None}
    if name == "open_interest":
        return {"open_interest": str(ctx.oi) if ctx.oi is not None else None}
    if name == "basis":
        return {"basis": str(ctx.basis) if ctx.basis is not None else None}
    if name in {"orderbook", "liquidity"}:
        bid, ask = ctx.book.best_bid(), ctx.book.best_ask()
        return {
            "best_bid": str(bid.price) if bid else None,
            "best_ask": str(ask.price) if ask else None,
            "bid_quantity": str(bid.quantity) if bid else None,
            "ask_quantity": str(ask.quantity) if ask else None,
            "spread": str(ask.price - bid.price) if bid and ask else None,
        }
    return {}


def _reasons(name: str, analysis: dict[str, Any]) -> list[str]:
    if name in {"trend", "momentum", "breakout", "mean_reversion"}:
        return [
            str(reason)
            for signal in analysis.get("signals", [])
            if signal.get("strategy") == name
            for reason in signal.get("reason_codes", [])
        ]
    return [str(reason) for reason in analysis.get("supporting_evidence", [])]
