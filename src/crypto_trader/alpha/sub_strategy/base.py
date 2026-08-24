"""Alpha sub-strategy contract. LONG/SHORT symmetric, NO_TRADE is first-class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from crypto_trader.alpha.features import FeatureSnapshot
from crypto_trader.alpha.regime import RegimeOutput


class AlphaSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"


@dataclass
class AlphaSignal:
    strategy: str
    version: str
    symbol: str
    ts: datetime
    side: AlphaSide
    confidence: Decimal
    reason_codes: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class AlphaContext:
    symbol: str
    ts: datetime
    feature: FeatureSnapshot
    regime: RegimeOutput
    run_id: str | None = None


class AlphaSubStrategy(ABC):
    name: str = "base"
    version: str = "0.1.0"

    @abstractmethod
    def evaluate(self, ctx: AlphaContext) -> AlphaSignal:
        raise NotImplementedError

    def _signal(
        self,
        ctx: AlphaContext,
        side: AlphaSide,
        confidence: Decimal,
        reasons: list[str],
        metadata: dict | None = None,
    ) -> AlphaSignal:
        return AlphaSignal(
            strategy=self.name,
            version=self.version,
            symbol=ctx.symbol,
            ts=ctx.ts,
            side=side,
            confidence=confidence,
            reason_codes=reasons,
            metadata=metadata or {},
        )
