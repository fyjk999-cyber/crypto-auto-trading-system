"""Correlation proxy and portfolio beta."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.money import D


class CorrelationEngine:
    def correlation_proxy(self, returns_a: list[Decimal], returns_b: list[Decimal]) -> Decimal:
        if len(returns_a) < 2 or len(returns_a) != len(returns_b):
            return D("0")
        mean_a = sum(returns_a, D("0")) / Decimal(len(returns_a))
        mean_b = sum(returns_b, D("0")) / Decimal(len(returns_b))
        cov = sum(
            ((a - mean_a) * (b - mean_b) for a, b in zip(returns_a, returns_b, strict=False)),
            D("0"),
        )
        var_a = sum(((a - mean_a) ** 2 for a in returns_a), D("0"))
        var_b = sum(((b - mean_b) ** 2 for b in returns_b), D("0"))
        if var_a == 0 or var_b == 0:
            return D("0")
        return max(D("-1"), min(D("1"), cov / (var_a * var_b).sqrt()))

    def portfolio_beta(self, assets: list[dict]) -> Decimal:
        if not assets:
            return D("0")
        total = sum((D(str(a.get("weight_pct", "0"))) for a in assets), D("0"))
        if total == 0:
            return D("0")
        return (
            sum(
                (D(str(a.get("weight_pct", "0"))) * D(str(a.get("beta", "1"))) for a in assets),
                D("0"),
            )
            / total
        )
