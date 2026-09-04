from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from crypto_trader.alpha.ensemble import MultiStrategyAlpha
from crypto_trader.alpha.features import compute_features
from crypto_trader.alpha.learning import FastLearning, SlowLearning, SlowStage
from crypto_trader.alpha.leverage import recommend_leverage
from crypto_trader.alpha.market_data_engine import MarketDataEngine
from crypto_trader.alpha.meta_decision import MetaDecision
from crypto_trader.alpha.ml_meta import BASE_WEIGHTS, MLMeta
from crypto_trader.alpha.regime import MarketRegime, RegimeEngine
from crypto_trader.alpha.sizing import recommend_position
from crypto_trader.alpha.sub_strategy import (
    BreakoutStrategy,
    FundingBasisStrategy,
    MeanReversionStrategy,
    MomentumStrategy,
    TrendFollowingStrategy,
)
from crypto_trader.alpha.sub_strategy.base import AlphaContext, AlphaSide
from crypto_trader.domain.models import Account
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.strategy.base import StrategyContext

TS = datetime(2026, 1, 1, tzinfo=UTC)


def make_mde(prices):
    mde = MarketDataEngine("BTCUSDT")
    ts = TS
    for price in prices:
        ts = ts + timedelta(minutes=1)
        mde.ingest(ts, price, Decimal("10"))
    return mde


def make_ctx(mde):
    feature = compute_features(mde, "BTCUSDT", TS + timedelta(minutes=len(mde.bars)))
    regime = RegimeEngine().classify(feature)
    return AlphaContext(symbol="BTCUSDT", ts=feature.ts, feature=feature, regime=regime)


def uptrend(n=120):
    return [Decimal("100") + Decimal(i) * Decimal("0.1") for i in range(n)]


def downtrend(n=120):
    return [Decimal("120") - Decimal(i) * Decimal("0.1") for i in range(n)]


def flat(n=120):
    return [Decimal("100") for _ in range(n)]


def test_market_data_engine_no_future_leakage():
    mde = make_mde(uptrend(60))
    snapshot = compute_features(mde, "BTCUSDT", mde.latest().ts)
    # features are computed only from closed bars <= latest ts
    assert snapshot.ts == mde.latest().ts
    assert snapshot.version == mde.version()
    assert "closed_bars_only" in snapshot.reason_codes


def test_features_uptrend_and_downtrend_symmetric():
    up = compute_features(make_mde(uptrend(120)), "BTCUSDT", TS + timedelta(minutes=120))
    down = compute_features(make_mde(downtrend(120)), "BTCUSDT", TS + timedelta(minutes=120))
    assert up.return_20 > 0
    assert down.return_20 < 0
    assert abs(abs(up.return_20) - abs(down.return_20)) < Decimal("0.002")


def test_regime_classifies_bull_bear_range_and_extreme():
    up_ctx = make_ctx(make_mde(uptrend(120)))
    assert up_ctx.regime.regime == MarketRegime.BULL
    down_ctx = make_ctx(make_mde(downtrend(120)))
    assert down_ctx.regime.regime == MarketRegime.BEAR
    flat_ctx = make_ctx(make_mde(flat(120)))
    assert flat_ctx.regime.regime == MarketRegime.RANGE
    # extreme risk via volatility percentile override
    reg = RegimeEngine()
    f = flat_ctx.feature.model_copy(update={"realized_vol_20": Decimal("0.05")})
    out = reg.classify(f, vol_percentile=0.99)
    assert out.regime == MarketRegime.EXTREME_RISK


def test_sub_strategies_long_short_symmetric():
    up_ctx = make_ctx(make_mde(uptrend(120)))
    down_ctx = make_ctx(make_mde(downtrend(120)))
    strategies = [
        TrendFollowingStrategy(),
        MomentumStrategy(),
        BreakoutStrategy(),
        MeanReversionStrategy(),
        FundingBasisStrategy(),
    ]
    for strat in strategies:
        up_signal = strat.evaluate(up_ctx)
        down_signal = strat.evaluate(down_ctx)
        if up_signal.side == AlphaSide.NO_TRADE:
            assert down_signal.side == AlphaSide.NO_TRADE, strat.name
            continue
        assert {up_signal.side, down_signal.side} == {AlphaSide.LONG, AlphaSide.SHORT}, strat.name
        assert abs(up_signal.confidence - down_signal.confidence) < Decimal("0.05")


