"""AI Trading Brain schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class MarketSituation:
    market_state: str
    opportunities: list[str]
    risks: list[str]
    uncertainties: list[str]
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "market_state": self.market_state,
            "opportunities": self.opportunities,
            "risks": self.risks,
            "uncertainties": self.uncertainties,
            "timestamp": self.timestamp,
        }


@dataclass
class TradingThesis:
    symbol: str
    direction: str
    thesis: str
    supporting_evidence: list[str]
    contradicting_evidence: list[str]
    confidence: float
    invalid_conditions: list[str]
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "thesis": self.thesis,
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "confidence": self.confidence,
            "invalid_conditions": self.invalid_conditions,
            "timestamp": self.timestamp,
        }


@dataclass
class TradingIntent:
    symbol: str
    action: str  # OPEN_LONG|OPEN_SHORT|HOLD|REDUCE|EXIT|NO_TRADE
    confidence: float
    thesis: str
    evidence: list[str]
    risks: list[str]
    invalid_conditions: list[str]
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "confidence": self.confidence,
            "thesis": self.thesis,
            "evidence": self.evidence,
            "risks": self.risks,
            "invalid_conditions": self.invalid_conditions,
            "timestamp": self.timestamp,
        }


@dataclass
class PositionDecision:
    symbol: str
    action: str  # HOLD|ADD|REDUCE|EXIT
    reason: str
    confidence: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "reason": self.reason,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


@dataclass
class ExitReasoning:
    symbol: str
    reason: str
    category: (
        str  # THESIS_INVALIDATED|RISK_INCREASED|OPPORTUNITY_CHANGED|PROFIT_PROTECTION|TIME_DECAY
    )
    confidence: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "reason": self.reason,
            "category": self.category,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


@dataclass
class TradeReviewReport:
    symbol: str
    why_buy: str
    why_hold: str
    why_sell: str
    correct_decisions: list[str]
    wrong_decisions: list[str]
    ignored_information: list[str]
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "why_buy": self.why_buy,
            "why_hold": self.why_hold,
            "why_sell": self.why_sell,
            "correct_decisions": self.correct_decisions,
            "wrong_decisions": self.wrong_decisions,
            "ignored_information": self.ignored_information,
            "timestamp": self.timestamp,
        }
