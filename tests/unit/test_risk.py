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


def test_reduce_only_can_lower_existing_exposure_to_exchange_limit_for_both_sides():
    engine = RiskEngine(RiskConfig(max_exchange_exposure=Decimal("100")))
    for position_quantity, order_side, direction in (
        (Decimal("2"), OrderSide.SELL, "LONG"),
        (Decimal("-2"), OrderSide.BUY, "SHORT"),
    ):
        position = Position(
            symbol="BTCUSDT",
            base_asset="BTC",
            quote_asset="USDT",
            quantity=position_quantity,
            avg_entry_price=Decimal("100"),
            cost_basis=Decimal("200"),
        )
        decision = engine.check(
            SignalIntent(
                signal_id=f"reduce-over-limit-{direction}",
                strategy_id="live_llm_position",
                symbol="BTCUSDT",
                side=order_side,
                quantity=Decimal("1"),
                limit_price=Decimal("100"),
                metadata={"reduce_only": True, "direction": direction},
            ),
            account=make_account(),
            positions={"BTCUSDT": position},
            market_price=Decimal("100"),
            open_order_count=0,
        )
        assert decision.decision == ExecutionDecision.APPROVE
        assert decision.checks["max_exchange_exposure"] is True


def test_reduce_only_can_decrease_risk_even_when_projected_exposure_remains_over_caps():
    engine = RiskEngine(
        RiskConfig(
            max_symbol_exposure=Decimal("100"),
            max_account_exposure=Decimal("100"),
            max_exchange_exposure=Decimal("100"),
            max_position_notional=Decimal("100"),
            max_leverage=Decimal("2"),
        )
    )
    position = Position(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("4"),
        avg_entry_price=Decimal("100"),
        cost_basis=Decimal("400"),
    )
    decision = engine.check(
        SignalIntent(
            signal_id="reduce-still-over-limits",
            strategy_id="live_llm_position",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("1"),
            limit_price=Decimal("100"),
            metadata={"reduce_only": True, "direction": "LONG"},
        ),
        account=make_account(equity="50"),
        positions={"BTCUSDT": position},
        market_price=Decimal("100"),
        open_order_count=0,
    )
    assert decision.decision == ExecutionDecision.APPROVE
    for check in (
        "max_symbol_exposure",
        "max_account_exposure",
        "max_exchange_exposure",
        "max_position_notional",
        "max_leverage",
    ):
        assert decision.checks[check] is True


def test_existing_symbol_exposure_is_valued_at_current_market_price():
    engine = RiskEngine(RiskConfig(max_symbol_exposure=Decimal("250")))
    position = Position(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("2"),
        avg_entry_price=Decimal("100"),
        cost_basis=Decimal("200"),
    )
    decision = engine.check(
        make_signal(qty="0.1").model_copy(update={"limit_price": Decimal("120")}),
        account=make_account(),
        positions={"BTCUSDT": position},
        market_price=Decimal("120"),
        open_order_count=0,
    )
    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "MAX_SYMBOL_EXPOSURE"
    assert decision.checks["existing_notional"] == "240"


def test_portfolio_exposure_uses_factual_prices_for_every_held_symbol():
    engine = RiskEngine(RiskConfig(max_account_exposure=Decimal("250")))
    positions = {
        "BTCUSDT": Position(
            symbol="BTCUSDT",
            base_asset="BTC",
            quote_asset="USDT",
            quantity=Decimal("1"),
            avg_entry_price=Decimal("100"),
            cost_basis=Decimal("100"),
        ),
        "ETHUSDT": Position(
            symbol="ETHUSDT",
            base_asset="ETH",
            quote_asset="USDT",
            quantity=Decimal("1"),
            avg_entry_price=Decimal("100"),
            cost_basis=Decimal("100"),
        ),
    }

    decision = engine.check(
        make_signal(qty="0.1"),
        account=make_account(),
        positions=positions,
        market_price=Decimal("100"),
        market_prices={"BTCUSDT": Decimal("100"), "ETHUSDT": Decimal("200")},
        open_order_count=0,
    )

    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason == "MAX_ACCOUNT_EXPOSURE"
    assert decision.checks["existing_notional"] == "300"


def test_risk_rejects_unknown_drawdown_instead_of_treating_it_as_zero():
    decision = RiskEngine().check(
        make_signal(),
        account=make_account(),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        drawdown=None,
    )
    assert decision.decision == ExecutionDecision.REJECT
    assert "DRAWDOWN_UNAVAILABLE" in str(decision.checks) or "DRAWDOWN_UNAVAILABLE" in str(decision.reason)
