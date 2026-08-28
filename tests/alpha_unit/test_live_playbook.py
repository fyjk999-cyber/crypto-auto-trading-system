from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.alpha.features import FeatureSnapshot
from crypto_trader.alpha.regime import MarketRegime, RegimeOutput
from crypto_trader.alpha.sub_strategy import (
    BreakoutRetestStrategy,
    LiquiditySweepStrategy,
    MarketStructureStrategy,
    SupportResistanceReversalStrategy,
    TrendPullbackStrategy,
)
from crypto_trader.alpha.sub_strategy.base import AlphaContext, AlphaSide
from crypto_trader.llm_chief.strategy_evidence import StrategyEvidenceBuilder

TS = datetime(2026, 1, 1, tzinfo=UTC)


def make_ctx(**updates) -> AlphaContext:
    feature = FeatureSnapshot(
        symbol="BTCUSDT",
        ts=TS,
        version=1,
        reason_codes=["test"],
        price=Decimal("100"),
        return_1=Decimal("0"),
        return_5=Decimal("0"),
        return_20=Decimal("0"),
        realized_vol_20=Decimal("0.01"),
        volume_ratio_20=Decimal("1"),
        ema_20=Decimal("100"),
        ema_50=Decimal("100"),
        zscore_20=Decimal("0"),
        donchian_low_50=Decimal("90"),
        donchian_high_50=Decimal("110"),
    ).model_copy(update=updates)
    regime = RegimeOutput(
        symbol="BTCUSDT",
        ts=TS,
        version=1,
        regime=MarketRegime.RANGE,
        reason_codes=["test"],
        trend_score=0.0,
        vol_score=0.01,
    )
    return AlphaContext(symbol="BTCUSDT", ts=TS, feature=feature, regime=regime)


def test_builder_includes_five_live_playbooks():
    names = {strategy.name for strategy in StrategyEvidenceBuilder().strategies}
    assert {
        "trend_pullback",
        "breakout_retest",
        "liquidity_sweep",
        "support_resistance_reversal",
        "market_structure",
    }.issubset(names)
    assert len(names) == 10


def test_trend_pullback_long_short_and_flat_fail_closed():
    strategy = TrendPullbackStrategy()
    long_ctx = make_ctx(
        price=Decimal("101"),
        ema_20=Decimal("101.2"),
        ema_50=Decimal("100"),
        return_20=Decimal("0.03"),
        zscore_20=Decimal("0.2"),
    )
    short_ctx = make_ctx(
        price=Decimal("99"),
        ema_20=Decimal("98.8"),
        ema_50=Decimal("100"),
        return_20=Decimal("-0.03"),
        zscore_20=Decimal("-0.2"),
    )
    assert strategy.evaluate(long_ctx).side == AlphaSide.LONG
    assert strategy.evaluate(short_ctx).side == AlphaSide.SHORT
    assert strategy.evaluate(make_ctx()).side == AlphaSide.NO_TRADE


def test_breakout_retest_long_short_and_flat_fail_closed():
    strategy = BreakoutRetestStrategy()
    long_ctx = make_ctx(
        price=Decimal("110"),
        return_1=Decimal("0.004"),
        return_20=Decimal("0.04"),
        volume_ratio_20=Decimal("1.2"),
        zscore_20=Decimal("1"),
    )
    short_ctx = make_ctx(
        price=Decimal("90"),
        return_1=Decimal("-0.004"),
        return_20=Decimal("-0.04"),
        volume_ratio_20=Decimal("1.2"),
        zscore_20=Decimal("-1"),
    )
    assert strategy.evaluate(long_ctx).side == AlphaSide.LONG
    assert strategy.evaluate(short_ctx).side == AlphaSide.SHORT
    assert strategy.evaluate(make_ctx()).side == AlphaSide.NO_TRADE


def test_liquidity_sweep_proxy_long_short_and_flat_fail_closed():
    strategy = LiquiditySweepStrategy()
    long_ctx = make_ctx(
        price=Decimal("90"),
        return_1=Decimal("0.004"),
        volume_ratio_20=Decimal("1.5"),
        zscore_20=Decimal("-2"),
    )
    short_ctx = make_ctx(
        price=Decimal("110"),
        return_1=Decimal("-0.004"),
        volume_ratio_20=Decimal("1.5"),
        zscore_20=Decimal("2"),
    )
    long_signal = strategy.evaluate(long_ctx)
    short_signal = strategy.evaluate(short_ctx)
    assert long_signal.side == AlphaSide.LONG
    assert short_signal.side == AlphaSide.SHORT
    assert "SWEEP_PROXY_CLOSE_ONLY" in long_signal.reason_codes
    assert strategy.evaluate(make_ctx()).side == AlphaSide.NO_TRADE


def test_support_resistance_reversal_long_short_and_flat_fail_closed():
    strategy = SupportResistanceReversalStrategy()
    long_ctx = make_ctx(
        price=Decimal("90"),
        return_1=Decimal("0.003"),
        zscore_20=Decimal("-1"),
    )
    short_ctx = make_ctx(
        price=Decimal("110"),
        return_1=Decimal("-0.003"),
        zscore_20=Decimal("1"),
    )
    assert strategy.evaluate(long_ctx).side == AlphaSide.LONG
    assert strategy.evaluate(short_ctx).side == AlphaSide.SHORT
    assert strategy.evaluate(make_ctx()).side == AlphaSide.NO_TRADE


def test_market_structure_long_short_and_flat_fail_closed():
    strategy = MarketStructureStrategy()
    long_ctx = make_ctx(
        price=Decimal("102"),
        ema_20=Decimal("101"),
        ema_50=Decimal("100"),
        return_5=Decimal("0.01"),
        return_20=Decimal("0.03"),
        zscore_20=Decimal("1"),
    )
    short_ctx = make_ctx(
        price=Decimal("98"),
        ema_20=Decimal("99"),
        ema_50=Decimal("100"),
        return_5=Decimal("-0.01"),
        return_20=Decimal("-0.03"),
        zscore_20=Decimal("-1"),
    )
    assert strategy.evaluate(long_ctx).side == AlphaSide.LONG
    assert strategy.evaluate(short_ctx).side == AlphaSide.SHORT
    assert strategy.evaluate(make_ctx()).side == AlphaSide.NO_TRADE
