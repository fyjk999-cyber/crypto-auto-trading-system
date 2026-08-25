"""Market anomaly detector."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnomalyEvent:
    symbol: str
    anomaly_type: str
    severity: float
    description: str


class AnomalyDetector:
    def detect(
        self,
        *,
        symbol: str,
        volume_ratio: float,
        oi_change_pct: float,
        funding: float,
        spread_bps: float,
        price_change_pct: float,
    ) -> list[AnomalyEvent]:
        events = []
        if volume_ratio > 3:
            events.append(AnomalyEvent(symbol, "VOLUME_SPIKE", 0.8, "volume > 3x average"))
        if abs(oi_change_pct) > 20:
            events.append(AnomalyEvent(symbol, "OI_EXPLOSION", 0.7, "OI change > 20%"))
        if abs(funding) > 0.001:
            events.append(AnomalyEvent(symbol, "FUNDING_EXTREME", 0.6, "funding extreme"))
        if spread_bps > 50:
            events.append(AnomalyEvent(symbol, "SPREAD_ABNORMAL", 0.5, "spread > 50bps"))
        if abs(price_change_pct) > 8:
            events.append(AnomalyEvent(symbol, "PRICE_ANOMALY", 0.8, "large price move"))
        return events
