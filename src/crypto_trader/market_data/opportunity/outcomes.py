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

from sqlalchemy import select

HORIZONS = ("1m", "5m", "15m", "30m", "1h", "4h", "12h", "24h")
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
    future_high: float | None = None
    future_low: float | None = None
    realized_volatility: float = 0.0
    long_gross_bps: float = 0.0
    short_gross_bps: float = 0.0
    long_net_bps: float = 0.0
    short_net_bps: float = 0.0
    all_in_cost_bps: float = 0.0
    net_edge_bps: float = 0.0
    min_edge_bps: float = 0.0
    net_edge_label: str = "NOT_PROFITABLE"
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
    min_edge_bps: float = 0.0,
) -> list[OpportunityOutcome]:
    """Evaluate every supplied horizon; missing horizons are skipped."""
    path = [float(p) for p in (path_prices or [])]
    outcomes: list[OpportunityOutcome] = []
    for horizon in HORIZONS:
        if horizon not in window_prices:
            continue
        target = float(window_prices[horizon])
        raw_move = (target - float(frozen_price)) / float(frozen_price) * 10000.0
        long_gross = raw_move
        short_gross = -raw_move
        cost = float(all_in_cost_bps)
        gross = _signed_return_bps(frozen_price, window_prices[horizon], expected_direction)
        net = gross - cost
        long_net = long_gross - cost
        short_net = short_gross - cost
        future_high = max(path) if path else target
        future_low = min(path) if path else target
        realized_vol = 0.0
        if len(path) >= 3:
            returns = [
                (path[i] - path[i - 1]) / path[i - 1] for i in range(1, len(path)) if path[i - 1]
            ]
            if len(returns) >= 2:
                mean = sum(returns) / len(returns)
                variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
                realized_vol = (variance**0.5) * 10000.0
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
                future_high=round(future_high, 10),
                future_low=round(future_low, 10),
                realized_volatility=round(realized_vol, 6),
                long_gross_bps=round(long_gross, 6),
                short_gross_bps=round(short_gross, 6),
                long_net_bps=round(long_net, 6),
                short_net_bps=round(short_net, 6),
                all_in_cost_bps=round(cost, 6),
                net_edge_bps=round(net, 6),
                min_edge_bps=round(float(min_edge_bps), 6),
                net_edge_label=("PROFITABLE" if net > float(min_edge_bps) else "NOT_PROFITABLE"),
            )
        )
    return outcomes


class OpportunityOutcomeRecorder:
    """Persist post-freeze evaluations; learning/observability only."""

    authority = "LEARNING_ONLY"
    is_order = False

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def record(
        self,
        *,
        trading_day: str,
        symbol: str,
        outcomes: list[OpportunityOutcome],
    ) -> int:
        from crypto_trader.persistence.models import OpportunityOutcomeORM

        written = 0
        async with self._session_factory() as session:
            for outcome in outcomes:
                row = (
                    await session.execute(
                        select(OpportunityOutcomeORM).where(
                            OpportunityOutcomeORM.trading_day == trading_day,
                            OpportunityOutcomeORM.symbol == symbol,
                            OpportunityOutcomeORM.horizon == outcome.horizon,
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    row = OpportunityOutcomeORM(
                        trading_day=trading_day, symbol=symbol, horizon=outcome.horizon
                    )
                    session.add(row)
                row.expected_direction = outcome.expected_direction
                row.traded = outcome.traded
                row.return_bps = outcome.return_bps
                row.net_return_bps = outcome.net_return_bps
                row.mfe_bps = outcome.mfe_bps
                row.mae_bps = outcome.mae_bps
                row.label = outcome.label
                row.future_high = outcome.future_high
                row.future_low = outcome.future_low
                row.realized_volatility = outcome.realized_volatility
                row.long_gross_bps = outcome.long_gross_bps
                row.short_gross_bps = outcome.short_gross_bps
                row.long_net_bps = outcome.long_net_bps
                row.short_net_bps = outcome.short_net_bps
                row.all_in_cost_bps = outcome.all_in_cost_bps
                row.net_edge_bps = outcome.net_edge_bps
                row.min_edge_bps = outcome.min_edge_bps
                row.net_edge_label = outcome.net_edge_label
                written += 1
            await session.commit()
        return written

    async def list_for_day(self, trading_day: str) -> list[dict]:
        from crypto_trader.persistence.models import OpportunityOutcomeORM

        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(OpportunityOutcomeORM)
                        .where(OpportunityOutcomeORM.trading_day == trading_day)
                        .order_by(
                            OpportunityOutcomeORM.symbol.asc(),
                            OpportunityOutcomeORM.horizon.asc(),
                        )
                    )
                )
                .scalars()
                .all()
            )
        return [
            {
                "symbol": row.symbol,
                "horizon": row.horizon,
                "expected_direction": row.expected_direction,
                "traded": row.traded,
                "return_bps": row.return_bps,
                "net_return_bps": row.net_return_bps,
                "mfe_bps": row.mfe_bps,
                "mae_bps": row.mae_bps,
                "label": row.label,
                "future_high": row.future_high,
                "future_low": row.future_low,
                "realized_volatility": row.realized_volatility,
                "long_gross_bps": row.long_gross_bps,
                "short_gross_bps": row.short_gross_bps,
                "long_net_bps": row.long_net_bps,
                "short_net_bps": row.short_net_bps,
                "all_in_cost_bps": row.all_in_cost_bps,
                "net_edge_bps": row.net_edge_bps,
                "min_edge_bps": row.min_edge_bps,
                "net_edge_label": row.net_edge_label,
            }
            for row in rows
        ]

    async def summary(self, trading_day: str) -> dict:
        rows = await self.list_for_day(trading_day)
        counts: dict[str, int] = {label: 0 for label in LABELS}
        for row in rows:
            counts[row["label"]] = counts.get(row["label"], 0) + 1
        return {
            "trading_day": trading_day,
            "rows": len(rows),
            "labels": counts,
            "authority": self.authority,
            "not_an_order": True,
        }
