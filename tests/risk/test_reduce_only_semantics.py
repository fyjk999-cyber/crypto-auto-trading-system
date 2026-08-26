from decimal import Decimal

from crypto_trader.domain.enums import ExecutionDecision, OrderSide
from crypto_trader.domain.models import Account, Position, SignalIntent
from crypto_trader.risk.engine import RiskConfig, RiskEngine


def make_account(equity="100000"):
    return Account(account_id="default", equity=Decimal(equity))


def make_position(qty="1", avg="100", cost="100"):
    return Position(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal(qty),
        avg_entry_price=Decimal(avg),
        cost_basis=Decimal(cost),
    )


def make_signal(side, qty, reduce_only=False):
    return SignalIntent(
        signal_id="s1",
        strategy_id="ai_brain",
        symbol="BTCUSDT",
        side=side,
        quantity=qty,
        metadata={"reduce_only": reduce_only} if reduce_only else {},
    )


def test_reduce_only_exit_allowed_when_current_position_over_limit():
    engine = RiskEngine(
        RiskConfig(
            max_symbol_exposure=Decimal("50"),
            max_position_notional=Decimal("50"),
            max_account_exposure=Decimal("50"),
            max_leverage=Decimal("1"),
        )
    )
    signal = make_signal(OrderSide.SELL, "1.0", reduce_only=True)
    decision = engine.check(
        signal,
        account=make_account(),
        positions={"BTCUSDT": make_position("1", "100", "100")},
        market_price=Decimal("100"),
        open_order_count=0,
        current_signed_qty=Decimal("1"),
    )
    assert decision.decision == ExecutionDecision.APPROVE


def test_reduce_only_reduce_allowed_when_current_position_over_limit():
    engine = RiskEngine(
        RiskConfig(
            max_symbol_exposure=Decimal("50"),
            max_position_notional=Decimal("50"),
            max_account_exposure=Decimal("50"),
            max_leverage=Decimal("1"),
        )
    )
    signal = make_signal(OrderSide.SELL, "0.3", reduce_only=True)
    decision = engine.check(
        signal,
        account=make_account(),
        positions={"BTCUSDT": make_position("1", "100", "100")},
        market_price=Decimal("100"),
        open_order_count=0,
        current_signed_qty=Decimal("1"),
    )
    assert decision.decision == ExecutionDecision.APPROVE


def test_new_entry_rejected_when_position_over_limit():
    engine = RiskEngine(
        RiskConfig(
            max_symbol_exposure=Decimal("50"),
            max_position_notional=Decimal("50"),
            max_account_exposure=Decimal("50"),
            max_leverage=Decimal("1"),
        )
    )
    signal = make_signal(OrderSide.BUY, "0.1", reduce_only=False)
    decision = engine.check(
        signal,
        account=make_account(),
        positions={"BTCUSDT": make_position("1", "100", "100")},
        market_price=Decimal("100"),
        open_order_count=0,
        current_signed_qty=Decimal("1"),
    )
    assert decision.decision == ExecutionDecision.REJECT


def test_reduce_only_wrong_direction_rejected():
    engine = RiskEngine()
    signal = make_signal(OrderSide.BUY, "0.3", reduce_only=True)
    decision = engine.check(
        signal,
        account=make_account(),
        positions={"BTCUSDT": make_position("1", "100", "100")},
        market_price=Decimal("100"),
        open_order_count=0,
        current_signed_qty=Decimal("1"),
    )
    assert decision.decision == ExecutionDecision.REJECT
    assert decision.reason in (
        "REDUCE_ONLY_WRONG_DIRECTION",
        "REDUCE_ONLY_BUY_AGAINST_LONG_OR_FLAT",
    )


def test_reduce_only_without_position_rejected():
    engine = RiskEngine()
    signal = make_signal(OrderSide.SELL, "0.3", reduce_only=True)
    decision = engine.check(
        signal,
        account=make_account(),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
        current_signed_qty=Decimal("0"),
    )
    assert decision.decision == ExecutionDecision.REJECT


def test_reduce_only_quantity_exceeds_position_rejected():
    engine = RiskEngine()
    signal = make_signal(OrderSide.SELL, "2.0", reduce_only=True)
    decision = engine.check(
        signal,
        account=make_account(),
        positions={"BTCUSDT": make_position("1", "100", "100")},
        market_price=Decimal("100"),
        open_order_count=0,
        current_signed_qty=Decimal("1"),
    )
    assert decision.decision == ExecutionDecision.REJECT


def test_long_reduce_projected_exposure_decreases():
    engine = RiskEngine(
        RiskConfig(
            max_symbol_exposure=Decimal("1000"),
            max_position_notional=Decimal("1000"),
            max_account_exposure=Decimal("1000"),
            max_leverage=Decimal("10"),
        )
    )
    signal = make_signal(OrderSide.SELL, "0.5", reduce_only=True)
    decision = engine.check(
        signal,
        account=make_account(),
        positions={"BTCUSDT": make_position("1", "100", "100")},
        market_price=Decimal("100"),
        open_order_count=0,
        current_signed_qty=Decimal("1"),
    )
    assert decision.decision == ExecutionDecision.APPROVE
    assert decision.checks.get("projected_signed_quantity") == "0.5"


def test_short_reduce_projected_exposure_decreases():
    engine = RiskEngine(
        RiskConfig(
            max_symbol_exposure=Decimal("1000"),
            max_position_notional=Decimal("1000"),
            max_account_exposure=Decimal("1000"),
            max_leverage=Decimal("10"),
        )
    )
    signal = make_signal(OrderSide.BUY, "0.5", reduce_only=True)
    decision = engine.check(
        signal,
        account=make_account(),
        positions={"BTCUSDT": make_position("-1", "100", "100")},
        market_price=Decimal("100"),
        open_order_count=0,
        current_signed_qty=Decimal("-1"),
    )
    assert decision.decision == ExecutionDecision.APPROVE
    assert decision.checks.get("projected_signed_quantity") == "-0.5"


def test_short_exit_never_reverses():
    engine = RiskEngine()
    signal = make_signal(OrderSide.BUY, "1.0", reduce_only=True)
    decision = engine.check(
        signal,
        account=make_account(),
        positions={"BTCUSDT": make_position("-1", "100", "100")},
        market_price=Decimal("100"),
        open_order_count=0,
        current_signed_qty=Decimal("-1"),
    )
    assert decision.decision == ExecutionDecision.APPROVE
    assert Decimal(decision.checks.get("projected_signed_quantity")) == Decimal("0")
