"""LowRisk read-only evidence adapter over the Shared Market History API.

This is the minimum integration seam. It is EVIDENCE ONLY: it hands historical
market facts to LowRisk layers that already consume historical context, and it can
never create or mutate anything.

Guarantees enforced here (not merely documented):

* GET-only transport, loopback-only target (enforced in the client).
* Disabled by default: when ``shared_history_enabled`` is false the adapter performs
  no I/O and reports DATA_UNAVAILABLE. The untouched production runtime stays off.
* ``UNAVAILABLE != ZERO``: an unavailable read returns no rows and
  ``available = False``. It never zero-fills, never invents bars, never falls back to
  synthetic data.
* ``STALE != FRESH``: cached data is only served with an explicit STALE status.
* ``PARTIAL_HISTORY != COMPLETE``: the service-provided coverage state is preserved.
* Temporal integrity: for a decision at ``decision_as_of`` no row with a timestamp
  after that instant is ever returned, and an offending payload is rejected whole.
* Provenance: source, symbol, timeframe, first/last timestamp, row count, coverage,
  freshness, schema version and read time are retained on every result.
* Bounded reads: row limits and time ranges are bounded, and the cache has an explicit
  TTL and entry bound. Full history is never materialised into LowRisk.
"""

from __future__ import annotations

import time
import urllib.parse
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from crypto_trader.shared_history.client import (
    DEFAULT_API_URL,
    LowRiskSharedHistoryClient,
    SharedHistoryClientError,
)

# Quality states. These are preserved, never rewritten into a friendlier value.
COMPLETE = "COMPLETE"
PARTIAL_HISTORY = "PARTIAL_HISTORY"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
STALE = "STALE"

# Explicit reason codes for unavailability, so a caller can never mistake an outage
# for a genuine zero or an empty market.
REASON_DISABLED = "SHARED_HISTORY_DISABLED"
REASON_UNREACHABLE = "SHARED_HISTORY_UNREACHABLE"
REASON_HTTP_ERROR = "SHARED_HISTORY_HTTP_ERROR"
REASON_MALFORMED = "SHARED_HISTORY_MALFORMED_PAYLOAD"
REASON_FUTURE_DATA = "FUTURE_DATA_LEAKAGE_REJECTED"
REASON_EMPTY = "NO_ROWS_FOR_REQUEST"

# Per-dataset timestamp column, mirroring the service envelope.
_TIME_COLUMNS = {
    "candles": ("open_time", "close_time"),
    "funding": ("funding_time",),
    "open_interest": ("ts",),
}

# Reads that describe the service or a single document rather than a row series.
# A successful read of one of these is availability; an empty row set is expected.
DOCUMENT_DATASETS = frozenset({"health", "universe", "metadata", "regime"})

# Envelope-level ``schema_version`` is the API contract version. Provenance must name
# the DATA schema, so a dataset-specific field wins where the service provides one.
_DATASET_SCHEMA_KEYS = {
    "regime": "regime_schema_version",
    "analogs": "analog_schema_version",
    "features": "feature_set_version",
}

_MAX_LIMIT = 10_000


@dataclass(frozen=True)
class HistoricalEvidence:
    """A bounded, attributed view of historical market fact.

    ``available`` is False whenever the underlying read did not succeed. An
    unavailable result carries no rows: nothing is zero-filled.
    """

    available: bool
    status: str
    dataset: str
    symbol: str
    timeframe: str | None
    rows: tuple[dict[str, Any], ...] = ()
    first_timestamp: int | None = None
    last_timestamp: int | None = None
    row_count: int = 0
    coverage: str = DATA_UNAVAILABLE
    freshness: dict[str, Any] | None = None
    source: str | None = None
    schema_version: str | None = None
    read_at: int = 0
    requested_as_of: int | None = None
    cached: bool = False
    reason: str | None = None
    detail: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        return self.status == COMPLETE

    @property
    def is_partial(self) -> bool:
        return self.status == PARTIAL_HISTORY

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "status": self.status,
            "dataset": self.dataset,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "row_count": self.row_count,
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "coverage": self.coverage,
            "freshness": self.freshness,
            "source": self.source,
            "schema_version": self.schema_version,
            "read_at": self.read_at,
            "requested_as_of": self.requested_as_of,
            "cached": self.cached,
            "reason": self.reason,
            "detail": self.detail,
            "extra": self.extra,
        }


@dataclass
class _CacheEntry:
    evidence: HistoricalEvidence
    stored_at: float


