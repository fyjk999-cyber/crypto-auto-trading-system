"""Long-term performance metrics."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class LongTermMetrics:
    trade_count: int = 0
    roi: Decimal = Decimal("0")
    profit_factor: Decimal = Decimal("0")
    sharpe: Decimal = Decimal("0")
    sortino: Decimal = Decimal("0")
    max_drawdown: Decimal = Decimal("0")
    recovery_factor: Decimal = Decimal("0")
    win_rate: Decimal = Decimal("0")
    average_win: Decimal = Decimal("0")
    average_loss: Decimal = Decimal("0")
    direction_accuracy: Decimal = Decimal("0")
    long_accuracy: Decimal = Decimal("0")
    short_accuracy: Decimal = Decimal("0")
    confidence_calibration: Decimal = Decimal("0")
    prediction_drift: Decimal = Decimal("0")
    uptime_pct: Decimal = Decimal("0")
    api_latency_ms: float = 0.0
    data_freshness: Decimal = Decimal("0")
    execution_latency_ms: float = 0.0


def compute_longterm_metrics(
    daily_returns: list[Decimal], predictions: list[dict] | None = None
) -> LongTermMetrics:
    if not daily_returns:
        return LongTermMetrics()
    returns = [D(r) for r in daily_returns]
    equity = Decimal("1")
    peak = Decimal("1")
    max_dd = Decimal("0")
    equity_curve = []
    for r in returns:
        equity *= 1 + r
        equity_curve.append(equity)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
    roi = (equity - Decimal("1")) * D("100")
    avg = sum(returns, D("0")) / Decimal(len(returns))
    std = (sum((r - avg) ** 2 for r in returns) / Decimal(len(returns))).sqrt()
    sharpe = avg / std * Decimal(len(returns)).sqrt() if std > 0 else D("0")
    downside = [r for r in returns if r < 0]
    dstd = (sum((r**2) for r in downside) / Decimal(len(downside))).sqrt() if downside else D("0")
    sortino = avg / dstd * Decimal(len(returns)).sqrt() if dstd > 0 else D("0")
    wins = [r for r in returns if r > 0]
    losses = [-r for r in returns if r < 0]
    pf = sum(wins, D("0")) / sum(losses, D("0")) if losses and sum(losses, D("0")) > 0 else D("999")
    recovery = roi / (max_dd * D("100")) if max_dd > 0 else D("999")
    predictions = predictions or []
    correct = sum(1 for p in predictions if p.get("result") == "CORRECT")
    accuracy = Decimal(correct) / Decimal(len(predictions)) if predictions else D("0")
    conf_cal = sum(
        (
            abs(Decimal(str(p.get("confidence", 0))) - Decimal(str(p.get("actual", 0))))
            for p in predictions
            if p.get("actual") is not None
        ),
        D("0"),
    )
    if predictions:
        conf_cal = conf_cal / Decimal(len(predictions))
    return LongTermMetrics(
        trade_count=len(returns),
        roi=roi,
        profit_factor=pf,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_dd * 100,
        recovery_factor=recovery,
        win_rate=Decimal(len(wins)) / Decimal(len(returns)),
        average_win=sum(wins, D("0")) / Decimal(len(wins)) if wins else D("0"),
        average_loss=sum(losses, D("0")) / Decimal(len(losses)) if losses else D("0"),
        direction_accuracy=accuracy,
        long_accuracy=accuracy,
        short_accuracy=accuracy,
        confidence_calibration=conf_cal,
        prediction_drift=conf_cal,
        uptime_pct=D("100"),
    )
