"""Growth V2 opportunity outcome evaluation (Phase 5).

Classifies each daily-frozen opportunity after the fact WITHOUT changing the
frozen Top-10:

  TRADED_CORRECT / TRADED_WRONG / NOT_TRADED_CORRECTLY_AVOIDED / NOT_TRADED_MISSED

Also computes, per horizon (+15m/30m/1h/4h/12h/24h), the all-in-net return and
the maximum favourable / adverse excursion (MFE/MAE) relative to the frozen
entry price.

Learning/observability only: never an order authority.
"""

from __future__ import annotations

from dataclasses import dataclass

HORIZONS = ("15m", "30m", "1h", "4h", "12h", "24h")
LABELS = (
    "TRADED_CORRECT",
    "TRADED_WRONG",
    "NOT_TRADED_CORRECTLY_AVOIDED",
    "NOT_TRADED_MISSED",
)


@dataclass
class OpportunityOutcome:
    horizon: str
    expected_direction: str
    return_bps: float
    net_return_bps: float
    mfe_bps: float
    mae_bps: float
    label: str
    traded: bool
    authority: str = "LEARNING_ONLY"
    is_order: bool = False


def _signed_return_bps(frozen_price: float, price: float, direction: str) -> float:
    move = (float(price) - float(frozen_price)) / float(frozen_price) * 10000.0
    return move if direction.upper() == "LONG" else -move


def classify_outcome(
    *,
    expected_direction: str,
    traded: bool,
    net_return_bps: float,
) -> str:
    correct = net_return_bps > 0
    if traded:
        return "TRADED_CORRECT" if correct else "TRADED_WRONG"
    return "NOT_TRADED_MISSED" if correct else "NOT_TRADED_CORRECTLY_AVOIDED"


def evaluate_opportunity(
    *,
    frozen_price: float,
    expected_direction: str,
    traded: bool,
    window_prices: dict[str, float],
    path_prices: list[float] | None = None,
    all_in_cost_bps: float = 0.0,
) -> list[OpportunityOutcome]:
    """Evaluate every supplied horizon; missing horizons are skipped."""
    path = [float(p) for p in (path_prices or [])]
    outcomes: list[OpportunityOutcome] = []
    for horizon in HORIZONS:
        if horizon not in window_prices:
            continue
        gross = _signed_return_bps(frozen_price, window_prices[horizon], expected_direction)
        net = gross - float(all_in_cost_bps)
        if path:
            excursions = [
                _signed_return_bps(frozen_price, price, expected_direction) for price in path
            ]
            mfe = max(excursions)
            mae = min(excursions)
        else:
            mfe = max(gross, 0.0)
            mae = min(gross, 0.0)
        outcomes.append(
            OpportunityOutcome(
                horizon=horizon,
                expected_direction=expected_direction.upper(),
                return_bps=round(gross, 6),
                net_return_bps=round(net, 6),
                mfe_bps=round(mfe, 6),
                mae_bps=round(mae, 6),
                label=classify_outcome(
                    expected_direction=expected_direction, traded=traded, net_return_bps=net
                ),
                traded=traded,
            )
        )
    return outcomes
