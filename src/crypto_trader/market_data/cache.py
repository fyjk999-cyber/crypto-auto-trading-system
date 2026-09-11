"""Canonical shared market-data cache (§10).

Observer, evidence prewarm, factor tools and history tools must not repeatedly
download identical market history. Entries are keyed by factual identity:

    provider + instrument + timeframe + window/limit + closed_only

An entry retains its own provenance:

    source, fetched_at, latest_data_at, quality

Caching is an OPTIMISATION ONLY:

    * an expired entry is never returned as fresh (it is reported as STALE and
      the caller must re-fetch);
    * failed or empty requests are recorded as failures and NEVER stored as
      valid data, so a provider outage cannot poison the cache;
    * ``latest_data_at`` always describes the data itself, not the fetch time.

Authority impact: NONE.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from crypto_trader.market_data.quality import (
    MISSING,
    REQUEST_FAILED,
    VALID,
)

CACHE_PROVIDER_OKX_PUBLIC = "OKX_PUBLIC"


@dataclass(frozen=True, slots=True)
class CacheKey:
    provider: str
    instrument: str
    timeframe: str
    limit: int
    closed_only: bool = True
    # as-of-sensitive history (e.g. ChiefTrader history tool) additionally keys
    # the interval bucket, because "closed candles usable at T" is a function of
    # both the instrument/timeframe AND the decision time.
    as_of_bucket: str | None = None

    def as_tuple(self) -> tuple:
        return (
            self.provider,
            self.instrument,
            self.timeframe,
            int(self.limit),
            bool(self.closed_only),
            self.as_of_bucket,
        )

    def as_ref(self) -> str:
        suffix = f":asof={self.as_of_bucket}" if self.as_of_bucket else ""
        return (
            f"{self.provider}:{self.instrument}:{self.timeframe}:"
            f"{int(self.limit)}:{'closed' if self.closed_only else 'raw'}{suffix}"
        )


@dataclass(frozen=True, slots=True)
class CacheEntry:
    key: CacheKey
    payload: Any
    source: str
    fetched_at: datetime
    latest_data_at: datetime | None
    quality: str
    closed_only: bool = True

    def age_seconds(self, *, now: datetime) -> float:
        return (now.astimezone(UTC) - self.fetched_at.astimezone(UTC)).total_seconds()

    def is_fresh(self, *, now: datetime, ttl_seconds: float) -> bool:
        return self.age_seconds(now=now) <= max(0.0, ttl_seconds)

    def as_dict(self) -> dict:
        return {
            "key": self.key.as_ref(),
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat(),
            "latest_data_at": self.latest_data_at.isoformat() if self.latest_data_at else None,
            "quality": self.quality,
            "closed_only": self.closed_only,
        }


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    stale_hits: int = 0
    stores: int = 0
    rejected_failures: int = 0
    evictions: int = 0

    def as_dict(self) -> dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "stale_hits": self.stale_hits,
            "stores": self.stores,
            "rejected_failures": self.rejected_failures,
            "evictions": self.evictions,
        }


class MarketDataCache:
    """Thread-safe bounded cache with honest freshness semantics."""

    def __init__(self, *, max_entries: int = 512, clock=None) -> None:
        self.max_entries = max(1, int(max_entries))
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._entries: dict[tuple, tuple[CacheEntry, float]] = {}
        self.stats = CacheStats()

    # ------------------------------------------------------------------- read
    def get(
        self, key: CacheKey, *, ttl_seconds: float, now: datetime | None = None
    ) -> CacheEntry | None:
        """Return a FRESH entry, else ``None``.

        A stale entry is counted (``stale_hits``) and removed, so it can never be
        served as current market state.
        """
        now = now or datetime.now(UTC)
        with self._lock:
            stored = self._entries.get(key.as_tuple())
            if stored is None:
                self.stats.misses += 1
                return None
            entry, stored_mono = stored
            age = self._clock() - stored_mono
            if age > max(0.0, ttl_seconds):
                self._entries.pop(key.as_tuple(), None)
                self.stats.stale_hits += 1
                return None
            self.stats.hits += 1
            return entry

    def peek(self, key: CacheKey) -> CacheEntry | None:
        with self._lock:
            stored = self._entries.get(key.as_tuple())
            return stored[0] if stored else None

    # ------------------------------------------------------------------ write
    def put(
        self,
        key: CacheKey,
        payload: Any,
        *,
        source: str,
        latest_data_at: datetime | None = None,
        quality: str = VALID,
        now: datetime | None = None,
    ) -> bool:
        """Store a usable fact. Failures/empties are refused (never poison)."""
        now = now or datetime.now(UTC)
        if quality in (REQUEST_FAILED, MISSING) or payload in (None, [], {}, ()):
            with self._lock:
                self.stats.rejected_failures += 1
            return False
        entry = CacheEntry(
            key=key,
            payload=payload,
            source=source,
            fetched_at=now,
            latest_data_at=latest_data_at,
            quality=quality,
            closed_only=key.closed_only,
        )
        with self._lock:
            self._entries[key.as_tuple()] = (entry, self._clock())
            self.stats.stores += 1
            while len(self._entries) > self.max_entries:
                self._entries.pop(next(iter(self._entries)), None)
                self.stats.evictions += 1
        return True

    def record_failure(self, key: CacheKey, reason: str) -> None:
        """Explicitly refuse to cache a failure, keeping the reason observable."""
        with self._lock:
            self._entries.pop(key.as_tuple(), None)
            self.stats.rejected_failures += 1

    def invalidate(self, key: CacheKey) -> None:
        with self._lock:
            self._entries.pop(key.as_tuple(), None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    # -------------------------------------------------- fetch-through helper
    async def get_or_fetch(
        self,
        key: CacheKey,
        loader: Callable[[], Awaitable[Any]],
        *,
        ttl_seconds: float,
        source: str,
        latest_data_at_of: Callable[[Any], datetime | None] | None = None,
        is_usable: Callable[[Any], bool] | None = None,
    ) -> tuple[Any | None, str, bool]:
        """Return ``(payload, quality, cache_hit)``.

        ``quality`` is ``VALID`` on a fresh hit/fetch, ``REQUEST_FAILED`` when the
        loader raised, and ``MISSING`` when the loader produced nothing usable.
        """
        entry = self.get(key, ttl_seconds=ttl_seconds)
        if entry is not None:
            return entry.payload, entry.quality, True
        try:
            payload = await loader()
        except Exception:
            self.record_failure(key, "loader raised")
            return None, REQUEST_FAILED, False
        usable = is_usable(payload) if is_usable is not None else bool(payload)
        if not usable:
            self.record_failure(key, "loader produced no usable data")
            return None, MISSING, False
        latest = latest_data_at_of(payload) if latest_data_at_of else None
        self.put(
            key,
            payload,
            source=source,
            latest_data_at=latest,
            quality=VALID,
        )
        return payload, VALID, False

    # ---------------------------------------------------------- observability
    def snapshot(self) -> dict:
        with self._lock:
            entries = [entry.as_dict() for entry, _ in self._entries.values()]
        return {
            "entries": len(entries),
            "max_entries": self.max_entries,
            "stats": self.stats.as_dict(),
            "sample": entries[:5],
            "semantics": {
                "stale_is_never_fresh": True,
                "failures_are_not_cached": True,
                "key": "provider+instrument+timeframe+limit+closed_only",
            },
        }


_SHARED: MarketDataCache | None = None
_SHARED_LOCK = threading.Lock()


def get_shared_market_data_cache() -> MarketDataCache:
    """Process-wide canonical cache shared by observer and evidence tools."""
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None:
            _SHARED = MarketDataCache()
        return _SHARED


def reset_shared_market_data_cache() -> None:
    """Test hook: replace the shared cache with a clean instance."""
    global _SHARED
    with _SHARED_LOCK:
        _SHARED = MarketDataCache()


def candle_cache_key(
    *, instrument: str, timeframe: str, limit: int, as_of_bucket: str | None = None
) -> CacheKey:
    return CacheKey(
        provider=CACHE_PROVIDER_OKX_PUBLIC,
        instrument=str(instrument),
        timeframe=str(timeframe),
        limit=int(limit),
        closed_only=True,
        as_of_bucket=as_of_bucket,
    )


def as_of_bucket(as_of: datetime, interval_seconds: float) -> str:
    """Floor an as-of time to its interval bucket (closed-candle identity)."""
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    epoch = int(as_of.astimezone(UTC).timestamp())
    interval = max(1, int(interval_seconds))
    return str(epoch - (epoch % interval))


def closed_candle_ttl_seconds(bar_seconds: float) -> float:
    """Closed history is immutable; a short TTL avoids refetching the same facts."""
    return max(5.0, min(30.0, float(bar_seconds) / 4.0))
