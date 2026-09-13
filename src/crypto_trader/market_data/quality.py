"""Unified factual data-quality contract (Market Intelligence V1, Gate 1).

One lightweight reusable representation for every important market fact so
that observer / selection / evidence layers can always distinguish:

    "this fact is a valid zero"
from
    "this fact is missing / failed / stale / unsupported"

Authority impact: NONE. A quality state never grants direction or permission;
it only prevents unproven values from being presented as facts (and therefore
prevents them from entering ranking, factor strength, liquidity comparison,
OI change, turnover calculation or market-selection context).

Design notes:
    * ``Fact`` is deliberately small; not every internal object must adopt it.
    * ``ESTIMATED`` is NOT ``VALID``: derived approximations (e.g. estimated
      quote turnover) keep their own quality state and unit label.
    * ``UNSUPPORTED`` means the provider/instrument/field combination cannot
      supply the fact at all; ``NOT_SAMPLED`` means the fact IS supported but
      was not collected in the current bounded cycle. The two must never be
      conflated: a rotating coverage gap is not provider incapability and not a
      runtime failure.
    * Numeric and timestamp integrity helpers return facts, they never raise
      on bad provider input (a provider cannot crash the scanner).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------- quality states
VALID = "VALID"
MISSING = "MISSING"
STALE = "STALE"
FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"
NON_FINITE = "NON_FINITE"
REQUEST_FAILED = "REQUEST_FAILED"
UNSUPPORTED = "UNSUPPORTED"
# Supported by the provider, but intentionally not collected in THIS cycle
# (bounded / rotating coverage). Must never be read as "this market has no such
# fact" — that is what UNSUPPORTED means.
NOT_SAMPLED = "NOT_SAMPLED"
ESTIMATED = "ESTIMATED"
PARTIAL = "PARTIAL"
MALFORMED = "MALFORMED"

ALL_QUALITY_STATES = (
    VALID,
    MISSING,
    STALE,
    FUTURE_TIMESTAMP,
    NON_FINITE,
    REQUEST_FAILED,
    UNSUPPORTED,
    NOT_SAMPLED,
    ESTIMATED,
    PARTIAL,
    MALFORMED,
)

#: states describing a provider/instrument/field limitation (capability)
LIMITATION_QUALITY_STATES = frozenset({UNSUPPORTED, MALFORMED})
#: states describing bounded collection, not provider incapability
COVERAGE_QUALITY_STATES = frozenset({NOT_SAMPLED, MISSING})

# facts with these states may be used for computation/observation
USABLE_QUALITY_STATES = frozenset({VALID, ESTIMATED, PARTIAL})

DEFAULT_MAX_FUTURE_SKEW_SECONDS = 5.0


def is_usable(quality: str | None) -> bool:
    return quality in USABLE_QUALITY_STATES


@dataclass(frozen=True, slots=True)
class Fact:
    """A single factual value with provenance and quality."""

    value: Any | None
    source: str
    observed_at: datetime | None = None
    received_at: datetime | None = None
    unit: str | None = None
    quality: str = MISSING
    reason: str | None = None

    @property
    def usable(self) -> bool:
        return is_usable(self.quality)

    def as_dict(self) -> dict:
        return {
            "value": self.value,
            "source": self.source,
            "observed_at": _iso(self.observed_at),
            "received_at": _iso(self.received_at),
            "unit": self.unit,
            "quality": self.quality,
            "reason": self.reason,
        }


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def numeric_fact(
    raw: Any,
    *,
    source: str,
    unit: str | None = None,
    observed_at: datetime | None = None,
    received_at: datetime | None = None,
    allow_negative: bool = True,
    allow_zero: bool = True,
) -> Fact:
    """Parse a provider numeric into a :class:`Fact` with integrity checks.

    Rejects NaN / Infinity / -Infinity / malformed decimals / impossible
    negatives instead of letting them flow into factor math.
    """
    received_at = received_at or datetime.now(UTC)
    if raw is None or raw == "":
        return Fact(None, source, observed_at, received_at, unit, MISSING, "value absent")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return Fact(
            None, source, observed_at, received_at, unit, MALFORMED, "not a decimal number"
        )
    if math.isnan(value):
        return Fact(None, source, observed_at, received_at, unit, NON_FINITE, "NaN")
    if math.isinf(value):
        return Fact(None, source, observed_at, received_at, unit, NON_FINITE, "Infinity")
    if not allow_negative and value < 0:
        return Fact(
            None, source, observed_at, received_at, unit, MALFORMED, "negative value impossible"
        )
    if not allow_zero and value == 0:
        return Fact(
            None, source, observed_at, received_at, unit, MALFORMED, "zero value impossible"
        )
    return Fact(value, source, observed_at, received_at, unit, VALID)


def timestamp_fact(
    raw_ms: Any,
    *,
    now: datetime,
    source: str,
    max_age_seconds: float | None = None,
    max_future_skew_seconds: float = DEFAULT_MAX_FUTURE_SKEW_SECONDS,
    unit: str = "ms_epoch",
) -> tuple[datetime | None, str, str | None]:
    """Validate a provider timestamp independently of value freshness.

    Returns ``(observed_at, quality, reason)``. A missing timestamp is MISSING,
    not "fresh"; a future timestamp beyond the allowed skew is
    FUTURE_TIMESTAMP — it must never be clamped to age 0 downstream.
    """
    if raw_ms is None or raw_ms == "":
        return None, MISSING, "timestamp absent"
    try:
        ts = float(raw_ms)
    except (TypeError, ValueError):
        return None, MALFORMED, "timestamp malformed"
    if math.isnan(ts) or math.isinf(ts):
        return None, NON_FINITE, "timestamp non-finite"
    try:
        observed = datetime.fromtimestamp(ts / 1000.0, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None, MALFORMED, "timestamp out of range"
    skew = (observed - now.astimezone(UTC)).total_seconds()
    if skew > max_future_skew_seconds:
        return observed, FUTURE_TIMESTAMP, f"timestamp {skew:.1f}s in the future"
    if max_age_seconds is not None and -skew > max_age_seconds:
        return observed, STALE, f"timestamp {-skew:.1f}s old"
    return observed, VALID, None


def age_seconds(observed_at: datetime | None, *, now: datetime) -> float | None:
    """Honest age: negative (future) ages are returned as-is, never clamped."""
    if observed_at is None:
        return None
    observed = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=UTC)
    return (now.astimezone(UTC) - observed.astimezone(UTC)).total_seconds()


# ------------------------------------------------------------------- candle truth
@dataclass(frozen=True, slots=True)
class CandleTruth:
    """Factual coverage report for one candle request (§5.5).

    ``requested_count`` is NOT history coverage: it is what we asked for.
    Analysis eligibility must use ``contiguous_tail_count`` / ``analysis_ready``.
    """

    requested_count: int
    received_count: int
    closed_count: int
    unique_closed_count: int
    contiguous_tail_count: int
    gap_count: int
    latest_closed_at: datetime | None = None
    quality: str = MISSING
    reason: str | None = None

    @property
    def analysis_ready(self) -> bool:
        return self.contiguous_tail_count > 0 and self.quality in {VALID, PARTIAL}

    def as_dict(self) -> dict:
        return {
            "requested_count": self.requested_count,
            "received_count": self.received_count,
            "closed_count": self.closed_count,
            "unique_closed_count": self.unique_closed_count,
            "contiguous_tail_count": self.contiguous_tail_count,
            "gap_count": self.gap_count,
            "latest_closed_at": _iso(self.latest_closed_at),
            "quality": self.quality,
            "reason": self.reason,
            "analysis_ready": self.analysis_ready,
            "coverage_ratio": (
                round(self.unique_closed_count / self.requested_count, 4)
                if self.requested_count
                else 0.0
            ),
            "candles_available_is_requested_count": False,
        }


def build_candle_truth(
    *,
    requested_count: int,
    rows: list[list],
    bar_seconds: float,
    now: datetime,
    confirm_index: int = 8,
    open_index: int = 0,
    max_future_skew_seconds: float = DEFAULT_MAX_FUTURE_SKEW_SECONDS,
) -> tuple[list[tuple[int, list]], CandleTruth]:
    """Filter/validate raw OKX candle rows and report factual coverage.

    Returns ``(closed_rows_deduped_ascending, truth)``. Only CLOSED candles
    (confirm == '1') are accepted for historical factor computation.
    Rows are deduplicated by candle open timestamp; temporal ordering and
    gaps are measured on the deduplicated closed series.
    """
    received = len(rows)
    invalids = 0
    future = 0
    closed: dict[int, list] = {}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) <= confirm_index:
            invalids += 1
            continue
        if str(row[confirm_index]) != "1":
            continue
        ts_ms, _, _, _, _, _, _, _, _ = (list(row) + [None] * 9)[:9]
        try:
            ts = int(float(ts_ms))
        except (TypeError, ValueError):
            invalids += 1
            continue
        observed = datetime.fromtimestamp(ts / 1000.0, tz=UTC)
        if (observed - now.astimezone(UTC)).total_seconds() > max_future_skew_seconds:
            future += 1
            continue
        closed[ts] = list(row)

    ordered = sorted(closed.items())
    unique_closed = len(ordered)
    latest = (
        datetime.fromtimestamp(ordered[-1][0] / 1000.0, tz=UTC) if ordered else None
    )
    gap_count = 0
    contiguous_tail = 0
    if ordered:
        contiguous_tail = 1
        for (prev_ts, _), (cur_ts, _) in zip(ordered, ordered[1:], strict=False):
            step = (cur_ts - prev_ts) / 1000.0
            if step > bar_seconds * 1.5:
                gap_count += 1
                contiguous_tail = 1
            else:
                contiguous_tail += 1

    if not ordered:
        quality = MALFORMED if invalids else MISSING
        reason = (
            f"no closed candles in response (invalid_rows={invalids}, "
            f"future_rows={future})"
            if invalids or future
            else "provider returned no closed candles"
        )
    elif gap_count or future or invalids:
        quality = PARTIAL
        reason = (
            f"closed candles usable but incomplete "
            f"(gaps={gap_count}, future_rows={future}, invalid_rows={invalids})"
        )
    else:
        quality = VALID
        reason = None
    truth = CandleTruth(
        requested_count=int(requested_count),
        received_count=received,
        closed_count=received - invalids - sum(1 for r in rows if _is_open(r, confirm_index)),
        unique_closed_count=unique_closed,
        contiguous_tail_count=contiguous_tail,
        gap_count=gap_count,
        latest_closed_at=latest,
        quality=quality,
        reason=reason,
    )
    return ordered, truth


def _is_open(row, confirm_index: int) -> bool:
    try:
        return str(row[confirm_index]) != "1"
    except Exception:
        return True
