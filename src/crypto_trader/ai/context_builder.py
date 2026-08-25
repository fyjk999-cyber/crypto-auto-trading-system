"""AI context builder: no LLM calls, no trading."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class AIAnalysisContext:
    symbol: str
    feature_vector: dict
    market_snapshot: dict
    opportunity: dict
    regime: str
    trade_memory: list[dict] = field(default_factory=list)
    prepared_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class AIContextBuilder:
    def build(
        self,
        *,
        symbol: str,
        feature_vector: dict | None = None,
        market_snapshot: dict | None = None,
        opportunity: dict | None = None,
        regime: str = "UNKNOWN",
        trade_memory: list[dict] | None = None,
    ) -> AIAnalysisContext:
        return AIAnalysisContext(
            symbol=symbol,
            feature_vector=feature_vector or {},
            market_snapshot=market_snapshot or {},
            opportunity=opportunity or {},
            regime=regime,
            trade_memory=trade_memory or [],
        )
