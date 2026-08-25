"""Regime classifier from factor snapshots."""

from __future__ import annotations

from crypto_trader.domain.money import D
from crypto_trader.factors.regime.detector import MarketRegimeDetector


class RegimeClassifier:
    def classify(self, symbol: str, factor_snapshot: dict) -> dict:
        factors = factor_snapshot.get("market_state", factor_snapshot)
        detector = MarketRegimeDetector()
        regime = detector.detect(
            symbol,
            trend_strength=D(str(factors.get("trend", "0"))),
            volatility=D(str(factors.get("volatility", "0"))),
            volume_change=D(str(factors.get("volume", "0"))),
            oi_change=D(str(factors.get("open_interest", "0"))),
            funding=D(str(factors.get("funding", "0"))),
            price_change=D(str(factors.get("return", "0"))),
        )
        return regime.to_dict()
