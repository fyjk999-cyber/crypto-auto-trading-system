"""MarketFeatureVector: lightweight technical/derivative/orderflow features."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class MarketFeatureVector:
    symbol: str
    timeframe: str = "1m"
    price: Decimal = Decimal("0")
    sma20: Decimal = Decimal("0")
    ema20: Decimal = Decimal("0")
    rsi14: Decimal = Decimal("0")
    roc5: Decimal = Decimal("0")
    atr14: Decimal = Decimal("0")
    realized_vol: Decimal = Decimal("0")
    bollinger_upper: Decimal = Decimal("0")
    bollinger_lower: Decimal = Decimal("0")
    volume_anomaly: Decimal = Decimal("0")
    spread_bps: Decimal = Decimal("0")
    depth_imbalance: Decimal = Decimal("0")
    funding: Decimal | None = None
    oi_change_pct: Decimal | None = None
    liquidation_volume: Decimal = Decimal("0")
    regime: str = "RANGE"
    quality_score: int = 0

    @staticmethod
    def from_closes(
        symbol: str,
        closes: list[Decimal],
        volumes: list[Decimal] | None = None,
        timeframe: str = "1m",
    ) -> MarketFeatureVector:
        if len(closes) < 20:
            return MarketFeatureVector(symbol=symbol, timeframe=timeframe)
        closes = [D(c) for c in closes]
        volumes = [D(v) for v in volumes] if volumes else [D("1")] * len(closes)
        sma20 = sum(closes[-20:], D("0")) / D("20")
        ema20 = closes[-20]
        for c in closes[-19:]:
            ema20 = c * D("0.095") + ema20 * D("0.905")
        returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
        vol = (
            (sum((r * D("100")) ** 2 for r in returns[-20:]) / D("20")).sqrt()
            if len(returns) >= 20
            else D("0")
        )
        avg_vol = sum(volumes[-20:], D("0")) / D("20")
        volume_anomaly = volumes[-1] / avg_vol if avg_vol > 0 else D("1")
        rsi14 = D("50")
        gains, losses = [], []
        for i in range(1, 15):
            diff = closes[-14 + i] - closes[-15 + i]
            gains.append(max(diff, D("0")))
            losses.append(max(-diff, D("0")))
        avg_gain = sum(gains, D("0")) / D("14")
        avg_loss = sum(losses, D("0")) / D("14")
        if avg_loss == 0:
            rsi14 = D("100")
        else:
            rsi14 = D("100") - (D("100") / (D("1") + avg_gain / avg_loss))
        roc5 = (closes[-1] - closes[-6]) / closes[-6] if len(closes) >= 6 else D("0")
        atr14 = vol / D("100") * closes[-1]
        upper = sma20 + D("2") * vol / D("100") * closes[-1]
        lower = sma20 - D("2") * vol / D("100") * closes[-1]
        regime = "BULL" if closes[-1] > ema20 else "BEAR"
        return MarketFeatureVector(
            symbol=symbol,
            timeframe=timeframe,
            price=closes[-1],
            sma20=sma20,
            ema20=ema20,
            rsi14=rsi14,
            roc5=roc5,
            atr14=atr14,
            realized_vol=vol,
            bollinger_upper=upper,
            bollinger_lower=lower,
            volume_anomaly=volume_anomaly,
            regime=regime,
            quality_score=min(100, 40 + len(closes)),
        )
