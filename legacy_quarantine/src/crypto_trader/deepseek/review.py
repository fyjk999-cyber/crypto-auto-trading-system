"""AI self review after closed trades."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class AIReviewRecord:
    symbol: str
    prediction: str
    result: str
    mistake: str
    lesson: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def build_review(symbol: str, prediction: str, result: str) -> AIReviewRecord:
    if result == "WIN":
        mistake, lesson = "", "pattern confirmed"
    elif prediction == "LONG":
        mistake, lesson = "false long", "require trend confirmation"
    elif prediction == "SHORT":
        mistake, lesson = "false short", "require momentum confirmation"
    else:
        mistake, lesson = "missed opportunity", "reduce NO_TRADE bias"
    return AIReviewRecord(
        symbol=symbol, prediction=prediction, result=result, mistake=mistake, lesson=lesson
    )
