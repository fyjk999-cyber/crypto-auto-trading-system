"""Backtest validation report. Low-sample hypotheses stay EXPERIMENTAL."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class ValidationReport:
    trade_count: int
    win_rate: Decimal
    profit_factor: Decimal
    max_drawdown: Decimal
    sharpe: Decimal
    sortino: Decimal
    failure_cases: list[str]
    status: str  # EXPERIMENTAL | VALIDATED | REJECTED


def validate_hypothesis(
    *,
    trade_count: int,
    win_rate: Decimal,
    profit_factor: Decimal,
    max_drawdown: Decimal,
    sharpe: Decimal,
    sortino: Decimal,
    failure_cases: list[str],
) -> ValidationReport:
    status = "EXPERIMENTAL" if trade_count < 100 else "VALIDATED"
    if status == "VALIDATED" and (
        win_rate < Decimal("0.45") or profit_factor < Decimal("1.0") or max_drawdown > Decimal("20")
    ):
        status = "REJECTED"
    return ValidationReport(
        trade_count=trade_count,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        sharpe=sharpe,
        sortino=sortino,
        failure_cases=failure_cases,
        status=status,
    )