def test_no_trade_is_first_class_for_flat_market():
    ctx = make_ctx(make_mde(flat(120)))
    for strat in [
        TrendFollowingStrategy(),
        MomentumStrategy(),
        BreakoutStrategy(),
        MeanReversionStrategy(),
        FundingBasisStrategy(),
    ]:
        signal = strat.evaluate(ctx)
        assert signal.side == AlphaSide.NO_TRADE, strat.name


def test_ml_meta_not_a_directional_sub_strategy():
    assert "ml_meta" not in BASE_WEIGHTS
    assert sum(BASE_WEIGHTS.values()) == Decimal("1.00")
    assert BASE_WEIGHTS["trend_following"] == Decimal("0.40")
    assert BASE_WEIGHTS["funding_basis"] == Decimal("0.15")


def test_ml_meta_effective_weights_and_long_short():
    fast = FastLearning()
    ml = MLMeta(fast)
    up_ctx = make_ctx(make_mde(uptrend(120)))
    signals = [
        s.evaluate(up_ctx)
        for s in [
            TrendFollowingStrategy(),
            MomentumStrategy(),
            BreakoutStrategy(),
            MeanReversionStrategy(),
            FundingBasisStrategy(),
        ]
    ]
    decision = ml.decide(symbol="BTCUSDT", ts=up_ctx.ts, regime=up_ctx.regime, signals=signals)
    assert decision.side == AlphaSide.LONG
    assert decision.confidence > 0
    assert abs(sum(decision.effective_weights.values()) - Decimal("1.0")) < Decimal("0.001")
    down_ctx = make_ctx(make_mde(downtrend(120)))
    signals = [
        s.evaluate(down_ctx)
        for s in [
            TrendFollowingStrategy(),
            MomentumStrategy(),
            BreakoutStrategy(),
            MeanReversionStrategy(),
            FundingBasisStrategy(),
        ]
    ]
    decision2 = ml.decide(symbol="BTCUSDT", ts=down_ctx.ts, regime=down_ctx.regime, signals=signals)
    assert decision2.side == AlphaSide.SHORT


def test_position_sizing_long_short_symmetric():
    meta = MetaDecision(
        symbol="BTCUSDT",
        ts=TS,
        version="t",
        side=AlphaSide.LONG,
        confidence=Decimal("0.8"),
        reason_codes=["t"],
        effective_weights={},
        vote_scores={},
    )
    long_qty = recommend_position(
        meta,
        account_equity=Decimal("10000"),
        price=Decimal("100"),
        volatility=Decimal("0.01"),
        risk_per_trade="0.01",
    )
    meta2 = meta.model_copy(update={"side": AlphaSide.SHORT})
    short_qty = recommend_position(
        meta2,
        account_equity=Decimal("10000"),
        price=Decimal("100"),
        volatility=Decimal("0.01"),
        risk_per_trade="0.01",
    )
    assert long_qty == short_qty
    assert long_qty > 0
    no = recommend_position(
        meta.model_copy(update={"side": AlphaSide.NO_TRADE}),
        account_equity=Decimal("10000"),
        price=Decimal("100"),
        volatility=Decimal("0.01"),
    )
    assert no == 0


def test_leverage_recommendation_bounds():
    meta = MetaDecision(
        symbol="BTCUSDT",
        ts=TS,
        version="t",
        side=AlphaSide.LONG,
        confidence=Decimal("0.8"),
        reason_codes=["t"],
        effective_weights={},
        vote_scores={},
    )
    lev = recommend_leverage(
        meta, regime=MarketRegime.BULL, volatility=Decimal("0.01"), max_leverage="3"
    )
    assert 0 < lev <= Decimal("3")
    risk_lev = recommend_leverage(
        meta, regime=MarketRegime.EXTREME_RISK, volatility=Decimal("0.01"), max_leverage="3"
    )
    assert risk_lev < lev


def test_fast_learning_updates_stats_and_not_production():
    fast = FastLearning()
    fast.record_trade("trend_following", "LONG", Decimal("0.5"))
    fast.record_trade("trend_following", "LONG", Decimal("-0.2"))
    assert fast.strategy_score("trend_following") is not None
    assert fast.failure_count("trend_following") == 1
    assert fast.confidence_calibration("trend_following", "LONG") != Decimal("0")


