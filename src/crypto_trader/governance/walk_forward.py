from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class WalkForwardResult:
    parameter_stability: Decimal
    oos_degradation: Decimal
    regime_stability: Decimal
    strategy_stability: Decimal
    drawdown_stability: Decimal
    passed: bool = True


class WalkForward:
    def evaluate(
        self,
        is_sharpe: Decimal,
        oos_sharpe: Decimal,
        regimes_is: set,
        regimes_oos: set,
        strategies_is: set,
        strategies_oos: set,
        max_dd_is: Decimal,
        max_dd_oos: Decimal,
    ) -> WalkForwardResult:
        param_stability = D("1") - abs(is_sharpe - oos_sharpe) / max(abs(is_sharpe), D("0.01"))
        degradation = (is_sharpe - oos_sharpe) / max(abs(is_sharpe), D("0.01"))
        regime_stability = Decimal(len(regimes_is & regimes_oos)) / max(
            Decimal(len(regimes_is | regimes_oos)), D("1")
        )
        strategy_stability = Decimal(len(strategies_is & strategies_oos)) / max(
            Decimal(len(strategies_is | strategies_oos)), D("1")
        )
        dd_stability = D("1") - abs(max_dd_is - max_dd_oos) / max(abs(max_dd_is), D("0.01"))
        passed = degradation < D("0.3") and regime_stability >= D("0.5") and dd_stability > D("0.5")
        return WalkForwardResult(
            parameter_stability=max(param_stability, D("0")),
            oos_degradation=degradation,
            regime_stability=regime_stability,
            strategy_stability=strategy_stability,
            drawdown_stability=dd_stability,
            passed=passed,
        )
