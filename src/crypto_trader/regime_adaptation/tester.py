"""Market regime adaptation test."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AdaptationResult:
    regime_transition: str
    reduced_trading: bool
    adjusted_strategy: bool
    lowered_risk: bool
    portfolio_changed: bool


class RegimeAdaptationTester:
    def test(
        self,
        *,
        from_regime: str,
        to_regime: str,
        trade_count_change_pct: float,
        strategy_change: bool,
        risk_change: bool,
        portfolio_change: bool,
    ) -> AdaptationResult:
        return AdaptationResult(
            regime_transition=f"{from_regime}->{to_regime}",
            reduced_trading=trade_count_change_pct < -0.2,
            adjusted_strategy=strategy_change,
            lowered_risk=risk_change,
            portfolio_changed=portfolio_change,
        )
