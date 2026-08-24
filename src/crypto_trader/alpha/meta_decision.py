from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from crypto_trader.alpha.sub_strategy.base import AlphaSide


class MetaDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    ts: datetime
    version: str
    side: AlphaSide
    confidence: Decimal
    reason_codes: list[str] = Field(default_factory=list)
    effective_weights: dict[str, Decimal] = Field(default_factory=dict)
    vote_scores: dict[str, Decimal] = Field(default_factory=dict)
    regime: str | None = None
    alpha_version: str = "phase16.0.1"
    run_id: str | None = None
