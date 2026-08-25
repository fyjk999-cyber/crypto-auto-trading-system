"""Factor attribution: decompose trade result into factor contributions."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.money import D
from crypto_trader.factors.models import FactorAttributionResult


class FactorAttribution:
    def attribute(
        self, *, trade_id: str, result: str, pnl_pct: Decimal, entry_snapshot: dict
    ) -> FactorAttributionResult:
        pnl = D(pnl_pct)
        factors = entry_snapshot.get("factors", entry_snapshot)
        contributors: dict[str, Decimal] = {}
        negative: dict[str, Decimal] = {}
        total_positive = D("0")
        for _name, value in factors.items():
            val = D(str(value)) if not isinstance(value, Decimal) else value
            if val > 0:
                total_positive += abs(val)
        if total_positive == 0:
            total_positive = D("1")
        for name, value in factors.items():
            val = D(str(value)) if not isinstance(value, Decimal) else value
            contribution = pnl * val / total_positive
            if contribution >= 0:
                contributors[name] = contribution
            else:
                negative[name] = contribution
        return FactorAttributionResult(trade_id, result, contributors, negative)
