"""Anomaly detection rules."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class AnomalyRule:
    name: str
    description: str
    min_severity: Decimal = D("0.5")


RULES = [
    AnomalyRule("price_volume_divergence", "price up but volume down"),
    AnomalyRule("orderflow_failure", "buy pressure without price expansion"),
    AnomalyRule("oi_divergence", "price up but OI down"),
    AnomalyRule("funding_extreme", "funding abnormal"),
    AnomalyRule("volatility_regime_shift", "low vol suddenly spikes"),
]
