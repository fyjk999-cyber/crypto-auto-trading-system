"""AI skill scoring."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SkillScore:
    market_skill: float
    strategy_skill: float
    risk_skill: float
    coin_skill: float
    calibration_skill: float
    overall: float


class SkillEvaluator:
    def evaluate(
        self,
        *,
        regime_accuracy: float,
        direction_accuracy: float,
        strategy_win_rate: float,
        drawdown_score: float,
        coin_profile_accuracy: float,
        calibration_error: float,
    ) -> SkillScore:
        market = 0.5 * regime_accuracy + 0.5 * direction_accuracy
        strategy = strategy_win_rate
        risk = drawdown_score
        coin = coin_profile_accuracy
        calibration = max(0.0, 1.0 - calibration_error)
        overall = 0.25 * market + 0.25 * strategy + 0.2 * risk + 0.15 * coin + 0.15 * calibration
        return SkillScore(
            round(market, 3),
            round(strategy, 3),
            round(risk, 3),
            round(coin, 3),
            round(calibration, 3),
            round(overall, 3),
        )
