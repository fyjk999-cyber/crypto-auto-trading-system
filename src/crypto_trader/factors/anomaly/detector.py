"""Market anomaly detector (data-driven, no LLM)."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.money import D
from crypto_trader.factors.anomaly.models import MarketAnomaly


class MarketAnomalyDetector:
    def detect(
        self,
        symbol: str,
        *,
        price_change: Decimal,
        volume_change: Decimal,
        orderflow: Decimal,
        oi_change: Decimal,
        funding: Decimal,
        volatility: Decimal,
        volatility_previous: Decimal,
    ) -> list[MarketAnomaly]:
        anomalies: list[MarketAnomaly] = []
        price = D(price_change)
        volume = D(volume_change)
        orderflow = D(orderflow)
        oi = D(oi_change)
        funding = D(funding)
        vol = D(volatility)
        vol_prev = D(volatility_previous)
        if price > 0 and volume < -0.1:
            anomalies.append(
                MarketAnomaly("price_volume_divergence", symbol, 0.6, ["price up", "volume down"])
            )
        if orderflow > 0.3 and abs(price) < 0.001:
            anomalies.append(
                MarketAnomaly("orderflow_failure", symbol, 0.7, ["buy pressure", "price stagnant"])
            )
        if price > 0 and oi < -0.05:
            anomalies.append(MarketAnomaly("oi_divergence", symbol, 0.65, ["price up", "OI down"]))
        if abs(funding) > 0.0005:
            anomalies.append(
                MarketAnomaly(
                    "funding_extreme",
                    symbol,
                    min(0.9, float(abs(funding) * 2000)),
                    ["funding extreme"],
                )
            )
        if vol > 0.6 and vol_prev < 0.3:
            anomalies.append(
                MarketAnomaly("volatility_regime_shift", symbol, 0.8, ["low vol -> high vol"])
            )
        return anomalies
