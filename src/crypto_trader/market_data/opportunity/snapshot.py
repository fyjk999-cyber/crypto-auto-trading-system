"""Immutable MarketObservationSnapshot (§6.6) and candidate expiry (§6.7).

One scan == one logical snapshot == one ``scan_id``. A snapshot object is
never mutated into a future market state: the next scan produces a new object
with a new id. Expired snapshots stay historically queryable but MUST NOT be
presented as current opportunities, and a failed scan must never silently
re-freshen an old candidate.

Authority impact: NONE. A snapshot is observation evidence only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from crypto_trader.domain.identifiers import new_id

STATUS_COMPLETE = "COMPLETE"
STATUS_PARTIAL = "PARTIAL"
STATUS_FAILED = "FAILED"

UNIVERSE_TYPE_OKX_USDT_PERP = "OKX Live USDT Perpetual Discovery Universe"
PROVIDER_OKX_PUBLIC = "OKX_PUBLIC"

SCANNER_VERSION = "opportunity-scanner-v2"
DEFAULT_CANDIDATE_TTL_SECONDS = 180.0


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class MarketObservationSnapshot:
    """Immutable factual record of one observation cycle."""

    scan_id: str
    started_at: datetime
    completed_at: datetime
    expires_at: datetime
    status: str
    provider: str = PROVIDER_OKX_PUBLIC
    universe_type: str = UNIVERSE_TYPE_OKX_USDT_PERP
    discovered_count: int = 0
    observable_count: int = 0
    analysis_attempted_count: int = 0
    analysis_success_count: int = 0
    analysis_ready_count: int = 0
    execution_supported_count: int = 0
    broad_market_summary: dict = field(default_factory=dict)
    factor_candidates: tuple = ()
    active_symbols: tuple = ()
    rotation_symbols: tuple = ()
    data_quality_summary: dict = field(default_factory=dict)
    scanner_version: str = SCANNER_VERSION
    error: str | None = None
    # Compact per-symbol broad facts for the whole observable set. Kept out of
    # as_dict() to bound API payloads; used by the research pool builder and the
    # read-only Market Directory. Contents are never mutated after publication.
    observable_rows: tuple = ()

    # ------------------------------------------------------------- lifecycle
    def age_seconds(self, *, now: datetime | None = None) -> float:
        now = now or datetime.now(UTC)
        return (now.astimezone(UTC) - self.completed_at.astimezone(UTC)).total_seconds()

    def is_expired(self, *, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        return now.astimezone(UTC) >= self.expires_at.astimezone(UTC)

    def is_usable(self, *, now: datetime | None = None) -> bool:
        return self.status in {STATUS_COMPLETE, STATUS_PARTIAL} and not self.is_expired(now=now)

    # ---------------------------------------------------------- serialisation
    def as_dict(self) -> dict:
        return {
            "scan_id": self.scan_id,
            "started_at": _iso(self.started_at),
            "completed_at": _iso(self.completed_at),
            "expires_at": _iso(self.expires_at),
            "provider": self.provider,
            "universe_type": self.universe_type,
            "status": self.status,
            "discovered_count": self.discovered_count,
            "observable_count": self.observable_count,
            "analysis_attempted_count": self.analysis_attempted_count,
            "analysis_success_count": self.analysis_success_count,
            "analysis_ready_count": self.analysis_ready_count,
            "execution_supported_count": self.execution_supported_count,
            "broad_market_summary": dict(self.broad_market_summary),
            "factor_candidates": [c.as_dict() for c in self.factor_candidates],
            "active_symbols": list(self.active_symbols),
            "rotation_symbols": list(self.rotation_symbols),
            "data_quality_summary": dict(self.data_quality_summary),
            "scanner_version": self.scanner_version,
            "error": self.error,
            "observable_rows_count": len(self.observable_rows),
        }

    def summary_dict(self) -> dict:
        """Compact view for selection context / API (no candidate bodies)."""
        return {
            "scan_id": self.scan_id,
            "status": self.status,
            "started_at": _iso(self.started_at),
            "completed_at": _iso(self.completed_at),
            "expires_at": _iso(self.expires_at),
            "provider": self.provider,
            "universe_type": self.universe_type,
            "counts": {
                "discovered_count": self.discovered_count,
                "observable_count": self.observable_count,
                "analysis_attempted_count": self.analysis_attempted_count,
                "analysis_success_count": self.analysis_success_count,
                "analysis_ready_count": self.analysis_ready_count,
                "execution_supported_count": self.execution_supported_count,
            },
            "factor_candidate_count": len(self.factor_candidates),
            "data_quality_summary": dict(self.data_quality_summary),
            "scanner_version": self.scanner_version,
        }


def new_scan_id(prefix: str = "scan") -> str:
    return new_id(prefix)


def snapshot_expiry(completed_at: datetime, ttl_seconds: float) -> datetime:
    return completed_at.astimezone(UTC) + timedelta(seconds=max(1.0, float(ttl_seconds)))


class SnapshotExpired(RuntimeError):
    """Raised when autonomous selection/research would use an expired snapshot."""

    def __init__(self, scan_id: str, age_seconds: float | None = None) -> None:
        detail = f"scan_id={scan_id}"
        if age_seconds is not None:
            detail += f" age={age_seconds:.0f}s"
        super().__init__(f"snapshot not usable: {detail}")


def require_usable_snapshot(
    snapshot: MarketObservationSnapshot | None, *, now: datetime | None = None
) -> MarketObservationSnapshot:
    now = now or datetime.now(UTC)
    if snapshot is None:
        raise SnapshotExpired("none")
    if snapshot.status == STATUS_FAILED:
        raise SnapshotExpired(snapshot.scan_id, snapshot.age_seconds(now=now))
    if snapshot.is_expired(now=now):
        raise SnapshotExpired(snapshot.scan_id, snapshot.age_seconds(now=now))
    return snapshot


def aggregate_quality(*states: str) -> str:
    """Worst-case quality for a group of facts (honest roll-up)."""
    from crypto_trader.market_data.quality import (
        MISSING,
        PARTIAL,
        REQUEST_FAILED,
        STALE,
        UNSUPPORTED,
        VALID,
    )

    present = [s for s in states if s]
    if not present:
        return MISSING
    for worst in (REQUEST_FAILED, UNSUPPORTED, STALE, PARTIAL, MISSING):
        if worst in present:
            return worst
    if all(s == VALID for s in present):
        return VALID
    return PARTIAL


def build_data_quality_summary(
    *, funding: dict, oi: dict, candles: dict, total_symbols: int
) -> dict[str, Any]:
    """Bounded factual data-quality roll-up for a scan."""
    return {
        "funding": _counts(funding, total_symbols),
        "open_interest": _counts(oi, total_symbols),
        "candles": _counts(candles, total_symbols),
        "note": (
            "provider failure states are reported as facts; missing funding is "
            "never rendered as zero funding"
        ),
    }


def _counts(states: dict[str, str], total: int) -> dict:
    counts: dict[str, int] = {}
    for state in states.values():
        counts[state] = counts.get(state, 0) + 1
    return {
        "states": counts,
        "observed": len(states),
        "requested": total,
        "unobserved": max(0, total - len(states)),
    }
