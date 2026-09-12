"""DeepSeek JSON output schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MarketOpinion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    direction: str  # LONG | SHORT | WATCH | NO_TRADE
    confidence: float
    timeframe: str
    reasoning: str
    risk_level: str  # LOW | MEDIUM | HIGH
    invalid_conditions: list[str] = Field(default_factory=list)


class AssetScore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    direction: str
    score: int
    reasoning: str


class CapitalReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    decision: str  # APPROVE | ADJUST | REJECT
    risk_level: str
    recommended_size: float
    recommended_leverage: float
    reasoning: str


class LearningRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    prediction: str
    result: str
    mistake: str
    lesson: str
