from decimal import Decimal

from crypto_trader.domain.enums import ExecutionDecision, OrderSide
from crypto_trader.domain.models import Account, Position, SignalIntent
from crypto_trader.risk.engine import RiskConfig, RiskEngine
from crypto_trader.risk.kill_switch import KillSwitch


def make_signal(qty="1"):
    return SignalIntent(
        signal_id="sig_1",
        strategy_id="test",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=qty,
        limit_price="100",
    )


def make_account(equity="10000"):
    return Account(balances={}, equity=Decimal(equity))


def test_risk_approves_normal_order():
    engine = RiskEngine()
    decision = engine.check(
        make_signal(),
        account=make_account(),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
    )
    assert decision.decision == ExecutionDecision.APPROVE


def test_kill_switch_blocks_everything():
    ks = KillSwitch()
    ks.engage("emergency")
    engine = RiskEngine(kill_switch=ks)
    decision = engine.check(
        make_signal(),
        account=make_account(),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
    )
    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "GLOBAL_KILL_SWITCH"


def test_max_order_notional_rejects():
    config = RiskConfig(max_order_notional=Decimal("10"))
    engine = RiskEngine(config)
    decision = engine.check(
        make_signal(qty="1"),
        account=make_account(),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
    )
    assert decision.decision == ExecutionDecision.SCALE_DOWN
    assert decision.reason == "MAX_ORDER_NOTIONAL"
    assert decision.side == OrderSide.BUY
    assert decision.checks["original_quantity"] == "1"
    assert decision.checks["approved_quantity"] == "0.1"


def test_max_open_orders_rejects():
    config = RiskConfig(max_open_orders=3)
    engine = RiskEngine(config)
    decision = engine.check(
        make_signal(),
        account=make_account(),
        positions={},
        market_price=Decimal("100"),
        open_order_count=3,
    )
    assert decision.reason == "MAX_OPEN_ORDERS"


def test_max_daily_loss_rejects():
    config = RiskConfig(max_daily_loss=Decimal("50"))
    engine = RiskEngine(config)
    decision = engine.check(
        make_signal(),
        account=make_account(),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        daily_pnl=Decimal("-51"),
    )
    assert decision.reason == "MAX_DAILY_LOSS"


def test_max_symbol_exposure_rejects():
    config = RiskConfig(max_symbol_exposure=Decimal("90"))
    engine = RiskEngine(config)
    pos = Position(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("1"),
        avg_entry_price=Decimal("80"),
        cost_basis=Decimal("80"),
    )
    decision = engine.check(
        make_signal(qty="0.2"),
        account=make_account(),
        positions={"BTCUSDT": pos},
        market_price=Decimal("100"),
        open_order_count=0,
    )
    assert decision.reason == "MAX_SYMBOL_EXPOSURE"


def test_consecutive_failures_rejects():
    config = RiskConfig(max_consecutive_failures=5)
    engine = RiskEngine(config)
    decision = engine.check(
        make_signal(),
        account=make_account(),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        consecutive_failures=5,
    )
    assert decision.reason == "MAX_CONSECUTIVE_FAILURES"
