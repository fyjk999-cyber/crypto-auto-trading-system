"""Performance attribution engine."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class AttributionResult:
    strategy_contribution: Decimal
    regime_contribution: Decimal
    coin_selection_contribution: Decimal
    entry_timing_contribution: Decimal
    exit_timing_contribution: Decimal
    leverage_contribution: Decimal
    risk_management_contribution: Decimal
    luck_factor: Decimal
    confidence: Decimal


class AttributionEngine:
    def attribute(
        self,
        *,
        pnl_pct: Decimal,
        strategy_alpha: Decimal,
        regime_fit: Decimal,
        coin_alpha: Decimal,
        entry_alpha: Decimal,
        exit_alpha: Decimal,
        leverage_effect: Decimal,
        risk_effect: Decimal,
    ) -> AttributionResult:
        total = (
            abs(strategy_alpha)
            + abs(regime_fit)
            + abs(coin_alpha)
            + abs(entry_alpha)
            + abs(exit_alpha)
            + abs(leverage_effect)
            + abs(risk_effect)
        )
        if total == 0:
            total = Decimal("1")
        scale = Decimal(pnl_pct) / total
        return AttributionResult(
            strategy_contribution=strategy_alpha * scale,
            regime_contribution=regime_fit * scale,
            coin_selection_contribution=coin_alpha * scale,
            entry_timing_contribution=entry_alpha * scale,
            exit_timing_contribution=exit_alpha * scale,
            leverage_contribution=leverage_effect * scale,
            risk_management_contribution=risk_effect * scale,
            luck_factor=max(
                Decimal("0"),
                Decimal(pnl_pct)
                - (
                    strategy_alpha
                    + regime_fit
                    + coin_alpha
                    + entry_alpha
                    + exit_alpha
                    + leverage_effect
                    + risk_effect
                )
                * scale,
            ),
            confidence=Decimal("0.7"),
        )
