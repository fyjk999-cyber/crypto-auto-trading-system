"""AI-ready context builder. No LLM calls, no AI orders."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AIAnalysisContext:
    symbol: str
    feature_vector: dict
    market_snapshot: dict
    position_state: dict
    risk_state: dict
    trade_memory: list[dict] = field(default_factory=list)
    daily_review: dict = field(default_factory=dict)
    prepared_at: str = ""


class AIContextBuilder:
    def build(
        self,
        *,
        symbol: str,
        feature_vector: dict | None = None,
        market_snapshot: dict | None = None,
        position_state: dict | None = None,
        risk_state: dict | None = None,
        trade_memory: list[dict] | None = None,
        daily_review: dict | None = None,
    ) -> AIAnalysisContext:
        from datetime import UTC, datetime

        return AIAnalysisContext(
            symbol=symbol,
            feature_vector=feature_vector or {},
            market_snapshot=market_snapshot or {},
            position_state=position_state or {},
            risk_state=risk_state or {},
            trade_memory=trade_memory or [],
            daily_review=daily_review or {},
            prepared_at=datetime.now(UTC).isoformat(),
        )
