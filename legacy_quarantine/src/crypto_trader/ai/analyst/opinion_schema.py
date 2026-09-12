"""AI market opinion schema."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AIMarketOpinion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    direction_bias: str  # LONG | SHORT | NEUTRAL
    confidence: float
    risk_level: str  # LOW | MEDIUM | HIGH
    timeframe: str
    reason_codes: list[str] = Field(default_factory=list)
    timestamp: str
