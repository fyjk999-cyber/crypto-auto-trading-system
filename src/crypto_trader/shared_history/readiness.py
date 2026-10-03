"""Pure post-migration contract evaluation; never deploys or qualifies a runtime."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

FRESHNESS_THRESHOLD_SECONDS = 300


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
    required = ("resource_state", "writer_count", "service_status", "incremental_updater")
    if any(key not in health for key in required):
        return HistoryReadiness("NOT_VERIFIED", "CURRENT_HEALTH_EVIDENCE_MISSING", count)
    generated = health.get("health_snapshot_generated_at")
    observed = time.time() * 1000 if now_ms is None else now_ms
    if (
        isinstance(generated, bool)
        or not isinstance(generated, (int, float))
        or not math.isfinite(generated)
        or not math.isfinite(observed)
        or not 0 <= observed - generated <= 60_000
    ):
        return HistoryReadiness("NOT_VERIFIED", "CURRENT_HEALTH_TIMESTAMP_MISSING_OR_STALE", count)
    if health["resource_state"] != "NORMAL":
        return HistoryReadiness("HISTORICAL_DATA_UNAVAILABLE", "RESOURCE_NOT_NORMAL", count)
    if (
        health["writer_count"] != 1
        or isinstance(health["writer_count"], bool)
        or health["service_status"] != "OK"
        or health["incremental_updater"] != "ACTIVE"
        or health.get("health_snapshot_stale") is not False
    ):
        return HistoryReadiness("HISTORICAL_DATA_UNAVAILABLE", "SERVICE_NOT_READY", count)
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
