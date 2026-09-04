from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.alpha.ensemble import MultiStrategyAlpha
from crypto_trader.alpha.market_data_engine import MarketDataEngine
from crypto_trader.domain.models import Account
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.strategy.base import StrategyContext

TS = datetime(2026, 1, 1, tzinfo=UTC)


def seed_uptrend_mde(symbol="BTCUSDT", n=120):
    mde = MarketDataEngine(symbol)
    ts = TS
    for i in range(n):
        ts = ts + timedelta(minutes=1)
        mde.ingest(ts, Decimal("100") + Decimal(i) * Decimal("0.1"), Decimal("10"))
    return mde


async def test_alpha_plugin_cannot_drive_paper_engine_entry(database):
    alpha = MultiStrategyAlpha(
        "BTCUSDT",
        risk_per_trade="0.0001",
        max_position_notional="500",
        max_leverage="3",
    )
    alpha.mde = seed_uptrend_mde()
    book = OrderBook(symbol="BTCUSDT")
    book.apply_snapshot(1, [(Decimal("112"), Decimal("10"))], [(Decimal("112.1"), Decimal("10"))])
    ctx = StrategyContext(
        symbol="BTCUSDT",
        book=book,
        account=Account(balances={}, equity=Decimal("10000")),
        positions={},
        clock_time=TS + timedelta(minutes=121),
    )
    assert await alpha.on_market_data(ctx) == []
    assert alpha.analyze_evidence(ctx)["strategy_fit"]["side"] == "LONG"


async def test_alpha_short_path_is_symmetric_decision_layer():
    """SHORT is symmetric at the alpha decision layer (spot short execution
    requires a margin/borrow model; it is a documented limitation)."""
    from datetime import timedelta as _td

    from crypto_trader.alpha.sub_strategy.base import AlphaSide

    alpha = MultiStrategyAlpha(
        "BTCUSDT",
        risk_per_trade="0.0001",
        max_position_notional="500",
        max_leverage="3",
    )
    mde = MarketDataEngine("BTCUSDT")
    ts = TS
    for i in range(120):
        ts = ts + _td(minutes=1)
        mde.ingest(ts, Decimal("100") - Decimal(i) * Decimal("0.1"), Decimal("10"))
    alpha.mde = mde
    book = OrderBook(symbol="BTCUSDT")
    book.apply_snapshot(1, [(Decimal("88"), Decimal("1"))], [(Decimal("88.1"), Decimal("1"))])
    ctx = StrategyContext(
        symbol="BTCUSDT",
        book=book,
        account=Account(balances={}, equity=Decimal("10000")),
        positions={},
        clock_time=TS + _td(minutes=121),
        run_id="r_short",
    )
    assert await alpha.on_market_data(ctx) == []
    evidence = alpha.analyze_evidence(ctx)
    assert evidence["strategy_fit"]["side"] == "SHORT"
    assert alpha.last_meta.side == AlphaSide.SHORT
    # symmetry: same sizing/leverage magnitude as LONG for same inputs
    from crypto_trader.alpha.features import compute_features
    from crypto_trader.alpha.leverage import recommend_leverage
    from crypto_trader.alpha.regime import RegimeEngine
    from crypto_trader.alpha.sizing import recommend_position

    feature = compute_features(alpha.mde, "BTCUSDT", ctx.clock_time)
    regime = RegimeEngine().classify(feature)
    meta_long = alpha.last_meta.model_copy(update={"side": AlphaSide.LONG})
    meta_short = alpha.last_meta.model_copy(update={"side": AlphaSide.SHORT})
    q_long = recommend_position(
        meta_long,
        account_equity=Decimal("10000"),
        price=Decimal("88"),
        volatility=feature.realized_vol_20 or Decimal("0.01"),
    )
    q_short = recommend_position(
        meta_short,
        account_equity=Decimal("10000"),
        price=Decimal("88"),
        volatility=feature.realized_vol_20 or Decimal("0.01"),
    )
    assert q_long == q_short
    lev_long = recommend_leverage(
        meta_long, regime=regime.regime, volatility=feature.realized_vol_20 or Decimal("0.01")
    )
    lev_short = recommend_leverage(
        meta_short, regime=regime.regime, volatility=feature.realized_vol_20 or Decimal("0.01")
    )
    assert lev_long == lev_short
