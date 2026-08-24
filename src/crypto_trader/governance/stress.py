from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class StressScenario:
    name: str
    price_shock: Decimal = Decimal("0")
    vol_multiplier: Decimal = Decimal("1")
    spread_multiplier: Decimal = Decimal("1")
    liquidity_haircut: Decimal = Decimal("0")
    funding_shock: Decimal = Decimal("0")
    oi_shock: Decimal = Decimal("0")
    correlation_shock: Decimal = Decimal("0")


@dataclass
class StressResult:
    scenario: str
    projected_equity: Decimal
    projected_drawdown: Decimal
    margin_ratio: Decimal
    liquidation_distance: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    available_margin: Decimal
    liquidation_risk: Decimal
    correlated_loss: Decimal
    passed: bool = True
    reason_codes: list[str] = field(default_factory=list)


DEFAULT_SCENARIOS = [
    StressScenario("price_down_3", price_shock=D("-0.03")),
    StressScenario("price_down_5", price_shock=D("-0.05")),
    StressScenario("price_down_8", price_shock=D("-0.08")),
    StressScenario("price_up_3", price_shock=D("0.03")),
    StressScenario("price_up_5", price_shock=D("0.05")),
    StressScenario("price_up_8", price_shock=D("0.08")),
    StressScenario("vol_x2", vol_multiplier=D("2")),
    StressScenario("spread_x3", spread_multiplier=D("3")),
    StressScenario("liquidity_minus_50", liquidity_haircut=D("0.5")),
    StressScenario("funding_shock", funding_shock=D("0.001")),
    StressScenario("oi_shock", oi_shock=D("0.2")),
    StressScenario("correlation_shock", correlation_shock=D("0.5")),
    StressScenario("market_gap", price_shock=D("-0.05"), liquidity_haircut=D("0.5")),
]


class ScenarioStressEngine:
    def __init__(self, scenarios: list[StressScenario] | None = None) -> None:
        self.scenarios = scenarios or DEFAULT_SCENARIOS

    def run(
        self,
        *,
        equity: Decimal,
        position_notional: Decimal,
        side: str,
        leverage: Decimal,
        maintenance_margin: Decimal,
        liquidation_distance: Decimal,
        gross_exposure_pct: Decimal,
        correlated_notional: Decimal,
    ) -> list[StressResult]:
        results = []
        for scenario in self.scenarios:
            shock = D(scenario.price_shock)
            if side == "LONG":
                pnl = D(position_notional) * shock * D(leverage)  # rough mark pnl
            elif side == "SHORT":
                pnl = -D(position_notional) * shock * D(leverage)
            else:
                pnl = D("0")
            projected_equity = D(equity) + pnl
            dd = -pnl / D(equity) if D(equity) > 0 else D("0")
            margin_ratio = (
                (projected_equity / D(maintenance_margin))
                if D(maintenance_margin) > 0
                else D("999")
            )
            liq_distance = D(liquidation_distance) - abs(shock) * D(leverage)
            correlated_loss = D(correlated_notional) * D(scenario.correlation_shock)
            liquidation_risk = D("1") if liq_distance <= 0 or margin_ratio < D("1") else D("0")
            available_margin = projected_equity - D(maintenance_margin)
            passed = liquidation_risk == 0 and available_margin > 0
            reasons = []
            if not passed:
                reasons.append("STRESS_FAIL")
            results.append(
                StressResult(
                    scenario=scenario.name,
                    projected_equity=projected_equity,
                    projected_drawdown=dd,
                    margin_ratio=margin_ratio,
                    liquidation_distance=liq_distance,
                    gross_exposure=D(gross_exposure_pct),
                    net_exposure=D(position_notional) / D(equity) * D("100")
                    if D(equity) > 0
                    else D("0"),
                    available_margin=available_margin,
                    liquidation_risk=liquidation_risk,
                    correlated_loss=correlated_loss,
                    passed=passed,
                    reason_codes=reasons,
                )
            )
        return results

    def risk_aware_resize(
        self, results: list[StressResult], position_notional: Decimal, leverage: Decimal
    ) -> tuple[Decimal, Decimal, bool]:
        if all(r.passed for r in results):
            return position_notional, leverage, True
        # reduce size and leverage, then re-run coarse policy: scale down by 0.6
        new_pos = D(position_notional) * D("0.6")
        new_lev = min(D(leverage), D("3"))
        return new_pos, new_lev, new_pos > 0
