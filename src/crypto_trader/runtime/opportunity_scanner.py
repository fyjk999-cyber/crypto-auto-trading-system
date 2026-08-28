"""Cheap pre-LLM opportunity scoring for the multi-symbol PAPER runtime.

This module is intentionally NOT a trading strategy and never creates orders.
It ranks symbols with inexpensive, deterministic market features so only the
best candidates reach the expensive StrategyEvidence + Chief Trader path.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from crypto_trader.strategy.base import StrategyContext


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class OpportunityScore:
    symbol: str
    score: float
    eligible: bool
    direction: str
    spread_bps: float
    components: dict[str, float]
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "score": self.score,
            "eligible": self.eligible,
            "direction": self.direction,
            "spread_bps": self.spread_bps,
            "components": dict(self.components),
            "reason": self.reason,
        }


class CheapOpportunityScanner:
    """Rank market opportunities without invoking factors, memory, or an LLM."""

    def __init__(
        self,
        *,
        min_candles: int = 30,
        momentum_lookback: int = 20,
        min_score: float = 0.20,
        max_spread_bps: float = 15.0,
    ) -> None:
        self.min_candles = max(int(min_candles), 3)
        self.momentum_lookback = max(int(momentum_lookback), 2)
        self.min_score = _clip(float(min_score))
        self.max_spread_bps = max(float(max_spread_bps), 0.01)

    def score(self, ctx: StrategyContext, candles: list[dict]) -> OpportunityScore:
        if len(candles) < self.min_candles:
            return self._invalid(ctx.symbol, "INSUFFICIENT_CANDLES")

        try:
            closes = [float(row["close"]) for row in candles]
            volumes = [float(row.get("volume", 0.0)) for row in candles]
        except (KeyError, TypeError, ValueError):
            return self._invalid(ctx.symbol, "INVALID_CANDLES")
        if any(price <= 0 for price in closes):
            return self._invalid(ctx.symbol, "INVALID_CLOSE")

        bid = ctx.book.best_bid()
        ask = ctx.book.best_ask()
        if bid is None or ask is None or bid.price <= 0 or ask.price <= bid.price:
            return self._invalid(ctx.symbol, "INVALID_ORDERBOOK")
        bid_price = float(bid.price)
        ask_price = float(ask.price)
        mid = (bid_price + ask_price) / 2.0
        spread_bps = (ask_price - bid_price) / mid * 10_000.0
        if spread_bps <= 0 or spread_bps > self.max_spread_bps:
            return OpportunityScore(
                symbol=ctx.symbol,
                score=0.0,
                eligible=False,
                direction="NEUTRAL",
                spread_bps=spread_bps,
                components={"spread_quality": 0.0},
                reason="SPREAD_TOO_WIDE",
            )

        lookback = min(self.momentum_lookback, len(closes) - 1)
        momentum_raw = closes[-1] / closes[-1 - lookback] - 1.0
        momentum = _clip(abs(momentum_raw) / 0.01)

        returns = [
            abs(closes[index] / closes[index - 1] - 1.0)
            for index in range(max(1, len(closes) - 20), len(closes))
        ]
        volatility = _clip((fmean(returns) if returns else 0.0) / 0.003)

        recent_volume = fmean(volumes[-5:]) if volumes[-5:] else 0.0
        baseline_slice = volumes[-25:-5]
        baseline_volume = fmean(baseline_slice) if baseline_slice else 0.0
        if baseline_volume > 0:
            volume_ratio = recent_volume / baseline_volume
            volume_impulse = _clip(max(volume_ratio - 1.0, 0.0) / 1.5)
        else:
            volume_impulse = 0.0

        bid_qty = sum(float(level.quantity) for level in list(ctx.book.bids.values())[:10])
        ask_qty = sum(float(level.quantity) for level in list(ctx.book.asks.values())[:10])
        depth_total = bid_qty + ask_qty
        signed_imbalance = (bid_qty - ask_qty) / depth_total if depth_total > 0 else 0.0
        orderbook_imbalance = _clip(abs(signed_imbalance))

        funding = abs(float(ctx.funding)) if ctx.funding is not None else 0.0
        basis = abs(float(ctx.basis)) if ctx.basis is not None else 0.0
        derivatives = max(_clip(funding / 0.001), _clip(basis / 0.003))

        spread_quality = _clip(1.0 - spread_bps / self.max_spread_bps)
        raw_score = (
            0.30 * momentum
            + 0.25 * volume_impulse
            + 0.15 * volatility
            + 0.20 * orderbook_imbalance
            + 0.10 * derivatives
        )
        final_score = _clip(raw_score * spread_quality)

        direction_pressure = momentum_raw * 100.0 + signed_imbalance * 0.25
        if direction_pressure > 0.05:
            direction = "LONG_BIAS"
        elif direction_pressure < -0.05:
            direction = "SHORT_BIAS"
        else:
            direction = "NEUTRAL"

        components = {
            "momentum": momentum,
            "volume_impulse": volume_impulse,
            "volatility": volatility,
            "orderbook_imbalance": orderbook_imbalance,
            "derivatives": derivatives,
            "spread_quality": spread_quality,
        }
        return OpportunityScore(
            symbol=ctx.symbol,
            score=final_score,
            eligible=final_score >= self.min_score,
            direction=direction,
            spread_bps=spread_bps,
            components=components,
            reason="OK" if final_score >= self.min_score else "SCORE_BELOW_THRESHOLD",
        )

    def _invalid(self, symbol: str, reason: str) -> OpportunityScore:
        return OpportunityScore(
            symbol=symbol,
            score=0.0,
            eligible=False,
            direction="NEUTRAL",
            spread_bps=0.0,
            components={},
            reason=reason,
        )
