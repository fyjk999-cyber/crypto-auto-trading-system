"""Trade review engine."""

from __future__ import annotations

from crypto_trader.ai_brain.models.schemas import TradeReviewReport


class TradeReviewEngine:
    def review(
        self,
        *,
        symbol: str,
        why_buy: str,
        why_hold: str,
        why_sell: str,
        result: str,
        ignored: list[str] | None = None,
    ) -> TradeReviewReport:
        correct = []
        wrong = []
        if result == "WIN":
            correct = ["entry logic", "hold discipline"]
        else:
            wrong = ["entry logic or exit timing"]
        return TradeReviewReport(
            symbol=symbol,
            why_buy=why_buy,
            why_hold=why_hold,
            why_sell=why_sell,
            correct_decisions=correct,
            wrong_decisions=wrong,
            ignored_information=ignored or [],
        )
