from decimal import Decimal

from crypto_trader.domain.enums import ExecutionDecision, OrderSide
from crypto_trader.domain.models import Account, Position, SignalIntent
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
        assert "max_open_orders" in decision.checks["supporting_risk_evidence"]
        assert decision.checks["contrary_risk_evidence"] == ["LEVERAGE_CLAMPED"]
        assert decision.checks["hard_limits_triggered"] == ["LEVERAGE_CLAMPED"]


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


def test_reject_contract_is_explainable_and_never_reverses_direction():
    engine = RiskEngine()
    for side, direction in ((OrderSide.BUY, "LONG"), (OrderSide.SELL, "SHORT")):
        result = engine.check(
            SignalIntent(
                signal_id=f"reject-{direction}",
                strategy_id="live_llm",
                symbol="BTCUSDT",
                side=side,
                quantity=Decimal("1"),
                limit_price=Decimal("100"),
                metadata={"direction": direction, "requested_leverage": "0.5"},
            ),
            account=Account(equity=Decimal("10000")),
            positions={},
            market_price=Decimal("100"),
            open_order_count=0,
        )
        assert result.decision == ExecutionDecision.REJECT
        assert result.side == side
        assert result.checks["original_direction"] == direction
        assert result.checks["original_quantity"] == "1"
        assert result.checks["approved_quantity"] == "0"
        assert result.checks["requested_leverage"] == "0.5"
        assert result.checks["approved_leverage"] == "0"
        assert result.checks["contrary_risk_evidence"] == ["INVALID_LEVERAGE"]
        assert result.checks["hard_limits_triggered"] == ["INVALID_LEVERAGE"]


def test_direction_metadata_mismatch_is_rejected_not_corrected_or_reversed():
    engine = RiskEngine()
    entry = engine.check(
        SignalIntent(
            signal_id="direction-mismatch-entry",
            strategy_id="live_llm",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            limit_price=Decimal("100"),
            metadata={"direction": "SHORT"},
        ),
        account=Account(equity=Decimal("10000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
    )
    assert entry.decision == ExecutionDecision.REJECT
    assert entry.reason == "DIRECTION_METADATA_MISMATCH"
    assert entry.side == OrderSide.BUY

    long_position = Position(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("2"),
        avg_entry_price=Decimal("100"),
        cost_basis=Decimal("200"),
    )
    reduction = engine.check(
        SignalIntent(
            signal_id="direction-mismatch-reduce",
            strategy_id="live_llm_position",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("1"),
            limit_price=Decimal("100"),
            metadata={"direction": "SHORT", "reduce_only": True},
        ),
        account=Account(equity=Decimal("10000")),
        positions={"BTCUSDT": long_position},
        market_price=Decimal("100"),
        open_order_count=0,
    )
    assert reduction.decision == ExecutionDecision.REJECT
    assert reduction.reason == "DIRECTION_METADATA_MISMATCH"
    assert reduction.side == OrderSide.SELL


def test_approve_contract_records_supporting_and_empty_contrary_risk_evidence():
    result = RiskEngine().check(
        SignalIntent(
            signal_id="approve-evidence",
            strategy_id="live_llm",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            limit_price=Decimal("100"),
            metadata={"direction": "LONG", "requested_leverage": "1"},
        ),
        account=Account(equity=Decimal("10000")),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
    )
    assert result.decision == ExecutionDecision.APPROVE
    assert "max_leverage" in result.checks["supporting_risk_evidence"]
    assert result.checks["contrary_risk_evidence"] == []
    assert result.checks["hard_limits_triggered"] == []
