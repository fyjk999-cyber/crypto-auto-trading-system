"""Review period calculation in UTC. Never uses machine-local timezone."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta


@dataclass
class ReviewPeriod:
    period_type: str  # DAILY | WEEKLY | MONTHLY | YEARLY
    period_id: str
    starts_at: datetime
    ends_at: datetime
    triggered_at: datetime
    timezone: str = "UTC"


def previous_daily(now: datetime) -> ReviewPeriod:
    today = now.astimezone(UTC).date()
    start_dt = datetime.combine(today - timedelta(days=1), time.min, tzinfo=UTC)
    end_dt = datetime.combine(today - timedelta(days=1), time.max, tzinfo=UTC)
    return ReviewPeriod("DAILY", (today - timedelta(days=1)).isoformat(), start_dt, end_dt, now)


def previous_weekly(now: datetime) -> ReviewPeriod:
    today = now.astimezone(UTC).date()
    monday = today - timedelta(days=today.weekday())
    prev_monday = monday - timedelta(weeks=1)
    start_dt = datetime.combine(prev_monday, time.min, tzinfo=UTC)
    end_dt = datetime.combine(prev_monday + timedelta(days=6), time.max, tzinfo=UTC)
    iso = prev_monday.isocalendar()
    return ReviewPeriod("WEEKLY", f"{iso.year}-W{iso.week:02d}", start_dt, end_dt, now)


def previous_monthly(now: datetime) -> ReviewPeriod:
    today = now.astimezone(UTC).date()
    if today.month == 1:
        year, month = today.year - 1, 12
    else:
        year, month = today.year, today.month - 1
    start_dt = datetime(year, month, 1, tzinfo=UTC)
    if month == 12:
        end_month = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        end_month = datetime(year, month + 1, 1, tzinfo=UTC)
    end_dt = end_month - timedelta(microseconds=1)
    return ReviewPeriod("MONTHLY", f"{year}-{month:02d}", start_dt, end_dt, now)


def previous_yearly(now: datetime) -> ReviewPeriod:
    year = now.astimezone(UTC).year - 1
    start_dt = datetime(year, 1, 1, tzinfo=UTC)
    end_dt = datetime(year, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
    return ReviewPeriod("YEARLY", str(year), start_dt, end_dt, now)


def period_for(period_type: str, now: datetime) -> ReviewPeriod:
    return {
        "DAILY": previous_daily,
        "WEEKLY": previous_weekly,
        "MONTHLY": previous_monthly,
        "YEARLY": previous_yearly,
    }[period_type.upper()](now)
