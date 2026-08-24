from datetime import UTC, datetime, timedelta

from crypto_trader.domain.enums import ExecutionDecision
from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.execution.cross_exchange_guard import (
    CrossExchangeExecutionGuard,
    ExecutionQuote,
)


def quote(provider, mid, mark, ts):
    from decimal import Decimal as Dec

    mid = Dec(str(mid))
    mark = Dec(str(mark))
    return ExecutionQuote(
        provider=provider,
        symbol="BTCUSDT",
        mid_price=mid,
        mark_price=mark,
        best_bid=mid - Dec("1"),
        best_ask=mid + Dec("1"),
        timestamp=ts,
    )


def test_symbol_mapper_binance_okx_canonical():
    mapper = SymbolMapper()
    assert mapper.to_binance("BTCUSDT") == "BTCUSDT"
    assert mapper.to_okx("BTCUSDT") == "BTC-USDT-SWAP"
    assert mapper.to_canonical("BTC-USDT-SWAP") == "BTCUSDT"


def test_cross_exchange_guard_pass_warn_reduce_reject():
    now = datetime.now(UTC)
    guard = CrossExchangeExecutionGuard()
    signal = quote("BINANCE", 100, 100, now)
    ok = quote("OKX", 100.02, 100.01, now)
    assert guard.evaluate(signal, ok).decision == ExecutionDecision.APPROVE
    ok = quote("OKX", 100.15, 100.10, now)
    decision = guard.evaluate(signal, ok)
    assert decision.decision == ExecutionDecision.APPROVE
    assert any("WARN" in r for r in decision.reason_codes)
    ok = quote("OKX", 100.25, 100.20, now)
    assert guard.evaluate(signal, ok).decision == ExecutionDecision.HOLD
    ok = quote("OKX", 100.40, 100.35, now)
    assert guard.evaluate(signal, ok).decision == ExecutionDecision.REJECT


def test_cross_exchange_guard_stale_signal_or_execution():
    now = datetime.now(UTC)
    old = now - timedelta(seconds=6)
    guard = CrossExchangeExecutionGuard(max_age_seconds=5.0)
    signal = quote("BINANCE", 100, 100, old)
    ok = quote("OKX", 100, 100, now)
    assert guard.evaluate(signal, ok).decision == ExecutionDecision.REJECT
    signal = quote("BINANCE", 100, 100, now)
    ok = quote("OKX", 100, 100, old)
    assert guard.evaluate(signal, ok).decision == ExecutionDecision.REJECT
