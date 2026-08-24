"""Cross-exchange price guard between Binance reference and OKX execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.enums import ExecutionDecision
from crypto_trader.domain.money import D

# configurable defaults; never hardcode in Strategy
DEFAULT_WARN_BPS = D("10")
DEFAULT_REDUCE_BPS = D("20")
DEFAULT_REJECT_BPS = D("35")
DEFAULT_MAX_AGE_SECONDS = 5.0


@dataclass
class ExecutionQuote:
    provider: str
    symbol: str
    mid_price: Decimal
    mark_price: Decimal
    best_bid: Decimal
    best_ask: Decimal
    timestamp: datetime


@dataclass
class CrossExchangeDecision:
    decision: ExecutionDecision
    mid_deviation_bps: Decimal
    mark_deviation_bps: Decimal
    execution_slippage_bps: Decimal
    market_age_ms: float
    reason_codes: list[str]


class CrossExchangeExecutionGuard:
    def __init__(
        self,
        *,
        warn_bps: str = "10",
        reduce_bps: str = "20",
        reject_bps: str = "35",
        max_age_seconds: float = 5.0,
    ) -> None:
        self.warn_bps = D(warn_bps)
        self.reduce_bps = D(reduce_bps)
        self.reject_bps = D(reject_bps)
        self.max_age_seconds = max_age_seconds

    def evaluate(self, signal: ExecutionQuote, execution: ExecutionQuote) -> CrossExchangeDecision:
        reasons: list[str] = []
        now = datetime.now(UTC)
        signal_age = max(0.0, (now - signal.timestamp).total_seconds())
        execution_age = max(0.0, (now - execution.timestamp).total_seconds())

        def bps(a: Decimal, b: Decimal) -> Decimal:
            if b == 0:
                return D("999")
            return (a - b) / b * D("10000")

        signal_mid = (D(signal.best_bid) + D(signal.best_ask)) / D("2")
        exec_mid = (D(execution.best_bid) + D(execution.best_ask)) / D("2")
        mid_dev = bps(exec_mid, signal_mid)
        mark_dev = bps(D(execution.mark_price), D(signal.mark_price))
        exec_slippage = bps(abs(exec_mid - signal_mid), signal_mid)

        if signal_age > self.max_age_seconds:
            reasons.append("SIGNAL_DATA_STALE")
        if execution_age > self.max_age_seconds:
            reasons.append("EXECUTION_QUOTE_STALE")

        decision = ExecutionDecision.APPROVE
        if reasons:
            decision = ExecutionDecision.REJECT
        elif abs(mid_dev) >= self.reject_bps or abs(mark_dev) >= self.reject_bps:
            decision = ExecutionDecision.REJECT
            reasons.append("CROSS_EXCHANGE_GAP_REJECT")
        elif abs(mid_dev) >= self.reduce_bps or abs(mark_dev) >= self.reduce_bps:
            decision = ExecutionDecision.HOLD
            reasons.append("CROSS_EXCHANGE_GAP_REDUCE")
        elif abs(mid_dev) >= self.warn_bps or abs(mark_dev) >= self.warn_bps:
            reasons.append("CROSS_EXCHANGE_GAP_WARN")

        return CrossExchangeDecision(
            decision=decision,
            mid_deviation_bps=mid_dev,
            mark_deviation_bps=mark_dev,
            execution_slippage_bps=exec_slippage,
            market_age_ms=max(signal_age, execution_age) * 1000,
            reason_codes=reasons,
        )