def test_slow_learning_requires_full_pipeline_before_promotion():
    slow = SlowLearning()
    slow.propose("c1", "trend_following", {"threshold": "0.003"})
    with pytest.raises(ValueError):
        slow.promote("c1", "trend_following")
    slow.add_evidence("c1", SlowStage.BACKTEST, {"sharpe": "1.1"})
    slow.add_evidence("c1", SlowStage.OUT_OF_SAMPLE, {"sharpe": "1.0"})
    slow.add_evidence("c1", SlowStage.WALK_FORWARD, {"sharpe": "0.9"})
    slow.add_evidence("c1", SlowStage.SHADOW, {"live": "ok"})
    slow.add_evidence("c1", SlowStage.PROMOTION, {"promoted": True})
    promoted = slow.promote("c1", "trend_following")
    assert promoted["strategy"] == "trend_following"
    assert slow.candidates["c1"].status == "PROMOTED"


def test_slow_learning_rejects_invalid_order():
    slow = SlowLearning()
    slow.propose("c2", "momentum", {"threshold": "0.004"})
    slow.add_evidence("c2", SlowStage.SHADOW, {"bad": True})
    assert slow.candidates["c2"].status == "REJECTED"


def test_alpha_never_imports_core_execution(tmp_path):
    import subprocess
    import sys

    root = "/".join(__file__.split("/")[:-3])
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import ast, pathlib
root = pathlib.Path("src/crypto_trader/alpha")
forbidden = {"LedgerService", "OrderManager", "TradingEngine", "submit_order", "cancel_order"}
for p in root.rglob("*.py"):
    tree = ast.parse(p.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in forbidden:
            raise SystemExit(f"{p} references {node.id}")
        if isinstance(node, ast.Attribute) and node.attr in {"submit_order", "cancel_order"}:
            raise SystemExit(f"{p} references {node.attr}")
print("ALPHA_CLEAN")
""",
        ],
        cwd=root,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "ALPHA_CLEAN" in result.stdout


def test_ensemble_produces_evidence_but_no_executable_signal():
    alpha = MultiStrategyAlpha("BTCUSDT")
    # uptrend produces measurable bullish evidence, never an entry intent.
    up_book = OrderBook(symbol="BTCUSDT")
    up_book.apply_snapshot(1, [(Decimal("100"), Decimal("1"))], [(Decimal("100.1"), Decimal("1"))])
    account = Account(balances={}, equity=Decimal("10000"))
    ctx = StrategyContext(
        symbol="BTCUSDT", book=up_book, account=account, positions={}, clock_time=TS, run_id="r1"
    )
    # seed many bars into alpha.mde directly so features have trend
    alpha.mde = make_mde(uptrend(120))
    signals = __import__("asyncio").run(alpha.on_market_data(ctx))
    evidence = alpha.analyze_evidence(ctx)
    assert signals == []
    assert evidence["tool_name"] == "multi_strategy_alpha"
    assert evidence["strategy_fit"]["side"] == "LONG"

    # downtrend -> SELL signal
    alpha_down = MultiStrategyAlpha("BTCUSDT")
    alpha_down.mde = make_mde(downtrend(120))
    signals_down = __import__("asyncio").run(alpha_down.on_market_data(ctx))
    evidence_down = alpha_down.analyze_evidence(ctx)
    assert signals_down == []
    assert evidence_down["strategy_fit"]["side"] == "SHORT"


def test_ensemble_no_trade_for_flat_market():
    alpha = MultiStrategyAlpha("BTCUSDT")
    alpha.mde = make_mde(flat(120))
    book = OrderBook(symbol="BTCUSDT")
    book.apply_snapshot(1, [(Decimal("100"), Decimal("1"))], [(Decimal("100.1"), Decimal("1"))])
    ctx = StrategyContext(
        symbol="BTCUSDT",
        book=book,
        account=Account(balances={}, equity=Decimal("10000")),
        positions={},
        clock_time=TS,
        run_id="r1",
    )
    signals = __import__("asyncio").run(alpha.on_market_data(ctx))
    assert signals == []
    assert alpha.analyze_evidence(ctx)["strategy_fit"]["side"] == "NO_TRADE"
