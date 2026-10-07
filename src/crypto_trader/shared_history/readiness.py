"""Pure post-migration contract evaluation; never deploys or qualifies a runtime."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

FRESHNESS_THRESHOLD_SECONDS = 300


def _timestamp(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value >= 0
    )


def operational_health_failure(
    health: dict[str, Any], *, now_ms: float | None = None
) -> str | None:
    """Single operational safety predicate shared by readiness and runtime.

    Market freshness is independent: callers still must validate their factual
    market evidence. Legacy heavy snapshot age is NOT the operational clock.
    """
    observed = time.time() * 1000 if now_ms is None else now_ms
    envelope = health.get("operational_health")
    if not isinstance(envelope, dict):
        return "CURRENT_HEALTH_EVIDENCE_MISSING"
    if type(envelope.get("schema_version")) is not int or envelope["schema_version"] != 1:
        return "OPERATIONAL_SCHEMA_UNSUPPORTED"
    if type(envelope.get("generation")) is not int or envelope["generation"] < 1:
        return "OPERATIONAL_GENERATION_INVALID"
    published = envelope.get("published_at_ms")
    if (
        not _timestamp(observed)
        or not _timestamp(published)
        or not 0 <= observed - published <= 60000
    ):
        return "OPERATIONAL_PUBLICATION_STALE_OR_INVALID"
    for component in ("resource", "scheduler"):
        fact = envelope.get(component)
        if not isinstance(fact, dict):
            return "CURRENT_HEALTH_EVIDENCE_MISSING"
        timestamp = fact.get("collected_at_ms")
        if (
            not _timestamp(timestamp)
            or not 0 <= observed - timestamp <= 60000
            or timestamp > published
            or fact.get("error") is not None
        ):
            return "CURRENT_HEALTH_TIMESTAMP_MISSING_OR_STALE"
    if envelope["resource"].get("state") != "NORMAL":
        return "RESOURCE_NOT_NORMAL"
    if envelope["scheduler"].get("running") is not True:
        return "SCHEDULER_NOT_RUNNING"
    incremental = envelope.get("incremental")
    if not isinstance(incremental, dict) or incremental.get("last_outcome") != "PASS":
        return "INCREMENTAL_NOT_PASS"
    completed = incremental.get("completed_at_ms")
    if not _timestamp(completed) or completed > published:
        return "INCREMENTAL_TIMESTAMP_INVALID"
    active_keys = {
        "current_active", "current_cycle_id", "current_started_at_ms",
        "current_age_seconds", "current_stale", "current_stale_limit_seconds",
    }
    if (
        not active_keys <= incremental.keys()
        or type(incremental["current_active"]) is not bool
        or type(incremental["current_stale"]) is not bool
        or type(incremental["current_stale_limit_seconds"]) is not int
        or incremental["current_stale_limit_seconds"] != 300
    ):
        return "ACTIVE_INCREMENTAL_STATE_UNAVAILABLE"
    started = incremental["current_started_at_ms"]
    age = incremental["current_age_seconds"]
    cycle_id = incremental["current_cycle_id"]
    if incremental["current_active"]:
        if (
            not isinstance(cycle_id, str) or not cycle_id.strip()
            or not _timestamp(started) or started > published
            or not _timestamp(age)
        ):
            return "ACTIVE_INCREMENTAL_STATE_UNAVAILABLE"
        # Independent wall age plus producer monotonic stale evidence: neither
        # snapshot delay nor a backward wall-clock jump can revive stale work.
        if observed - started > 300000 or age > 300 or incremental["current_stale"]:
            return "ACTIVE_INCREMENTAL_CYCLE_STALE"
    elif (
        cycle_id is not None or started is not None or age is not None
        or incremental["current_stale"]
    ):
        return "ACTIVE_INCREMENTAL_STATE_UNAVAILABLE"
    if (
        type(health.get("writer_count")) is not int
        or health["writer_count"] != 1
        or health.get("service_status") != "OK"
        or health.get("health_snapshot_stale") is not False
    ):
        return "SERVICE_NOT_READY"
    return None


@dataclass(frozen=True)
class HistoryReadiness:
    status: str
    reason: str
    eligible_universe: int
    outside_300s: int | None = None
    max_1m_freshness: float | None = None


def evaluate_history_readiness(
    health: dict[str, Any],
    eligible_symbols: list[str],
    freshness_by_symbol: dict[str, float | None],
    *,
    now_ms: float | None = None,
) -> HistoryReadiness:
    """Require explicit, full-universe evidence; absent fields never imply PASS.

    Inputs are current GET response facts, not acceptance flags or old receipts.
    This prepares a contract for a separately authorized activation controller.
    """
    if any(not isinstance(symbol, str) or not symbol.strip() for symbol in eligible_symbols):
        return HistoryReadiness("NOT_VERIFIED", "INVALID_UNIVERSE", 0)
    symbols = set(eligible_symbols)
    count = len(symbols)
    if not count or count != len(eligible_symbols) or any(not s for s in symbols):
        return HistoryReadiness("NOT_VERIFIED", "EMPTY_OR_INVALID_UNIVERSE", count)
    if set(freshness_by_symbol) != symbols:
        return HistoryReadiness("NOT_VERIFIED", "UNIVERSE_COVERAGE_MISMATCH", count)
    failure = operational_health_failure(health, now_ms=now_ms)
    if failure:
        return HistoryReadiness("HISTORICAL_DATA_UNAVAILABLE", failure, count)
    values = list(freshness_by_symbol.values())
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        for value in values
    ):
        return HistoryReadiness("NOT_VERIFIED", "FRESHNESS_EVIDENCE_INVALID", count)
    outside = sum(value > FRESHNESS_THRESHOLD_SECONDS for value in values)
    maximum = float(max(values))
    return HistoryReadiness(
        "STALE" if outside else "PASS",
        "FRESHNESS_EXCEEDS_300S" if outside else "CURRENT_FULL_UNIVERSE_VERIFIED",
        count,
        outside,
        maximum,
    )
