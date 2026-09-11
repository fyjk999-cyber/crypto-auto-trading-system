"""Eligibility filter (MASTER DIRECTIVE §9).

Answers ONLY: "Can this market be safely observed?"
It must NEVER encode trade direction. A symbol rejected here is excluded
from observation/scanning for operational safety — that is all. Symbols not
rejected stay fully eligible for DeepSeek attention, with or without any
factor trigger (§3: FACTOR_REQUIRED_FOR_TRADE = FALSE).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EligibilityLimits:
    """Stable operational configuration (§43: thresholds are config, not live-mutated)."""

    min_volume_24h_usd: float = 1_000_000.0
    max_spread_bps: float = 50.0
    min_candles_for_scan: int = 60
    max_ticker_age_seconds: float = 120.0


@dataclass(slots=True)
class EligibilityResult:
    symbol: str
    eligible: bool
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"symbol": self.symbol, "eligible": self.eligible, "reasons": self.reasons}


class EligibilityFilter:
    """Operational/market-quality gate over factual ticker + history facts."""

    def __init__(self, limits: EligibilityLimits | None = None) -> None:
        self.limits = limits or EligibilityLimits()

    def evaluate(
        self,
        symbol: str,
        *,
        last_price: float | None,
        bid: float | None,
        ask: float | None,
        volume_24h_usd: float | None,
        ticker_age_seconds: float | None,
        candle_count: int,
        ticker_timestamp_quality: str | None = None,
    ) -> EligibilityResult:
        reasons: list[str] = []
        lim = self.limits
        if last_price is None or last_price <= 0:
            reasons.append("NO_FACTUAL_PRICE")
        if volume_24h_usd is None:
            reasons.append("NO_VOLUME_FACT")
        elif volume_24h_usd < lim.min_volume_24h_usd:
            reasons.append("LOW_LIQUIDITY")
        if bid is not None and ask is not None and bid > 0 and ask > 0:
            if ask < bid:
                reasons.append("CROSSED_BOOK")
            else:
                spread_bps = (ask - bid) / ((ask + bid) / 2.0) * 10_000.0
                if spread_bps > lim.max_spread_bps:
                    reasons.append("WIDE_SPREAD")
        else:
            reasons.append("NO_BOOK_FACTS")
        # §5.3: a future / malformed / missing ticker timestamp must never be
        # treated as proof of freshness. Only an explicitly VALID timestamp
        # quality is accepted; callers that pass no quality keep the legacy
        # age-only behaviour.
        if ticker_timestamp_quality is not None and ticker_timestamp_quality != "VALID":
            reasons.append(f"TICKER_TIMESTAMP_{ticker_timestamp_quality}")
        if ticker_age_seconds is not None and ticker_age_seconds > lim.max_ticker_age_seconds:
            reasons.append("STALE_TICKER")
        if candle_count < lim.min_candles_for_scan:
            reasons.append("INSUFFICIENT_HISTORY")
        return EligibilityResult(symbol=symbol, eligible=(not reasons), reasons=reasons)
