from decimal import Decimal

from crypto_trader.ai_optimization.optimizer import AIOptimizer
from crypto_trader.capital_guard.guard import CapitalGuard
from crypto_trader.demo.demo_executor import DemoExecutor
from crypto_trader.validation.shadow.metrics import calculate_metrics
from crypto_trader.validation.shadow.virtual_exchange import VirtualExecutionEngine


def test_virtual_execution_long_short_metrics_deterministic():
    engine = VirtualExecutionEngine(fee_rate="0.0005", slippage_bps="2")
    engine.open("BTCUSDT", "LONG", "100", "1")
    engine.close("BTCUSDT", "110")
    engine.open("ETHUSDT", "SHORT", "200", "1")
    engine.close("ETHUSDT", "195")
    assert len(engine.closed_positions) == 2
    metrics = calculate_metrics(
        engine.closed_positions,
        [
            {"direction": "LONG", "result": "CORRECT"},
            {"direction": "SHORT", "result": "CORRECT"},
        ],
    )
    assert metrics.trade_count == 2
    assert metrics.win_rate == Decimal("1")
    assert metrics.long_accuracy == Decimal("1")
    assert metrics.short_accuracy == Decimal("1")


async def test_demo_executor_never_live_or_bypasses_canonical_engine():
    executor = DemoExecutor()
    assert executor.adapter.demo is True
    result = await executor.submit(object())
    assert result.accepted is False
    assert result.reason == "CANONICAL_ENGINE_REQUIRED"


def test_ai_optimizer_promotion_and_rollback():
    optimizer = AIOptimizer()
    proposal = optimizer.propose("p1", "TREND_WORKS_HIGH_VOL")
    assert optimizer.promote(proposal, ["BACKTEST_PASS"]) is False
    assert (
        optimizer.promote(proposal, ["BACKTEST_PASS", "WALK_FORWARD_PASS", "SHADOW_PASS"]) is True
    )
    assert proposal.status == "PROMOTED"
    assert optimizer.rollback(proposal) is True
    assert proposal.status == "ROLLED_BACK"


def test_capital_guard_requires_manual_approval_and_limits():
    guard = CapitalGuard()
    blocked, reason = guard.block_new_risk(Decimal("10000"), Decimal("1000"))
    assert blocked is True
    assert reason == "MANUAL_APPROVAL_REQUIRED"
    guard.manual_approval_required = False
    guard.emergency_stop = True
    blocked, reason = guard.block_new_risk(Decimal("10000"), Decimal("100"))
    assert blocked is True
    assert reason == "EMERGENCY_STOP"
