"""Timestamped OI time series with fixed comparison windows (§5.7).

The previous implementation compared "last 8 observations" as if the elapsed
time between calls were constant. Network latency, failures and active-set
changes make that false, producing fake acceleration. This module stores
timestamped samples and measures change against the sample closest to
``T - window`` within an explicit tolerance.

    OI_CHANGE = (latest_oi - baseline_oi) / baseline_oi * 100

If no comparable sample exists the result is UNAVAILABLE (quality
UNSUPPORTED) — never a synthetic zero.

Windows are data-driven so future horizons (5m / 15m / 1h) can be added
without redesign. Sampling must cover the broad observable set, not only the
symbols selected for expensive candle analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_trader.market_data.quality import (
    MISSING,
    NON_FINITE,
    STALE,
    UNSUPPORTED,
    VALID,
    Fact,
    age_seconds,
)


@dataclass(frozen=True, slots=True)
class OiWindowSpec:
    """One fixed comparison window with an explicit tolerance."""

    label: str
    seconds: float
    tolerance_seconds: float


DEFAULT_OI_WINDOWS: tuple[OiWindowSpec, ...] = (
    OiWindowSpec("5m", 300.0, 90.0),
    OiWindowSpec("15m", 900.0, 180.0),
    OiWindowSpec("1h", 3600.0, 600.0),
)
DEFAULT_OI_WINDOW = "15m"


@dataclass(frozen=True, slots=True)
class OiSample:
    symbol: str
    open_interest: float
    observed_at: datetime
    source: str = "OKX /api/v5/public/open-interest"
    quality: str = VALID

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "open_interest": self.open_interest,
            "observed_at": self.observed_at.astimezone(UTC).isoformat(),
            "source": self.source,
            "quality": self.quality,
        }


@dataclass
class OiTimeSeries:
    """Bounded per-symbol timestamped OI samples + fixed-window change."""

    windows: tuple[OiWindowSpec, ...] = DEFAULT_OI_WINDOWS
    max_samples_per_symbol: int = 240
    _samples: dict[str, list[OiSample]] = field(default_factory=dict)

    # ------------------------------------------------------------------ write
    def record(self, sample: OiSample) -> bool:
        """Store one factual sample. Returns False when it was not usable.

        A provider OI of exactly ``0`` IS a valid factual zero and is stored
        (see ``window_change``: a zero baseline yields unavailable percentage
        change, never a division by zero and never a relabelled "invalid"
        fact). Negative / non-finite values are rejected.
        """
        if sample.quality != VALID or sample.open_interest is None:
            return False
        if not isinstance(sample.open_interest, float):
            return False
        value = sample.open_interest
        if value != value or value in (float("inf"), float("-inf")):  # NaN / Inf
            return False
        if value < 0:
            return False
        observed = (
            sample.observed_at
            if sample.observed_at.tzinfo
            else sample.observed_at.replace(tzinfo=UTC)
        )
        series = self._samples.setdefault(sample.symbol, [])
        # de-duplicate identical observation instants (retries / re-publishes)
        if series and series[-1].observed_at == observed:
            series[-1] = sample
        else:
            series.append(sample)
            series.sort(key=lambda s: s.observed_at)
        if len(series) > self.max_samples_per_symbol:
            del series[: -self.max_samples_per_symbol]
        return True

    # ------------------------------------------------------------------- read
    def sample_count(self, symbol: str) -> int:
        return len(self._samples.get(symbol, ()))

    def latest(self, symbol: str) -> OiSample | None:
        series = self._samples.get(symbol)
        return series[-1] if series else None

    def window_change(
        self, symbol: str, *, now: datetime, window: str = DEFAULT_OI_WINDOW
    ) -> Fact:
        """OI change vs the sample closest to ``T - window`` within tolerance."""
        spec = next((w for w in self.windows if w.label == window), None)
        if spec is None:
            # an unimplemented window is a genuine capability limitation
            return Fact(
                None,
                "oi_time_series",
                unit="pct",
                quality=UNSUPPORTED,
                reason=f"unknown OI window {window}",
            )
        series = self._samples.get(symbol) or []
        if len(series) < 2:
            # temporary evidence limitation, NOT provider incapability
            return Fact(
                None,
                "oi_time_series",
                unit="pct",
                quality=MISSING,
                reason=(
                    "OI_CHANGE_UNAVAILABLE:INSUFFICIENT_HISTORY: "
                    "fewer than two timestamped samples"
                ),
            )
        now = now if now.tzinfo else now.replace(tzinfo=UTC)
        newest = series[-1]
        newest_age = age_seconds(newest.observed_at, now=now)
        if newest_age is None or newest_age < 0:
            return Fact(
                None,
                "oi_time_series",
                unit="pct",
                quality=NON_FINITE,
                reason="OI_CHANGE_UNAVAILABLE:NON_FINITE: latest sample has no usable timestamp",
            )
        if newest_age > spec.seconds + spec.tolerance_seconds:
            return Fact(
                None,
                "oi_time_series",
                unit="pct",
                quality=STALE,
                reason=(
                    "OI_CHANGE_UNAVAILABLE:STALE: latest sample is "
                    f"{newest_age:.0f}s old, beyond window {spec.label}"
                ),
            )
        candidates = [s for s in series[:-1] if s.observed_at < newest.observed_at]
        if not candidates:
            return Fact(
                None,
                "oi_time_series",
                unit="pct",
                quality=MISSING,
                reason="OI_CHANGE_UNAVAILABLE:NO_COMPARABLE_BASELINE: no sample before latest",
            )
        baseline = min(
            candidates,
            key=lambda s: abs((age_seconds(s.observed_at, now=now) or 0.0) - spec.seconds),
        )
        baseline_age = age_seconds(baseline.observed_at, now=now) or 0.0
        if abs(baseline_age - spec.seconds) > spec.tolerance_seconds:
            return Fact(
                None,
                "oi_time_series",
                unit="pct",
                quality=MISSING,
                reason=(
                    "OI_CHANGE_UNAVAILABLE:NO_BASELINE_IN_WINDOW: nearest baseline is "
                    f"{baseline_age:.0f}s old, outside "
                    f"{spec.seconds:.0f}s±{spec.tolerance_seconds:.0f}s"
                ),
            )
        baseline_value = baseline.open_interest
        newest_value = newest.open_interest
        if not all(
            isinstance(v, float) and v == v and v not in (float("inf"), float("-inf"))
            for v in (baseline_value, newest_value)
        ):
            return Fact(
                None,
                "oi_time_series",
                unit="pct",
                quality=NON_FINITE,
                reason="OI_CHANGE_UNAVAILABLE:NON_FINITE: sample value is not finite",
            )
        if baseline_value <= 0:
            # a factual zero baseline cannot express a percentage change and is
            # never used as a denominator. The zero itself stays a valid fact.
            return Fact(
                None,
                "oi_time_series",
                unit="pct",
                quality=MISSING,
                reason=(
                    "OI_CHANGE_UNAVAILABLE:ZERO_BASELINE: baseline OI is zero; "
                    "percentage change is undefined"
                ),
            )
        change_pct = (newest_value - baseline_value) / baseline_value * 100.0
        return Fact(
            change_pct,
            "oi_time_series",
            observed_at=newest.observed_at,
            received_at=now,
            unit="pct",
            quality=VALID,
            reason=(
                f"window={spec.label} baseline_age={baseline_age:.0f}s "
                f"latest_age={newest_age:.0f}s"
            ),
        )

    def all_window_changes(self, symbol: str, *, now: datetime) -> dict[str, Fact]:
        return {w.label: self.window_change(symbol, now=now, window=w.label) for w in self.windows}

    # ------------------------------------------------------ restart durability
    def export_state(self) -> dict[str, list[dict]]:
        return {
            symbol: [s.as_dict() for s in samples]
            for symbol, samples in self._samples.items()
            if samples
        }

    def import_state(self, state: dict | None) -> int:
        if not isinstance(state, dict):
            return 0
        restored = 0
        for rows in state.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    sample = OiSample(
                        symbol=str(row["symbol"]),
                        open_interest=float(row["open_interest"]),
                        observed_at=datetime.fromisoformat(str(row["observed_at"])),
                        source=str(row.get("source", "OKX /api/v5/public/open-interest")),
                        quality=str(row.get("quality", VALID)),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                if self.record(sample):
                    restored += 1
        return restored
