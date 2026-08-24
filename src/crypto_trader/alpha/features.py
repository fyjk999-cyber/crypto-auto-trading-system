"""Feature engine: numeric feature snapshot with timestamp/version/reason_codes."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from crypto_trader.alpha.market_data_engine import MarketDataEngine


class FeatureSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    ts: datetime
    version: int
    reason_codes: list[str]
    price: Decimal
    return_1: Decimal = Decimal("0")
    return_5: Decimal = Decimal("0")
    return_20: Decimal = Decimal("0")
    realized_vol_20: Decimal = Decimal("0")
    volume_ratio_20: Decimal = Decimal("1")
    ema_20: Decimal = Decimal("0")
    ema_50: Decimal = Decimal("0")
    zscore_20: Decimal = Decimal("0")
    donchian_low_50: Decimal = Decimal("0")
    donchian_high_50: Decimal = Decimal("0")
    oi: Decimal = Decimal("0")
    funding: Decimal = Decimal("0")
    basis: Decimal = Decimal("0")


def compute_features(mde: MarketDataEngine, symbol: str, ts: datetime) -> FeatureSnapshot:
    """Compute features from closed bars only (the latest bar is at <= ts)."""
    latest = mde.latest()
    if latest is None:
        raise ValueError("no market data")
    price = latest.price

    def ret(n: int) -> Decimal:
        closes = mde.closes(n + 1)
        if len(closes) < n + 1:
            return Decimal("0")
        return (closes[-1] - closes[-1 - n]) / closes[-1 - n]

    vol = mde.realized_vol(20) or Decimal("0")
    avg_vol = mde.average_volume(20) or Decimal("1")
    vol_ratio = latest.volume / avg_vol if avg_vol > 0 else Decimal("1")
    low, high = mde.donchian(50, offset=1)
    return FeatureSnapshot(
        symbol=symbol,
        ts=ts,
        version=mde.version(),
        reason_codes=["closed_bars_only"],
        price=price,
        return_1=ret(1),
        return_5=ret(5),
        return_20=ret(20),
        realized_vol_20=vol,
        volume_ratio_20=vol_ratio,
        ema_20=mde.ema(20) or price,
        ema_50=mde.ema(50) or price,
        zscore_20=mde.zscore(20) or Decimal("0"),
        donchian_low_50=low or price,
        donchian_high_50=high or price,
        oi=latest.oi,
        funding=latest.funding,
        basis=latest.basis,
    )
