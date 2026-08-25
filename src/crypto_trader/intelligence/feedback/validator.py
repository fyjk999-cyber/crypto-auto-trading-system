"""Feedback validator."""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_trader.intelligence.feedback.models import FeedbackValidation


class FeedbackValidator:
    def validate(
        self, *, feedback_id: str, feedback: dict, now: datetime | None = None
    ) -> FeedbackValidation:
        now = now or datetime.now(UTC)
        if not feedback.get("symbol"):
            return FeedbackValidation(feedback_id, "REJECT", "MISSING_SYMBOL")
        if not feedback.get("validated_factors"):
            return FeedbackValidation(feedback_id, "REJECT", "NO_VALIDATED_FACTORS")
        ts = feedback.get("timestamp")
        if ts:
            try:
                feedback_time = datetime.fromisoformat(ts)
                if abs((now - feedback_time).total_seconds()) > 3600:
                    return FeedbackValidation(feedback_id, "REJECT", "STALE_FEEDBACK")
            except Exception:
                return FeedbackValidation(feedback_id, "REJECT", "BAD_TIMESTAMP")
        if feedback.get("confidence", 0) <= 0:
            return FeedbackValidation(feedback_id, "REJECT", "ZERO_CONFIDENCE")
        return FeedbackValidation(feedback_id, "PASS", "OK")
