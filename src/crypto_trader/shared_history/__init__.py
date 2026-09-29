"""LowRisk read-only integration with Shared Market History.

Shared Market History is the single shared factual historical market data source.
LowRisk consumes it as EVIDENCE ONLY.

Authority boundary (unchanged by this package):
  * Shared History provides DATA ONLY. It has no direction, risk, position, sizing,
    leverage, order or exit authority.
  * DeepSeek Chief remains LowRisk's directional authority.
  * Risk remains LowRisk's hard safety authority.
  * Execution keeps its existing PAPER authority.

This package can read and nothing else. It contains no writer, no admin path, no
Parquet or DuckDB access, and no checkpoint, backfill, retention or compaction logic.
"""

from __future__ import annotations

from crypto_trader.shared_history.adapter import (
    COMPLETE,
    DATA_UNAVAILABLE,
    PARTIAL_HISTORY,
    STALE,
    HistoricalEvidence,
    SharedHistoryEvidence,
)
from crypto_trader.shared_history.client import (
    DEFAULT_API_URL,
    LowRiskSharedHistoryClient,
    SharedHistoryClient,
    SharedHistoryClientError,
    is_loopback_url,
)

__all__ = [
    "COMPLETE",
    "DATA_UNAVAILABLE",
    "DEFAULT_API_URL",
    "HistoricalEvidence",
    "LowRiskSharedHistoryClient",
    "PARTIAL_HISTORY",
    "STALE",
    "SharedHistoryClient",
    "SharedHistoryClientError",
    "SharedHistoryEvidence",
    "is_loopback_url",
    "shared_history_from_settings",
]


def shared_history_from_settings(settings=None) -> SharedHistoryEvidence:
    """Build the evidence adapter from LowRisk Settings.

    Reuses the existing LowRisk configuration mechanism rather than introducing a
    second flag. When ``shared_history_enabled`` is false (the production default)
    the adapter performs no I/O.
    """
    if settings is None:
        from crypto_trader.config import get_settings

        settings = get_settings()
    return SharedHistoryEvidence(
        enabled=bool(getattr(settings, "shared_history_enabled", False)),
        base_url=getattr(settings, "shared_history_base_url", DEFAULT_API_URL),
        timeout=float(getattr(settings, "shared_history_timeout_seconds", 20.0)),
        cache_ttl_seconds=float(getattr(settings, "shared_history_cache_ttl_seconds", 60.0)),
        cache_max_entries=int(getattr(settings, "shared_history_cache_max_entries", 256)),
    )
