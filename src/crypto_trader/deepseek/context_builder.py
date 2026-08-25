"""DeepSeek prompt context builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class DeepSeekContext:
    symbol: str
    market_state: dict
    feature_vector: dict
    portfolio_state: dict
    trade_memory: list[dict] = field(default_factory=list)
    prepared_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class DeepSeekContextBuilder:
    def build(
        self,
        *,
        symbol: str,
        market_state: dict | None = None,
        feature_vector: dict | None = None,
        portfolio_state: dict | None = None,
        trade_memory: list[dict] | None = None,
    ) -> DeepSeekContext:
        return DeepSeekContext(
            symbol=symbol,
            market_state=market_state or {},
            feature_vector=feature_vector or {},
            portfolio_state=portfolio_state or {},
            trade_memory=trade_memory or [],
        )

    def render(self, ctx: DeepSeekContext, task: str = "market_opinion") -> str:
        return (
            f"Task: {task}. Symbol: {ctx.symbol}. Return JSON only.\n"
            f"Market: {ctx.market_state}\nFeatures: {ctx.feature_vector}\n"
            f"Portfolio: {ctx.portfolio_state}\nTradeMemory: {ctx.trade_memory}"
        )
