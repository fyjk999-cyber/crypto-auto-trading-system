from datetime import UTC, datetime, timedelta

from crypto_trader.domain.enums import ExecutionDecision, OrderSide, OrderStatus, TradingMode
from crypto_trader.domain.models import Instrument, OrderIntent, RiskDecision
from crypto_trader.execution.authority import AuthorizationContext, ExecutionAuthority
from crypto_trader.execution.rate_limiter import RateLimiter
from crypto_trader.risk.kill_switch import KillSwitch


def ctx(**kw):
    base = dict(
        now=datetime.now(UTC),
        trading_mode=TradingMode.PAPER,
        live_enabled=False,
        lease_held=True,
        kill_switch=KillSwitch(False),
        order_status=OrderStatus.CREATED,
        market_data_fresh=True,
        orderbook_fresh=True,
        orderbook_healthy=True,
        symbol_tradeable=True,
        exchange_connected=True,
        balance_fresh=True,
        risk_decision=RiskDecision(
            risk_decision_id="r1",
            client_order_id="c1",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            decision=ExecutionDecision.APPROVE,
            reason="RISK_PASS",
            checks={},
            timestamp=datetime.now(UTC),
        ),
        instrument=Instrument(
            symbol="BTCUSDT",
            base_asset="BTC",
            quote_asset="USDT",
            tick_size="0.01",
            step_size="0.001",
            min_qty="0.001",
            min_notional="5",
        ),
        rate_limiter=RateLimiter(100, 10),
    )
    base.update(kw)
    return AuthorizationContext(**base)


def make_intent():
    return OrderIntent(
        client_order_id="c1", symbol="BTCUSDT", side=OrderSide.BUY, price="100.01", quantity="0.1"
    )


async def test_authority_approves_clean_order():
    decision, notes = await ExecutionAuthority().authorize(make_intent(), ctx())
    assert decision == ExecutionDecision.APPROVE
    assert notes == ["AUTHORITY_PASS"]


async def test_kill_switch_rejects():
    ks = KillSwitch(True)
    decision, notes = await ExecutionAuthority().authorize(make_intent(), ctx(kill_switch=ks))
    assert decision == ExecutionDecision.REJECT
    assert "GLOBAL_KILL_SWITCH" in notes


async def test_lease_not_held_rejects():
    decision, _ = await ExecutionAuthority().authorize(make_intent(), ctx(lease_held=False))
    assert decision == ExecutionDecision.REJECT


async def test_live_requires_live_enabled():
    decision, _ = await ExecutionAuthority().authorize(
        make_intent(), ctx(trading_mode=TradingMode.LIVE, live_enabled=False)
    )
    assert decision == ExecutionDecision.REJECT


async def test_stale_market_data_holds():
    decision, _ = await ExecutionAuthority().authorize(make_intent(), ctx(market_data_fresh=False))
    assert decision == ExecutionDecision.HOLD


async def test_unhealthy_orderbook_holds():
    decision, _ = await ExecutionAuthority().authorize(make_intent(), ctx(orderbook_healthy=False))
    assert decision == ExecutionDecision.HOLD


async def test_duplicate_client_order_holds():
    decision, _ = await ExecutionAuthority().authorize(
        make_intent(), ctx(duplicate_client_order=True)
    )
    assert decision == ExecutionDecision.HOLD


async def test_price_precision_rejects():
    decision, _ = await ExecutionAuthority().authorize(
        OrderIntent(
            client_order_id="c1",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price="100.001",
            quantity="0.01",
        ),
        ctx(),
    )
    assert decision == ExecutionDecision.REJECT


async def test_min_quantity_rejects():
    decision, _ = await ExecutionAuthority().authorize(
        OrderIntent(
            client_order_id="c1",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price="100.01",
            quantity="0.0001",
        ),
        ctx(),
    )
    assert decision == ExecutionDecision.REJECT


async def test_expired_order_rejects():
    past = datetime.now(UTC) - timedelta(seconds=1)
    intent = make_intent()
    intent.expires_at = past
    decision, _ = await ExecutionAuthority().authorize(intent, ctx())
    assert decision == ExecutionDecision.REJECT


async def test_rate_limit_budget_holds():
    decision, _ = await ExecutionAuthority().authorize(
        make_intent(), ctx(rate_limiter=RateLimiter(0, 0))
    )
    assert decision == ExecutionDecision.HOLD
