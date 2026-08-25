"""Feature extraction for similarity."""

from __future__ import annotations


def feature_vector(regime: str, factors: dict) -> tuple[float, ...]:
    return (
        1.0 if regime == "TRENDING" else 0.0,
        1.0 if regime == "HIGH_VOLATILITY" else 0.0,
        float(factors.get("trend", 0)),
        float(factors.get("momentum", 0)),
        float(factors.get("volatility", 0)),
        float(factors.get("orderflow", 0)),
        float(factors.get("funding", 0)),
        float(factors.get("open_interest", 0)),
    )
