"""Dynamic leverage: advisory only. Outputs recommended_leverage."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.alpha.meta_decision import MetaDecision
from crypto_trader.alpha.regime import MarketRegime
from crypto_trader.alpha.sub_strategy.base import AlphaSide
from crypto_trader.domain.money import D


def recommend_leverage(
    meta: MetaDecision,
    *,
    regime: MarketRegime,
    volatility,
    max_leverage: str = "5",
) -> Decimal:
    if meta.side == AlphaSide.NO_TRADE:
        return D("0")
    max_lev = D(max_leverage)
    vol = D(volatility)
    if regime == MarketRegime.EXTREME_RISK:
        base = max_lev * D("0.25")
    elif regime == MarketRegime.HIGH_VOL:
        base = max_lev * D("0.50")
    elif regime == MarketRegime.RANGE:
        base = max_lev * D("0.70")
    else:
        base = max_lev * D("0.85")
    # volatility penalty: higher vol -> lower leverage
    if vol > 0:
        base = base / (D("1") + vol * D("50"))
    return min(max_lev, max(D("0"), base))
