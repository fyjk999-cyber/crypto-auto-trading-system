"""Alpha market data engine: per-symbol rolling windows, no future leakage.

Only closed observations at or before the current timestamp are used when
computing indicators for that timestamp.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class AlphaBar:
    ts: datetime
    price: Decimal
    volume: Decimal
    oi: Decimal | None = None
    funding: Decimal | None = None
    basis: Decimal | None = None


class MarketDataEngine:
    def __init__(self, symbol: str, max_bars: int = 500) -> None:
        self.symbol = symbol
        self.max_bars = max_bars
        self.bars: deque[AlphaBar] = deque(maxlen=max_bars)
        self._version = 0

    def ingest(self, ts: datetime, price, volume, oi=None, funding=None, basis=None) -> AlphaBar:
        bar = AlphaBar(
            ts=ts,
            price=D(price),
            volume=D(volume),
            oi=D(oi) if oi is not None else None,
            funding=D(funding) if funding is not None else None,
            basis=D(basis) if basis is not None else None,
        )
        if self.bars and ts <= self.bars[-1].ts:
            raise ValueError("market data must be monotonic (no future/duplicate bars)")
        self.bars.append(bar)
        self._version += 1
        return bar

    def _window(self, n: int):
        items = list(self.bars)[-n:] if n > 0 else list(self.bars)
        return items

    def closes(self, n: int = 0) -> list[Decimal]:
        return [b.price for b in self._window(n)]

    def returns(self, n: int = 1) -> list[Decimal]:
        closes = self.closes(n + 1)
        return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    def sma(self, n: int) -> Decimal | None:
        closes = self.closes(n)
        return sum(closes, Decimal("0")) / Decimal(len(closes)) if len(closes) >= n else None

    def ema(self, n: int) -> Decimal | None:
        closes = self.closes()
        if len(closes) < n:
            return None
        alpha = D("2") / D(n + 1)
        ema = sum(closes[:n], Decimal("0")) / D(n)
        for price in closes[n:]:
            ema = price * alpha + ema * (D("1") - alpha)
        return ema

    def realized_vol(self, n: int = 30) -> Decimal | None:
        rets = self.returns(1)[-n:]
        if len(rets) < 2:
            return None
        mean = sum(rets, Decimal("0")) / Decimal(len(rets))
        var = sum((r - mean) ** 2 for r in rets) / Decimal(len(rets) - 1)
        return var.sqrt()

    def average_volume(self, n: int = 20) -> Decimal | None:
        vols = [b.volume for b in self._window(n)]
        return sum(vols, Decimal("0")) / Decimal(len(vols)) if vols else None

    def donchian(self, n: int, offset: int = 0) -> tuple[Decimal | None, Decimal | None]:
        bars = self._window(n + offset)
        if offset > 0:
            bars = bars[:-offset] if len(bars) > offset else []
        if not bars:
            return None, None
        return min(b.price for b in bars), max(b.price for b in bars)

    def zscore(self, n: int) -> Decimal | None:
        closes = self.closes(n)
        if len(closes) < n:
            return None
        mean = sum(closes, Decimal("0")) / Decimal(len(closes))
        var = sum((p - mean) ** 2 for p in closes) / Decimal(len(closes))
        if var == 0:
            return Decimal("0")
        return (closes[-1] - mean) / var.sqrt()

    def latest(self) -> AlphaBar | None:
        return self.bars[-1] if self.bars else None

    def version(self) -> int:
        return self._version
