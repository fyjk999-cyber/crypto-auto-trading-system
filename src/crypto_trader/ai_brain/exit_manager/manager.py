"""Exit reasoning system."""

from __future__ import annotations

from crypto_trader.ai_brain.models.schemas import ExitReasoning


class ExitManager:
    def reason(
        self,
        *,
        symbol: str,
        thesis_valid: bool,
        risk_increased: bool,
        better_opportunity: bool,
        profit_target_hit: bool,
        time_window_expired: bool,
    ) -> ExitReasoning | None:
        if not thesis_valid:
            return ExitReasoning(symbol, "thesis invalidated", "THESIS_INVALIDATED", 0.85)
        if risk_increased:
            return ExitReasoning(symbol, "risk increased", "RISK_INCREASED", 0.75)
        if better_opportunity:
            return ExitReasoning(symbol, "better opportunity", "OPPORTUNITY_CHANGED", 0.65)
        if profit_target_hit:
            return ExitReasoning(symbol, "protect profit", "PROFIT_PROTECTION", 0.6)
        if time_window_expired:
            return ExitReasoning(symbol, "time window expired", "TIME_DECAY", 0.55)
        return None
