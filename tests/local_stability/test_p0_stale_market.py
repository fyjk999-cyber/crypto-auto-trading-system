from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.domain.enums import ExecutionDecision, OrderSide
from crypto_trader.execution.cross_exchange_guard import CrossExchangeExecutionGuard, ExecutionQuote
from crypto_trader.market_data.new_risk_gate import can_add_risk, new_risk_blocked_for_action
from crypto_trader.market_data.state import DataHealth, MarketState, SourceStatus


def healthy_state(now):
    state = MarketState(
        symbol="BTC-USDT-SWAP",
        timestamp=now,
        price=Decimal("100"),
        mark_price=Decimal("100"),
        index_price=Decimal("100"),
        best_bid=Decimal("99.9"),
        best_ask=Decimal("100.1"),
        health=DataHealth.HEALTHY,
        freshness=DataHealth.HEALTHY,
        generation=1,
    )
    state.sources["orderbook"] = SourceStatus(
        source="OKX", status=DataHealth.HEALTHY, age_seconds=0, updated_at=now
    )
    state.sources["mark_price"] = SourceStatus(
        source="OKX", status=DataHealth.HEALTHY, age_seconds=0, updated_at=now
    )
    state.sources["ticker"] = SourceStatus(
        source="OKX", status=DataHealth.HEALTHY, age_seconds=0, updated_at=now
    )
    state.sources["index_price"] = SourceStatus(
        source="OKX", status=DataHealth.HEALTHY, age_seconds=0, updated_at=now
    )
    state.mark_healthy_from_sources()
    return state


def test_stale_orderbook_blocks_new_risk_allows_reduce_close():
    now = datetime.now(UTC)
    state = healthy_state(now)
    assert state.new_risk_allowed is True
    # simulate provider failure invalidates immediately
    state.invalidate("ORDERBOOK_UNAVAILABLE")
    assert state.new_risk_allowed is False
    assert state.generation > 1
    allowed, reason = can_add_risk(state)
    assert allowed is False
    assert reason == "MARKET_DATA_UNAVAILABLE"


def test_new_risk_blocked_reduce_close_allowed_by_action():
    now = datetime.now(UTC)
    state = healthy_state(now)
    state.invalidate("ORDERBOOK_STALE")
    assert new_risk_blocked_for_action(state, OrderSide.BUY, Decimal("0"))[0] is True
    assert new_risk_blocked_for_action(state, OrderSide.SELL, Decimal("0"))[0] is True
    assert new_risk_blocked_for_action(state, OrderSide.BUY, Decimal("0.1"))[0] is True
    assert new_risk_blocked_for_action(state, OrderSide.SELL, Decimal("-0.1"))[0] is True
    # reduce/close allowed
    assert new_risk_blocked_for_action(state, OrderSide.SELL, Decimal("0.1"))[0] is False
    assert new_risk_blocked_for_action(state, OrderSide.BUY, Decimal("-0.1"))[0] is False


def test_recovery_requires_fresh_observations():
    now = datetime.now(UTC)
    state = healthy_state(now)
    state.invalidate("PROVIDER_FAILURE")
    # reconnect with no fresh snapshot yet -> still blocked
    assert can_add_risk(state)[0] is False
    fresh = healthy_state(now + timedelta(seconds=30))
    assert can_add_risk(fresh)[0] is True


def test_same_exchange_guard_rejects_stale_wide_spread():
    now = datetime.now(UTC)
    guard = CrossExchangeExecutionGuard()
    quote = ExecutionQuote(
        provider="OKX",
        symbol="BTC-USDT-SWAP",
        mid_price=Decimal("100"),
        mark_price=Decimal("100"),
        best_bid=Decimal("99"),
        best_ask=Decimal("101"),
        timestamp=now - timedelta(seconds=30),
    )
    decision = guard.evaluate_same_exchange(quote)
    assert decision.decision == ExecutionDecision.REJECT
    assert "EXECUTION_QUOTE_STALE" in decision.reason_codes
    wide = ExecutionQuote(
        provider="OKX",
        symbol="BTC-USDT-SWAP",
        mid_price=Decimal("100"),
        mark_price=Decimal("100"),
        best_bid=Decimal("90"),
        best_ask=Decimal("110"),
        timestamp=now,
    )
    decision2 = guard.evaluate_same_exchange(wide)
    assert decision2.decision == ExecutionDecision.REJECT
    assert "SPREAD_TOO_WIDE" in decision2.reason_codes


def test_cross_exchange_mode_still_works():
    now = datetime.now(UTC)
    guard = CrossExchangeExecutionGuard()
    signal = ExecutionQuote(
        provider="BINANCE_USDM",
        symbol="BTCUSDT",
        mid_price=Decimal("100"),
        mark_price=Decimal("100"),
        best_bid=Decimal("99"),
        best_ask=Decimal("101"),
        timestamp=now,
    )
    ok = ExecutionQuote(
        provider="OKX",
        symbol="BTC-USDT-SWAP",
        mid_price=Decimal("100.4"),
        mark_price=Decimal("100.35"),
        best_bid=Decimal("99.4"),
        best_ask=Decimal("101.4"),
        timestamp=now,
    )
    decision = guard.evaluate(signal, ok)
    assert decision.decision == ExecutionDecision.REJECT
    assert "CROSS_EXCHANGE_GAP_REJECT" in decision.reason_codes
