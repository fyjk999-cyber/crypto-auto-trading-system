"""Multi-Strategy Alpha ensemble.

Implements the StrategyPlugin contract: consumes market data, produces
SignalIntent. It never imports or touches Ledger, OrderManager, or exchange
execution APIs.
"""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.alpha.features import compute_features
from crypto_trader.alpha.learning import FastLearning, SlowLearning
from crypto_trader.alpha.leverage import recommend_leverage
from crypto_trader.alpha.market_data_engine import MarketDataEngine
from crypto_trader.alpha.meta_decision import MetaDecision
from crypto_trader.alpha.ml_meta import MLMeta
from crypto_trader.alpha.regime import RegimeEngine
from crypto_trader.alpha.sizing import recommend_position
from crypto_trader.alpha.sub_strategy import (
    BreakoutStrategy,
    FundingBasisStrategy,
    MeanReversionStrategy,
    MomentumStrategy,
    TrendFollowingStrategy,
)
from crypto_trader.alpha.sub_strategy.base import AlphaContext, AlphaSide
from crypto_trader.domain.enums import OrderSide, OrderType, TimeInForce
from crypto_trader.domain.models import SignalIntent
from crypto_trader.domain.money import D, floor_to_step, round_tick
from crypto_trader.strategy.base import StrategyContext, StrategyPlugin


class MultiStrategyAlpha(StrategyPlugin):
    name = "multi_strategy_alpha"
    version = "phase16.0.1"
    symbol = "BTCUSDT"

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        *,
        slippage_bps: str = "2",
        risk_per_trade: str = "0.01",
        max_position_notional: str | None = "100000",
        max_leverage: str = "3",
        tick_size: str = "0.01",
        step_size: str = "0.00001",
        fast_learning: FastLearning | None = None,
        slow_learning: SlowLearning | None = None,
    ) -> None:
        self.symbol = symbol
        self.slippage_bps = D(slippage_bps)
        self.risk_per_trade = risk_per_trade
        self.max_position_notional = D(max_position_notional) if max_position_notional else None
        self.max_leverage = max_leverage
        self.tick_size = D(tick_size)
        self.step_size = D(step_size)
        self.mde = MarketDataEngine(symbol)
        self.regime_engine = RegimeEngine()
        self.fast_learning = fast_learning or FastLearning()
        self.slow_learning = slow_learning or SlowLearning()
        self.ml_meta = MLMeta(self.fast_learning)
        self.sub_strategies = [
            TrendFollowingStrategy(),
            MomentumStrategy(),
            BreakoutStrategy(),
            MeanReversionStrategy(),
            FundingBasisStrategy(),
        ]
        self.last_meta: MetaDecision | None = None

    async def on_market_data(self, ctx: StrategyContext) -> list[SignalIntent]:
        book = ctx.book
        mid = book.mid_price()
        if mid is None:
            return []
        ts = ctx.clock_time
        volume = Decimal("0")
        best_bid = book.best_bid()
        best_ask = book.best_ask()
        if best_bid is not None:
            volume += best_bid.quantity
        if best_ask is not None:
            volume += best_ask.quantity
        # prevent duplicate/out-of-order ingestion for the same timestamp
        latest = self.mde.latest()
        if latest is None or ts > latest.ts:
            self.mde.ingest(ts, mid, max(volume, Decimal("0.0001")), oi="0", funding="0", basis="0")
        feature = compute_features(self.mde, self.symbol, ts)
        regime = self.regime_engine.classify(feature)
        alpha_ctx = AlphaContext(
            symbol=self.symbol, ts=ts, feature=feature, regime=regime, run_id=ctx.run_id
        )
        signals = [s.evaluate(alpha_ctx) for s in self.sub_strategies]
        meta = self.ml_meta.decide(
            symbol=self.symbol, ts=ts, regime=regime, signals=signals, run_id=ctx.run_id
        )
        self.last_meta = meta
        self.fast_learning.record_regime(regime.regime.value)
        if meta.side == AlphaSide.NO_TRADE:
            return []

        price = mid
        if meta.side == AlphaSide.LONG:
            price = mid * (D("1") + self.slippage_bps / D("10000"))
        else:
            price = mid * (D("1") - self.slippage_bps / D("10000"))
        price = round_tick(price, self.tick_size)
        quantity = recommend_position(
            meta,
            account_equity=ctx.account.equity,
            price=price,
            volatility=feature.realized_vol_20 or D("0.01"),
            risk_per_trade=self.risk_per_trade,
            max_position_notional=self.max_position_notional,
        )
        quantity = floor_to_step(quantity, self.step_size)
        if quantity <= 0:
            return []
        leverage = recommend_leverage(
            meta,
            regime=regime.regime,
            volatility=feature.realized_vol_20 or D("0.01"),
            max_leverage=self.max_leverage,
        )
        return [
            SignalIntent(
                signal_id=f"alpha_{int(ts.timestamp() * 1000)}_{meta.side.value}",
                strategy_id=self.name,
                symbol=self.symbol,
                side=OrderSide.BUY if meta.side == AlphaSide.LONG else OrderSide.SELL,
                quantity=quantity,
                limit_price=price,
                order_type=OrderType.LIMIT,
                time_in_force=TimeInForce.GTC,
                expires_at=ts + __import__("datetime").timedelta(minutes=5),
                reason=str(meta.reason_codes),
                run_id=ctx.run_id,
                metadata={
                    "alpha_decision": meta.model_dump(mode="json"),
                    "recommended_leverage": str(leverage),
                    "regime": regime.regime.value,
                    "alpha_version": self.version,
                },
            )
        ]

    def update_fast_learning(self, strategy: str, side: str, pnl) -> None:
        self.fast_learning.record_trade(strategy, side, pnl)
