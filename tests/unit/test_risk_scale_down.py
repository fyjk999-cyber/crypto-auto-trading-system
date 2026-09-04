from decimal import Decimal

from crypto_trader.domain.enums import ExecutionDecision, OrderSide
from crypto_trader.domain.models import Account, SignalIntent
from crypto_trader.risk.engine import RiskConfig, RiskEngine


def test_scale_down_preserves_short_direction_and_records_adjustment():
    decision = RiskEngine(RiskConfig(max_order_notional=Decimal("100"))).check(
        SignalIntent(
            signal_id="short_1",
            strategy_id="live_llm",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("2"),
            limit_price=Decimal("100"),
        ),
        account=Account(equity=Decimal("10000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
    )
    assert decision.decision == ExecutionDecision.SCALE_DOWN
    assert decision.side == OrderSide.SELL
    assert decision.checks["approved_quantity"] == "1"


def test_scale_down_uses_contract_size_for_derivative_notional():
    decision = RiskEngine(RiskConfig(max_order_notional=Decimal("100"))).check(
        SignalIntent(
            signal_id="swap_1",
            strategy_id="live_llm",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("200"),
            limit_price=Decimal("100"),
            metadata={"instrument_type": "SWAP", "contract_size": "0.01"},
        ),
        account=Account(equity=Decimal("10000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
    )
    assert decision.decision == ExecutionDecision.SCALE_DOWN
    assert decision.checks["approved_quantity"] == "100"


def test_leverage_clamp_is_symmetric_and_preserves_quantity_and_direction():
    engine = RiskEngine(RiskConfig(max_leverage=Decimal("3")))
    for side in (OrderSide.BUY, OrderSide.SELL):
        decision = engine.check(
            SignalIntent(
                signal_id=f"leverage-{side.value}",
                strategy_id="live_llm",
                symbol="BTCUSDT",
                side=side,
                quantity=Decimal("1"),
                limit_price=Decimal("100"),
                metadata={"requested_leverage": "5"},
            ),
            account=Account(equity=Decimal("10000")),
            positions={},
            market_price=Decimal("100"),
            open_order_count=0,
        )
        assert decision.decision == ExecutionDecision.SCALE_DOWN
        assert decision.side == side
        assert decision.checks["approved_quantity"] == "1"
        assert decision.checks["requested_leverage"] == "5"
        assert decision.checks["approved_leverage"] == "3"


def test_volatility_liquidity_missing_and_invalid_leverage_bounds():
    engine = RiskEngine(RiskConfig(max_leverage=Decimal("5")))
    base = dict(
        signal_id="leverage-bounds",
        strategy_id="live_llm",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        limit_price=Decimal("100"),
    )
    common = dict(
        account=Account(equity=Decimal("10000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
    )
    missing = engine.check(SignalIntent(**base), **common)
    assert missing.checks["approved_leverage"] == "1"
    volatile = engine.check(
        SignalIntent(**base, metadata={"requested_leverage": "4", "volatility": "0.1"}),
        **common,
    )
    assert volatile.decision == ExecutionDecision.SCALE_DOWN
    assert volatile.checks["approved_leverage"] == "1"
    illiquid = engine.check(
        SignalIntent(**base, metadata={"requested_leverage": "4", "liquidity": "0"}),
        **common,
    )
    assert illiquid.checks["approved_leverage"] == "1"
    invalid = engine.check(
        SignalIntent(**base, metadata={"requested_leverage": "0.5"}), **common
    )
    assert invalid.decision == ExecutionDecision.REJECT
    assert invalid.reason == "INVALID_LEVERAGE"
