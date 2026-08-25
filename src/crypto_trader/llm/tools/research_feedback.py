"""Research feedback LLM tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_trader.intelligence.context_adapter import AnalysisContextAdapter


@dataclass
class ResearchFeedbackToolResult:
    ok: bool
    data: dict | list
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class ResearchFeedbackTools:
    def __init__(self, feedback_interface=None) -> None:
        self.feedback_interface = feedback_interface
        self._adapter = AnalysisContextAdapter()

    async def get_research_feedback(self, symbol: str) -> ResearchFeedbackToolResult:
        if self.feedback_interface is None:
            return ResearchFeedbackToolResult(False, {}, "FEEDBACK_UNAVAILABLE")
        feedback = self.feedback_interface.get(symbol)
        if feedback is None:
            return ResearchFeedbackToolResult(True, {"symbol": symbol, "status": "NO_DATA"}, None)
        return ResearchFeedbackToolResult(True, feedback, None)

    async def get_factor_reliability_context(self, symbol: str) -> ResearchFeedbackToolResult:
        if self.feedback_interface is None:
            return ResearchFeedbackToolResult(False, {}, "FEEDBACK_UNAVAILABLE")
        feedback = self.feedback_interface.get(symbol) or {}
        return ResearchFeedbackToolResult(
            True,
            {
                "symbol": symbol,
                "trusted_factors": feedback.get("validated_factors", []),
                "weak_factors": [
                    f
                    for f in feedback.get("factor_confidence", {})
                    if f not in feedback.get("validated_factors", [])
                ],
            },
            None,
        )

    async def get_market_research_view(self, symbol: str) -> ResearchFeedbackToolResult:
        if self.feedback_interface is None:
            return ResearchFeedbackToolResult(False, {}, "FEEDBACK_UNAVAILABLE")
        feedback = self.feedback_interface.get(symbol) or {}
        return ResearchFeedbackToolResult(True, self._adapter.adapt(feedback), None)
