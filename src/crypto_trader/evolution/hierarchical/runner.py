"""Serial review runner using canonical scheduler order."""

from __future__ import annotations

from crypto_trader.evolution.time.review_period import period_for
from crypto_trader.evolution.time.review_schedule import ORDER


def due_periods(now) -> list[tuple[str, str]]:
    out = []
    for period_type in ORDER:
        period = period_for(period_type, now)
        out.append((period_type, period.period_id))
    return out
