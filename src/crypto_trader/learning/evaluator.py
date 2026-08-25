"""Trade evaluator."""

from __future__ import annotations

from crypto_trader.learning.review import TradeReview


class TradeEvaluator:
    def evaluate(
        self,
        *,
        symbol: str,
        entry_reason: str,
        exit_reason: str,
        was_win: bool,
        mistakes: list[str] | None = None,
        lessons: list[str] | None = None,
    ) -> TradeReview:
        return TradeReview(
            symbol=symbol,
            entry_reason=entry_reason,
            exit_reason=exit_reason,
            prediction_accuracy=1.0 if was_win else 0.0,
            decision_quality=0.8 if was_win else 0.4,
            mistakes=mistakes or [],
            lessons=lessons or [],
        )
