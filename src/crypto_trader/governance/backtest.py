"""Backtest V2: deterministic bar replay using real MarketDataEngine features."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.alpha.features import compute_features
from crypto_trader.alpha.market_data_engine import MarketDataEngine
from crypto_trader.alpha.regime import RegimeEngine
from crypto_trader.alpha.sub_strategy.base import AlphaContext
from crypto_trader.domain.money import D


@dataclass
class BacktestMetrics:
    cagr: Decimal = Decimal("0")
    sharpe: Decimal = Decimal("0")
    sortino: Decimal = Decimal("0")
    max_drawdown: Decimal = Decimal("0")
    calmar: Decimal = Decimal("0")
    profit_factor: Decimal = Decimal("0")
    win_rate: Decimal = Decimal("0")
    expectancy: Decimal = Decimal("0")
    average_r: Decimal = Decimal("0")
    long_contribution: Decimal = Decimal("0")
    short_contribution: Decimal = Decimal("0")
    funding_impact: Decimal = Decimal("0")
    fees_impact: Decimal = Decimal("0")
    turnover: int = 0


class BacktestEngine:
    def __init__(self, strategy, fee_rate: str = "0.0005", slippage: str = "0.0002") -> None:
        self.strategy = strategy
        self.fee_rate = D(fee_rate)
        self.slippage = D(slippage)

    def run(
        self, prices: list[Decimal], initial_equity: Decimal = Decimal("10000")
    ) -> BacktestMetrics:
        if len(prices) < 60:
            return BacktestMetrics()
        mde = MarketDataEngine("BTCUSDT")
        regime_engine = RegimeEngine()
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        equity = D(initial_equity)
        peak = equity
        max_dd = D("0")
        returns: list[Decimal] = []
        pnl_list: list[Decimal] = []
        long_pnl = D("0")
        short_pnl = D("0")
        fees = D("0")
        turnover = 0
        position_side = None
        entry_price = D("0")
        for i, price in enumerate(prices):
            ts = ts + __import__("datetime").timedelta(minutes=1)
            mde.ingest(ts, price, Decimal("10"))
            if i < 59:
                continue
            feature = compute_features(mde, "BTCUSDT", ts)
            regime = regime_engine.classify(feature)
            ctx = AlphaContext(symbol="BTCUSDT", ts=ts, feature=feature, regime=regime)
            signal = self.strategy.evaluate(ctx)
            if signal.side.value == "LONG" and position_side != "LONG":
                if position_side is not None:
                    pnl = (price * (D("1") - self.slippage) - entry_price) * D("1")
                    equity += pnl
                    pnl_list.append(pnl)
                    if position_side == "LONG":
                        long_pnl += pnl
                    else:
                        short_pnl += pnl
                    fees += price * self.fee_rate
                    turnover += 1
                entry_price = price * (D("1") + self.slippage)
                position_side = "LONG"
                fees += entry_price * self.fee_rate
                turnover += 1
            elif signal.side.value == "SHORT" and position_side != "SHORT":
                if position_side is not None:
                    pnl = (entry_price - price * (D("1") + self.slippage)) * D("1")
                    equity += pnl
                    pnl_list.append(pnl)
                    if position_side == "LONG":
                        long_pnl += pnl
                    else:
                        short_pnl += pnl
                    fees += price * self.fee_rate
                    turnover += 1
                entry_price = price * (D("1") - self.slippage)
                position_side = "SHORT"
                fees += entry_price * self.fee_rate
                turnover += 1
            if position_side is not None:
                mark = (price - entry_price) if position_side == "LONG" else (entry_price - price)
                ret = mark / entry_price
                returns.append(ret)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else D("0")
            if dd > max_dd:
                max_dd = dd
        if position_side is not None:
            price = prices[-1]
            pnl = (price - entry_price) if position_side == "LONG" else (entry_price - price)
            equity += pnl
            pnl_list.append(pnl)
            if position_side == "LONG":
                long_pnl += pnl
            else:
                short_pnl += pnl
            fees += price * self.fee_rate
            turnover += 1
        wins = [p for p in pnl_list if p > 0]
        losses = [-p for p in pnl_list if p < 0]
        metrics = BacktestMetrics()
        if pnl_list:
            metrics.win_rate = Decimal(len(wins)) / Decimal(len(pnl_list))
            metrics.profit_factor = (
                sum(wins, Decimal("0")) / sum(losses, Decimal("0"))
                if losses and sum(losses, Decimal("0")) > 0
                else Decimal("999")
            )
            metrics.expectancy = sum(pnl_list, Decimal("0")) / Decimal(len(pnl_list))
            metrics.average_r = metrics.expectancy
        if returns:
            avg = sum(returns, Decimal("0")) / Decimal(len(returns))
            var = (
                sum((r - avg) ** 2 for r in returns) / Decimal(len(returns) - 1)
                if len(returns) > 1
                else D("0")
            )
            std = var.sqrt() if var > 0 else D("0")
            metrics.sharpe = avg / std * Decimal(len(returns)).sqrt() if std > 0 else D("0")
            downside = [r for r in returns if r < 0]
            if downside:
                dvar = sum((r**2) for r in downside) / Decimal(len(downside))
                metrics.sortino = (
                    avg / dvar.sqrt() * Decimal(len(returns)).sqrt() if dvar > 0 else D("0")
                )
        metrics.max_drawdown = max_dd
        metrics.long_contribution = long_pnl
        metrics.short_contribution = short_pnl
        metrics.fees_impact = fees
        metrics.turnover = turnover
        return metrics
