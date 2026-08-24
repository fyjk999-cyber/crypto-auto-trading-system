from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from crypto_trader.domain.money import D


class RiskLevel(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


@dataclass
class RiskLevelInput:
    leverage: Decimal
    position_notional: Decimal
    nav: Decimal
    trade_risk_equity_pct: Decimal
    portfolio_gross_exposure_pct: Decimal
    extreme_market: bool = False
    drawdown_stress: bool = False
    exchange_abnormal: bool = False
    liquidity_abnormal: bool = False
    manual_policy_trigger: bool = False


class TradeRiskClassifier:
    def classify(self, inp: RiskLevelInput) -> RiskLevel:
        nav = D(inp.nav)
        lev = D(inp.leverage)
        pos_pct = D(inp.position_notional) / nav * D("100") if nav > 0 else D("999")
        trade_risk = D(inp.trade_risk_equity_pct)
        gross = D(inp.portfolio_gross_exposure_pct)
        if (
            inp.extreme_market
            or inp.drawdown_stress
            or inp.exchange_abnormal
            or inp.liquidity_abnormal
            or inp.manual_policy_trigger
            or lev >= D("6")
            or pos_pct >= D("25")
            or trade_risk >= D("3")
            or gross >= D("200")
        ):
            return RiskLevel.L4
        if lev >= D("4") or pos_pct >= D("15") or trade_risk >= D("2") or gross >= D("100"):
            return RiskLevel.L3
        if lev >= D("2") or pos_pct >= D("5"):
            return RiskLevel.L2
        return RiskLevel.L1
