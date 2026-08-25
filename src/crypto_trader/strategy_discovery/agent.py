"""Strategy discovery agent. Proposals only."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StrategyHypothesis:
    hypothesis_id: str
    hypothesis: str
    affected_symbols: list[str]
    affected_regime: str
    expected_improvement: str
    risk: str
    validation_plan: list[str] = field(default_factory=list)
    status: str = "PROPOSED"


class StrategyDiscoveryAgent:
    def discover(
        self, hypothesis_id: str, symbol: str, regime: str, failure_pattern: str
    ) -> StrategyHypothesis:
        return StrategyHypothesis(
            hypothesis_id=hypothesis_id,
            hypothesis=f"Improve {failure_pattern} for {symbol} in {regime}",
            affected_symbols=[symbol],
            affected_regime=regime,
            expected_improvement="reduce false breakout by 15%",
            risk="change entry confirmation only",
            validation_plan=["BACKTEST", "OOS", "WALK_FORWARD", "PAPER", "SHADOW"],
        )
