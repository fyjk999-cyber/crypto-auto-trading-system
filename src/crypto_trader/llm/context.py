"""LLM context builder and output contract. LLM cannot submit orders."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


class LLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: str  # LONG | SHORT | NO_TRADE
    confidence: float
    risk_level: str
    reason_codes: list[str] = Field(default_factory=list)
    invalid_conditions: list[str] = Field(default_factory=list)


@dataclass
class LLMContext:
    symbol: str
    market_state: dict
    feature_vector: dict
    position_state: dict
    risk_state: dict
    trade_memory: list[dict] = field(default_factory=list)
    daily_review: dict = field(default_factory=dict)
    prepared_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class LLMContextBuilder:
    def build(
        self,
        *,
        symbol: str,
        market_state: dict | None = None,
        feature_vector: dict | None = None,
        position_state: dict | None = None,
        risk_state: dict | None = None,
        trade_memory: list[dict] | None = None,
        daily_review: dict | None = None,
    ) -> LLMContext:
        return LLMContext(
            symbol=symbol,
            market_state=market_state or {},
            feature_vector=feature_vector or {},
            position_state=position_state or {},
            risk_state=risk_state or {},
            trade_memory=trade_memory or [],
            daily_review=daily_review or {},
        )

    def render_prompt(self, ctx: LLMContext) -> str:
        return (
            f"You are a crypto market analyst. Return JSON only. Symbol: {ctx.symbol}\n"
            f"MarketState: {ctx.market_state}\nFeatures: {ctx.feature_vector}\n"
            f"Risk: {ctx.risk_state}\n"
            "Output keys: direction, confidence, risk_level, reason_codes, invalid_conditions."
        )


def parse_llm_output(payload: dict) -> LLMOutput:
    return LLMOutput(**payload)
