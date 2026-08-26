"""Canonical review schedule times in UTC."""

from __future__ import annotations

from datetime import UTC, datetime, time


def should_trigger(period_type: str, now: datetime) -> bool:
    utc = now.astimezone(UTC)
    t = utc.time()
    if period_type == "DAILY":
        return t == time(0, 5)
    if period_type == "WEEKLY":
        return utc.weekday() == 0 and t == time(0, 5)
    if period_type == "MONTHLY":
        return utc.day == 1 and t == time(0, 5)
    if period_type == "YEARLY":
        return utc.month == 1 and utc.day == 1 and t == time(0, 5)
    return False


ORDER = ["DAILY", "WEEKLY", "MONTHLY", "YEARLY"]