class SharedHistoryEvidence:
    """Bounded, fail-closed, read-only evidence accessor for LowRisk."""

    def __init__(
        self,
        enabled: bool = False,
        base_url: str = DEFAULT_API_URL,
        timeout: float = 20.0,
        cache_ttl_seconds: float = 60.0,
        cache_max_entries: int = 256,
        client: LowRiskSharedHistoryClient | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.cache_ttl_seconds = float(cache_ttl_seconds)
        self.cache_max_entries = int(cache_max_entries)
        self._client = client
        self._base_url = base_url
        self._timeout = float(timeout)
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        # Observability counters. These are evidence about access, not market facts.
        self.read_count = 0
        self.cache_hit_count = 0
        self.cache_eviction_count = 0
        self.unavailable_count = 0
        self.future_data_rejections = 0
        self._health_blocked = False

    # ------------------------------------------------------------------
    # Client lifecycle
    # ------------------------------------------------------------------
    @property
    def client(self) -> LowRiskSharedHistoryClient:
        if self._client is None:
            self._client = LowRiskSharedHistoryClient(self._base_url, timeout=self._timeout)
        return self._client

    def _disabled(self, dataset: str, symbol: str, timeframe: str | None) -> HistoricalEvidence:
        return HistoricalEvidence(
            available=False,
            status=DATA_UNAVAILABLE,
            dataset=dataset,
            symbol=symbol,
            timeframe=timeframe,
            reason=REASON_DISABLED,
            detail="LOWRISK_SHARED_HISTORY_ENABLED is false",
            read_at=_now_ms(),
        )

    # ------------------------------------------------------------------
    # Read contract
    # ------------------------------------------------------------------
    def health(self) -> HistoricalEvidence:
        return self._read("health", "", None, lambda: self.client.health())

    def universe(self) -> HistoricalEvidence:
        return self._read("universe", "", None, lambda: self.client.universe())

    def metadata(self, symbol: str) -> HistoricalEvidence:
        symbol = _norm(symbol)
        return self._read("metadata", symbol, None, lambda: self.client.metadata(symbol))

    def latest_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 300,
        decision_as_of: int | None = None,
    ) -> HistoricalEvidence:
        symbol = _norm(symbol)
        limit = _bound(limit)
        return self._read(
            "candles",
            symbol,
            timeframe,
            lambda: self.client.latest_candles(
                symbol, timeframe, limit=limit, as_of=decision_as_of
            ),
            decision_as_of=decision_as_of,
            limit=limit,
        )

    def historical_candles(
        self,
        symbol: str,
        timeframe: str,
        start: int | None = None,
        end: int | None = None,
        limit: int = 1_000,
        decision_as_of: int | None = None,
    ) -> HistoricalEvidence:
        symbol = _norm(symbol)
        limit = _bound(limit)
        end = _clamp_end(end, decision_as_of)
        return self._read(
            "candles",
            symbol,
            timeframe,
            lambda: self.client.historical_candles(
                symbol,
                timeframe,
                start=start,
                end=end,
                limit=limit,
                as_of=decision_as_of,
            ),
            decision_as_of=decision_as_of,
            limit=limit,
            window=(start, end),
        )

    def features(
        self, symbol: str, decision_as_of: int | None = None, feature_set_version: str | None = None
    ) -> HistoricalEvidence:
        symbol = _norm(symbol)
        return self._read(
            "features",
            symbol,
            None,
            lambda: self.client.features(
                symbol, as_of=decision_as_of, feature_set_version=feature_set_version
            ),
            decision_as_of=decision_as_of,
            requested_version=feature_set_version,
        )

    def regime(self, symbol: str, decision_as_of: int | None = None) -> HistoricalEvidence:
        symbol = _norm(symbol)
        return self._read(
            "regime",
            symbol,
            None,
            lambda: self.client.regime(symbol, as_of=decision_as_of),
            decision_as_of=decision_as_of,
        )

    def funding(
        self, symbol: str, limit: int = 100, decision_as_of: int | None = None
    ) -> HistoricalEvidence:
        symbol = _norm(symbol)
        limit = _bound(limit)
        return self._read(
            "funding",
            symbol,
            None,
            lambda: self.client.funding(symbol, limit=limit, as_of=decision_as_of),
            decision_as_of=decision_as_of,
            limit=limit,
        )

    def open_interest(
        self, symbol: str, limit: int = 100, decision_as_of: int | None = None
    ) -> HistoricalEvidence:
        symbol = _norm(symbol)
        limit = _bound(limit)
        return self._read(
            "open_interest",
            symbol,
            None,
            lambda: self.client.open_interest(symbol, limit=limit, as_of=decision_as_of),
            decision_as_of=decision_as_of,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Central bounded read
    # ------------------------------------------------------------------
    def _read(
        self,
        dataset: str,
        symbol: str,
        timeframe: str | None,
        fetch,
        decision_as_of: int | None = None,
        limit: int | None = None,
        window: tuple[int | None, int | None] | None = None,
        allow_stale: bool = False,
        requested_version: str | None = None,
    ) -> HistoricalEvidence:
        symbol = _norm(symbol)
        if not self.enabled:
            self.unavailable_count += 1
            return self._disabled(dataset, symbol, timeframe)

        if dataset != "health" and self._health_blocked:
            return HistoricalEvidence(
                available=False, status=DATA_UNAVAILABLE, dataset=dataset,
                symbol=symbol, timeframe=timeframe, read_at=_now_ms(),
                reason="HISTORICAL_DATA_UNAVAILABLE",
            )

        key = (*_cache_key(dataset, symbol, timeframe, decision_as_of, limit, window),
               requested_version)
        entry = self._cache.get(key)
        if dataset != "health" and entry is not None and (
            time.monotonic() - entry.stored_at
        ) < self.cache_ttl_seconds:
            self.cache_hit_count += 1
            self._cache.move_to_end(key)
            return _with_cached(entry.evidence, True)

        self.read_count += 1
        try:
            payload = fetch()
        except SharedHistoryClientError as exc:
            self.unavailable_count += 1
            if allow_stale and entry is not None:
                return _with_cached(entry.evidence, True, status=STALE, reason=REASON_UNREACHABLE)
            return HistoricalEvidence(
                available=False,
                status=DATA_UNAVAILABLE,
                dataset=dataset,
                symbol=symbol,
                timeframe=timeframe,
                reason=_reason_for(exc),
                detail=str(exc)[:300],
                requested_as_of=decision_as_of,
                read_at=_now_ms(),
            )
        except Exception as exc:  # pragma: no cover - defensive, fail closed
            self.unavailable_count += 1
            return HistoricalEvidence(
                available=False,
                status=DATA_UNAVAILABLE,
                dataset=dataset,
                symbol=symbol,
                timeframe=timeframe,
                reason=REASON_HTTP_ERROR,
                detail=type(exc).__name__,
                requested_as_of=decision_as_of,
                read_at=_now_ms(),
            )

        evidence = self._normalize(dataset, symbol, timeframe, payload, decision_as_of)
        if requested_version is not None and evidence.schema_version != requested_version:
            return HistoricalEvidence(
                available=False, status=DATA_UNAVAILABLE, dataset=dataset,
                symbol=symbol, timeframe=timeframe, read_at=_now_ms(),
                reason="FEATURE_VERSION_MISMATCH", requested_as_of=decision_as_of,
            )
        if dataset == "health":
            self._health_blocked = not evidence.available
            if self._health_blocked:
                self._cache.clear()
        if evidence.available:
            self._store(key, evidence)
        return evidence

    # ------------------------------------------------------------------
    # Normalisation, provenance, temporal integrity
    # ------------------------------------------------------------------
    def _normalize(
        self,
        dataset: str,
        symbol: str,
        timeframe: str | None,
        payload: dict[str, Any],
        decision_as_of: int | None,
    ) -> HistoricalEvidence:
        read_at = _now_ms()
        service_state = str(payload.get("service_status") or "").upper()
        resource_state = str(payload.get("resource_state") or "").upper()
        if (
            service_state in {"PAUSED_RESOURCE_CRITICAL", "STALE", "UNAVAILABLE"}
            or resource_state in {"PAUSED_RESOURCE_CRITICAL", "CRITICAL"}
            or payload.get("health_snapshot_stale") is True
        ):
            return HistoricalEvidence(
                available=False, status=DATA_UNAVAILABLE, dataset=dataset,
                symbol=symbol, timeframe=timeframe, read_at=read_at,
                reason="HISTORICAL_DATA_UNAVAILABLE",
                requested_as_of=decision_as_of, extra=_envelope_extra(dataset, payload),
            )
        rows = _rows_of(dataset, payload)
        coverage = str(payload.get("coverage") or payload.get("historical_coverage") or "").upper()
        source = payload.get("source")
        schema_key = _DATASET_SCHEMA_KEYS.get(dataset)
        schema_version = (payload.get(schema_key) if schema_key else None) or payload.get(
            "schema_version"
        )

        timestamps = [ts for ts in (_row_ts(dataset, row) for row in rows) if ts is not None]
        first_ts = min(timestamps) if timestamps else _opt_int(payload.get("first_timestamp"))
        # The envelope's own maximum source timestamp is authoritative for documents
        # such as regime, whose payload carries no per-row timestamp column.
        last_ts = (
            max(timestamps)
            if timestamps
            else _opt_int(
                payload.get("max_source_timestamp")
                or payload.get("last_timestamp")
                or payload.get("as_of")
            )
        )

        # Temporal integrity: reject the WHOLE payload if it contains a fact that
        # postdates the decision instant. This covers row timestamps and the envelope
        # timestamp alike. Never silently trim into a plausible answer.
        if decision_as_of is not None and last_ts is not None:
            if int(last_ts) > int(decision_as_of):
                self.future_data_rejections += 1
                return HistoricalEvidence(
                    available=False,
                    status=DATA_UNAVAILABLE,
                    dataset=dataset,
                    symbol=symbol,
                    timeframe=timeframe,
                    reason=REASON_FUTURE_DATA,
                    detail=(
                        "max source timestamp "
                        + str(int(last_ts))
                        + " exceeds decision_as_of "
                        + str(int(decision_as_of))
                    ),
                    requested_as_of=decision_as_of,
                    read_at=read_at,
                )

        if rows:
            if coverage:
                status = _status_from_coverage(coverage)
            elif dataset in DOCUMENT_DATASETS:
                # A listing such as the universe is not a market-data completeness
                # claim, so an absent coverage field must not read as PARTIAL_HISTORY.
                status = COMPLETE
            else:
                # Conservative default for a market series that states no coverage.
                status = PARTIAL_HISTORY
            available = status != DATA_UNAVAILABLE
            reason = None
            if not available:
                rows = []
                reason = "HISTORICAL_DATA_UNAVAILABLE"
        elif dataset in DOCUMENT_DATASETS:
            # A service/document read: a successful read is the availability signal.
            # There are no market rows to fill, so nothing can be fabricated here.
            status = _status_from_coverage(coverage) if coverage else COMPLETE
            available = True
            reason = None
        else:
            status = DATA_UNAVAILABLE
            available = False
            reason = REASON_EMPTY

        row_count = len(rows) if rows else (_opt_int(payload.get("row_count")) or 0)

        return HistoricalEvidence(
            available=available,
            status=status,
            dataset=dataset,
            symbol=symbol,
            timeframe=timeframe,
            rows=tuple(rows),
            first_timestamp=int(first_ts) if first_ts is not None else None,
            last_timestamp=int(last_ts) if last_ts is not None else None,
            row_count=row_count,
            coverage=status,
            freshness=_freshness_of(payload),
            source=str(source) if source is not None else None,
            schema_version=str(schema_version) if schema_version is not None else None,
            read_at=read_at,
            requested_as_of=decision_as_of,
            cached=False,
            reason=reason,
            extra=_envelope_extra(dataset, payload),
        )

    # ------------------------------------------------------------------
    # Bounded cache
    # ------------------------------------------------------------------
    def _store(self, key: str, evidence: HistoricalEvidence) -> None:
        self._cache[key] = _CacheEntry(evidence=evidence, stored_at=time.monotonic())
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_max_entries:
            self._cache.popitem(last=False)
            self.cache_eviction_count += 1

    def cache_clear(self) -> None:
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def counters(self) -> dict[str, int]:
        return {
            "read_count": self.read_count,
            "cache_hit_count": self.cache_hit_count,
            "cache_eviction_count": self.cache_eviction_count,
            "unavailable_count": self.unavailable_count,
            "future_data_rejections": self.future_data_rejections,
            "cache_size": self.cache_size,
        }


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _now_ms() -> int:
    return int(time.time() * 1000)


def _norm(symbol: str) -> str:
    """One definition of a normalised symbol, shared by key, query and provenance."""
    return (symbol or "").strip().upper()


def _bound(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return 1
    return max(1, min(value, _MAX_LIMIT))


def _clamp_end(end: int | None, decision_as_of: int | None) -> int | None:
    """Client-side as-of clamp: never ask for anything after the decision instant."""
    if decision_as_of is None:
        return end
    if end is None:
        return int(decision_as_of)
    return min(int(end), int(decision_as_of))


def _reason_for(exc: Exception) -> str:
    text = str(exc)
    if "unreachable" in text:
        return REASON_UNREACHABLE
    if "invalid JSON" in text or "non-object" in text:
        return REASON_MALFORMED
    return REASON_HTTP_ERROR


def _status_from_coverage(coverage: str) -> str:
    if coverage in {COMPLETE, PARTIAL_HISTORY}:
        return coverage
    if coverage == DATA_UNAVAILABLE:
        return DATA_UNAVAILABLE
    if coverage == STALE:
        return STALE
    # Unknown or absent coverage is treated conservatively as partial, never COMPLETE.
    return PARTIAL_HISTORY


def _rows_of(dataset: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        # Some endpoints (regime) return a single document rather than a series.
        return [data]
    if dataset == "universe":
        symbols = payload.get("symbols")
        if isinstance(symbols, list):
            return [row for row in symbols if isinstance(row, dict)]
    return []


def _row_ts(dataset: str, row: dict[str, Any]) -> int | None:
    for column in _TIME_COLUMNS.get(dataset, ("open_time",)):
        value = row.get(column)
        if isinstance(value, (int, float)):
            return int(value)
    return None


# Surfaced from /v1/health for observability. Note what is deliberately absent:
# data_root, storage paths and any writer/admin handle. The consumer never learns
# storage internals.
_HEALTH_EXTRA_KEYS = (
    "resource_state",
    "health_snapshot_generated_at",
    "service_status",
    "parquet_status",
    "implementation_sha",
    "writer_count",
    "external_writer_active",
    "universe_size",
    "symbols_with_history",
    "universe_processed_count",
    "unresolved_symbol_count",
    "symbols_terminal_complete",
    "symbols_terminal_partial",
    "symbols_terminal_data_unavailable",
    "pending_backfill_tasks",
    "full_market",
    "full_market_backfill_complete",
    "health_snapshot_stale",
    "maintenance_phase",
    "incremental_updater",
    "latest_1m_freshness_seconds",
    "soak",
    "llm_contract",
    "historical_schema_version",
    "feature_set_version",
    "regime_schema_version",
    "analog_schema_version",
    "context_schema_version",
)


def _envelope_extra(dataset: str, payload: dict[str, Any]) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if dataset == "universe":
        for key in ("count", "live_usdt_swap_count", "as_of"):
            if key in payload:
                extra[key] = payload[key]
    if dataset == "health":
        for key in _HEALTH_EXTRA_KEYS:
            if key in payload:
                extra[key] = payload[key]
    if dataset == "regime":
        for key in ("row_count", "requested_as_of", "regime_schema_version", "freshness"):
            if key in payload:
                extra[key] = payload[key]
    # Preserve the remaining version axes so nothing is silently dropped.
    if "schema_version" in payload:
        extra["api_schema_version"] = payload["schema_version"]
    if "historical_schema_version" in payload:
        extra["historical_schema_version"] = payload["historical_schema_version"]
    for key in ("contract", "contract_version", "implementation_version"):
        if key in payload:
            extra[key] = payload[key]
    return extra


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _freshness_of(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Freshness is a dict on some endpoints and a bare status string on others."""
    freshness = payload.get("freshness")
    if isinstance(freshness, dict):
        return freshness
    if isinstance(freshness, str) and freshness:
        return {"status": freshness}
    data_freshness = payload.get("data_freshness")
    if isinstance(data_freshness, dict):
        return data_freshness
    return None


def _opt_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _with_cached(
    evidence: HistoricalEvidence,
    cached: bool,
    status: str | None = None,
    reason: str | None = None,
) -> HistoricalEvidence:
    return HistoricalEvidence(
        available=evidence.available,
        status=status or evidence.status,
        dataset=evidence.dataset,
        symbol=evidence.symbol,
        timeframe=evidence.timeframe,
        rows=evidence.rows,
        first_timestamp=evidence.first_timestamp,
        last_timestamp=evidence.last_timestamp,
        row_count=evidence.row_count,
        coverage=status or evidence.coverage,
        freshness=evidence.freshness,
        source=evidence.source,
        schema_version=evidence.schema_version,
        read_at=evidence.read_at,
        requested_as_of=evidence.requested_as_of,
        cached=cached,
        reason=reason or evidence.reason,
        detail=evidence.detail,
        extra=evidence.extra,
    )


def _cache_key(
    dataset: str,
    symbol: str,
    timeframe: str | None,
    decision_as_of: int | None,
    limit: int | None,
    window: tuple[int | None, int | None] | None,
) -> str:
    start, end = window if window else (None, None)
    return "|".join(
        [
            dataset,
            symbol,
            str(timeframe or ""),
            str(decision_as_of if decision_as_of is not None else ""),
            str(limit if limit is not None else ""),
            str(start if start is not None else ""),
            str(end if end is not None else ""),
        ]
    )


def quote_symbol(symbol: str) -> str:
    """Exposed for callers that need the same encoding the client applies."""
    return urllib.parse.quote((symbol or "").strip().upper())


__all__ = [
    "COMPLETE",
    "DATA_UNAVAILABLE",
    "PARTIAL_HISTORY",
    "STALE",
    "HistoricalEvidence",
    "SharedHistoryEvidence",
]
