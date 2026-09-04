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
