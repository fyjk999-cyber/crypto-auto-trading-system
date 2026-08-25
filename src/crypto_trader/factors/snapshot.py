"""Factor snapshot builder."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.factors.models import FactorResult, FactorSnapshot


class SnapshotBuilder:
    def build(self, symbol: str, timeframe: str, results: list[FactorResult]) -> FactorSnapshot:
        snapshot = FactorSnapshot(symbol=symbol, timeframe=timeframe)
        for r in results:
            snapshot.factors[r.factor_name] = r.value
            snapshot.confidence[r.factor_name] = r.confidence
        snapshot.market_state = {
            "trend": _to_float(snapshot.factors.get("trend")),
            "momentum": _to_float(snapshot.factors.get("momentum")),
            "volatility": _to_float(snapshot.factors.get("volatility")),
            "orderflow": _to_float(snapshot.factors.get("orderflow")),
            "funding": _to_float(snapshot.factors.get("funding")),
            "open_interest": _to_float(snapshot.factors.get("open_interest")),
        }
        return snapshot


def _to_float(value: Decimal | None) -> float:
    return float(value) if value is not None else 0.0
