"""Label-v2 exact factual outcome engine (LEARNING_ONLY).

For every scanner snapshot at T0 and horizon H the maturer reconstructs the
factual OKX path that ended at exactly T0+H, using only closed candles whose
close time is <= target. label-v1 stays archival and is never read here.
"""

from __future__ import annotations

import asyncio
import math
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select

from crypto_trader.exchange.okx import OKXAdapter, OKXDiagnosticError
from crypto_trader.persistence.models import ScanSnapshotLabelORM, ScanSnapshotORM

LABEL_VERSION = "label-v2"
LABEL_CONFIG_VERSION = "label-config-v2.0"
ENDPOINT_POLICY = "last_closed_candle_at_or_before_target"
COST_VERSION_DECISION = "label-cost-v2-decision-time"
COST_VERSION_ESTIMATE = "label-cost-v2-fallback-estimate"
FALLBACK_COST_BPS = 22.0
MIN_EDGE_BPS_DEFAULT = 10.0
ALIGNMENT_TOLERANCE_SECONDS = 60.0
ALIGNMENT_POLICY_VERSION = "label-alignment-v2.0"
PATH_QUALITY_FULL = "FULL"
PATH_QUALITY_UNAVAILABLE_PARTIAL_START = "UNAVAILABLE_PARTIAL_START"
PATH_QUALITY_UNAVAILABLE = "UNAVAILABLE"
ENDPOINT_QUALITY_CLOSED = "CLOSED_AT_OR_BEFORE_TARGET"
ENDPOINT_QUALITY_NOT_EVALUATED = "NOT_EVALUATED"

HORIZON_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
}
BAR_FOR_HORIZON: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1H",
    "4h": "4H",
}
STATUS_IMMATURE = "IMMATURE"
STATUS_MATURE_VALID = "MATURE_VALID"
STATUS_INCONCLUSIVE_DATA_GAP = "INCONCLUSIVE_DATA_GAP"
STATUS_INCONCLUSIVE_ALIGNMENT = "INCONCLUSIVE_ALIGNMENT"
STATUS_TRANSIENT_SOURCE_ERROR = "TRANSIENT_SOURCE_ERROR"


class TransientSourceError(RuntimeError):
    """Retryable factual source failure; never treated as a mature label."""


@dataclass(frozen=True)
class Candle:
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    bar_ms: int
    confirm: bool = True

    @property
    def close_ts_ms(self) -> int:
        return self.ts_ms + self.bar_ms


class CandleProvider(Protocol):
    async def closed_candles(
        self, symbol: str, bar: str, start_ms: int, end_ms: int
    ) -> list[Candle]: ...


def _bar_ms(horizon: str) -> int:
    return HORIZON_SECONDS[horizon] * 1000


def parse_okx_candles(rows: list[list[str]], bar_ms: int) -> list[Candle]:
    out: list[Candle] = []
    for row in rows:
        try:
            if len(row) < 9 or str(row[8]) != "1":  # closed candles only
                continue
            out.append(
                Candle(
                    ts_ms=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    bar_ms=bar_ms,
                )
            )
        except (TypeError, ValueError):
            continue
    return out


class OkxHistoricalCandleProvider:
    """Bounded backward pagination over OKX public history-candles.

    Empirical OKX semantics on ``/api/v5/market/history-candles``:
      after=X  -> rows earlier than X (older)
      before=X -> rows newer than X (newer)

    Backward traversal therefore uses ``after`` and walks timestamps downward
    until the requested start boundary or a bounded page cap is reached.
    """

    def __init__(
        self,
        client: OKXAdapter,
        *,
        page_limit: int = 100,
        max_pages: int = 12,
        cache_ttl_seconds: float = 300.0,
        page_delay_seconds: float = 0.05,
        max_cache_entries: int = 512,
    ) -> None:
        from crypto_trader.exchange.symbol_mapper import SymbolMapper

        self.client = client
        self.page_limit = max(1, min(int(page_limit), 100))
        self.max_pages = max(1, int(max_pages))
        self.cache_ttl_seconds = float(cache_ttl_seconds)
        self.page_delay_seconds = float(page_delay_seconds)
        self.max_cache_entries = max(1, int(max_cache_entries))
        self.mapper = SymbolMapper()
        self._cache: dict[tuple[str, str, int, int], tuple[float, list[Candle]]] = {}
        self.history_requests = 0
        self.history_errors = 0
        self.pages_fetched = 0
        self.cache_hits = 0
        self.history_latency_seconds = 0.0
        self.last_history_error: str | None = None

    async def closed_candles(
        self, symbol: str, bar: str, start_ms: int, end_ms: int
    ) -> list[Candle]:
        key = (symbol, bar, int(start_ms), int(end_ms))
        loop = asyncio.get_running_loop()
        now_mono = loop.time()
        cached = self._cache.get(key)
        if cached and now_mono - cached[0] <= self.cache_ttl_seconds:
            self.cache_hits += 1
            return list(cached[1])

        inst_id = self.mapper.to_okx(symbol)
        bar_ms = self._bar_ms(bar)
        # A raw decision T0 can be mid-bar. Fetch from the bar-aligned start so
        # the candle covering T0 is available for the endpoint rule; build_label
        # still excludes pre-T0 high/low from path metrics.
        fetch_start_ms = (int(start_ms) // bar_ms) * bar_ms
        collected: dict[int, Candle] = {}
        after = int(end_ms) + 1
        pages = 0
        while pages < self.max_pages:
            started = loop.time()
            try:
                rows = await self.client.get_history_candles(
                    inst_id, bar, after=after, limit=self.page_limit
                )
            except OKXDiagnosticError as exc:
                self.history_errors += 1
                self.last_history_error = f"OKXDiagnosticError:{exc.reason_code}:{exc.safe_message}"
                raise TransientSourceError("HISTORY_CANDLES_FAILED") from exc
            except Exception as exc:  # network/transport
                self.history_errors += 1
                self.last_history_error = type(exc).__name__
                raise TransientSourceError("HISTORY_CANDLES_TRANSPORT") from exc
            finally:
                self.history_latency_seconds += max(0.0, loop.time() - started)

            self.history_requests += 1
            self.pages_fetched += 1
            if not rows:
                break
            timestamps = [
                int(row[0]) for row in rows if len(row) >= 1 and str(row[0]).isdigit()
            ]
            if not timestamps:
                break
            page_oldest = min(timestamps)
            for candle in parse_okx_candles(rows, bar_ms):
                if fetch_start_ms <= candle.ts_ms <= int(end_ms):
                    collected[candle.ts_ms] = candle

            pages += 1
            if page_oldest <= fetch_start_ms:
                break
            if page_oldest >= after:  # cursor did not move strictly backward
                break
            after = page_oldest
            if self.page_delay_seconds:
                await asyncio.sleep(self.page_delay_seconds)

        candles = [collected[ts] for ts in sorted(collected)]
        self._cache[key] = (now_mono, candles)
        self._evict_cache()
        return candles

    def stats(self) -> dict[str, Any]:
        return {
            "history_requests": self.history_requests,
            "history_errors": self.history_errors,
            "history_page_requests": self.pages_fetched,
            "history_latency_seconds": round(self.history_latency_seconds, 3),
            "history_cache_hits": self.cache_hits,
            "last_history_error": self.last_history_error,
        }

    def _evict_cache(self) -> None:
        while len(self._cache) > self.max_cache_entries:
            oldest_key = min(self._cache, key=lambda key: self._cache[key][0])
            self._cache.pop(oldest_key, None)

    @staticmethod
    def _bar_ms(bar: str) -> int:
        mapping = {
            "1m": 60_000,
            "5m": 300_000,
            "15m": 900_000,
            "30m": 1_800_000,
            "1H": 3_600_000,
            "4H": 14_400_000,
        }
        return mapping[bar]


@dataclass(frozen=True)
class CostTruth:
    all_in_cost_bps: float
    cost_version: str
    quality: str
    components: dict[str, Any]


def decision_time_cost(features: dict[str, Any] | None) -> CostTruth:
    """Versioned decision-time economics, never a bare universal constant."""
    features = features or {}
    costs = features.get("costs") if isinstance(features.get("costs"), dict) else {}
    components: dict[str, Any] = dict(costs or {})
    total = components.get("total_cost_bps")
    if total is None:
        pieces = {
            name: components.get(name)
            for name in (
                "entry_fee_bps",
                "exit_fee_bps",
                "spread_bps",
                "slippage_bps",
                "funding_bps",
            )
        }
        present = [float(v) for v in pieces.values() if isinstance(v, (int, float))]
        if present:
            components.update({"derived_sum_bps": sum(present), "components": pieces})
            return CostTruth(
                sum(present), COST_VERSION_DECISION, "decision_time_components", components
            )
        components.update(
            {
                "fallback_bps": FALLBACK_COST_BPS,
                "missing": ["decision_time_costs_absent"],
                "note": "explicit versioned fallback estimate; quality degraded",
            }
        )
        return CostTruth(FALLBACK_COST_BPS, COST_VERSION_ESTIMATE, "estimated_missing", components)
    components.setdefault("source", "snapshot_decision_time")
    return CostTruth(float(total), COST_VERSION_DECISION, "decision_time", components)


@dataclass(frozen=True)
class LabelResult:
    maturity_status: str
    usable_for_training: bool
    requested_target_ts: datetime
    actual_target_ts: datetime | None
    alignment_error_seconds: float | None
    path_start_ts: datetime | None
    path_end_ts: datetime | None
    data_gap: bool
    entry_price: float | None
    future_high: float | None
    future_low: float | None
    realized_volatility: float | None
    long_gross_bps: float | None
    short_gross_bps: float | None
    all_in_cost_bps: float
    long_net_bps: float | None
    short_net_bps: float | None
    long_label: str
    short_label: str
    cost: CostTruth
    raw_t0: datetime | None = None
    aligned_bar_start: datetime | None = None
    partial_start_bar: bool = False
    path_quality: str = PATH_QUALITY_UNAVAILABLE
    endpoint_quality: str = ENDPOINT_QUALITY_NOT_EVALUATED
    alignment_policy_version: str = ALIGNMENT_POLICY_VERSION
    factual_source: str = "OKX_HISTORY_CANDLES"


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


class LabelV2Maturer:
    """Builds exact post-cost labels or an explicit inconclusive status.

    Alignment policy v2:

    * ``requested_target_ts`` remains raw T0 + horizon.
    * The endpoint may be the last closed candle whose close time is at or
      before the requested target, even if that candle opened before raw T0,
      because that close is a factual observation by the target time.
    * Path MFE/MAE is computed only from candles whose *open* is at or after
      raw T0. If the only closed endpoint candle covers T0, endpoint return is
      still factual while path metrics are marked explicitly unavailable rather
      than using pre-decision extrema.
    """

    def __init__(
        self, *, min_edge_bps: float = MIN_EDGE_BPS_DEFAULT, gap_ratio: float = 0.75
    ) -> None:
        self.min_edge_bps = float(min_edge_bps)
        self.gap_ratio = float(gap_ratio)

    def build_label(
        self,
        snapshot: ScanSnapshotORM,
        horizon: str,
        *,
        candles: list[Candle] | None = None,
        source_error: bool = False,
        now: datetime | None = None,
    ) -> LabelResult:
        now = _utc(now or datetime.now(UTC))
        t0 = _utc(snapshot.captured_at)
        bar_ms = _bar_ms(horizon)
        requested_target = t0 + timedelta(seconds=HORIZON_SECONDS[horizon])
        raw_t0_ms = int(t0.timestamp() * 1000)
        aligned_bar_start_ms = (raw_t0_ms // bar_ms) * bar_ms
        aligned_bar_start = datetime.fromtimestamp(aligned_bar_start_ms / 1000, tz=UTC)

        features = snapshot.features_json or {}
        entry = features.get("price")
        entry_price = float(entry) if isinstance(entry, (int, float)) else None
        cost = decision_time_cost(features)

        empty: dict[str, Any] = dict(
            usable_for_training=False,
            requested_target_ts=requested_target,
            actual_target_ts=None,
            alignment_error_seconds=None,
            path_start_ts=None,
            path_end_ts=None,
            data_gap=True,
            entry_price=entry_price,
            future_high=None,
            future_low=None,
            realized_volatility=None,
            long_gross_bps=None,
            short_gross_bps=None,
            all_in_cost_bps=cost.all_in_cost_bps,
            long_net_bps=None,
            short_net_bps=None,
            long_label="NOT_PROFITABLE",
            short_label="NOT_PROFITABLE",
            cost=cost,
            raw_t0=t0,
            aligned_bar_start=aligned_bar_start,
            partial_start_bar=False,
            path_quality=PATH_QUALITY_UNAVAILABLE,
            endpoint_quality=ENDPOINT_QUALITY_NOT_EVALUATED,
            alignment_policy_version=ALIGNMENT_POLICY_VERSION,
        )
        if now < requested_target:
            return LabelResult(maturity_status=STATUS_IMMATURE, **empty)
        if source_error:
            return LabelResult(maturity_status=STATUS_TRANSIENT_SOURCE_ERROR, **empty)
        if entry_price is None or entry_price <= 0:
            return LabelResult(maturity_status=STATUS_INCONCLUSIVE_DATA_GAP, **empty)

        target_ms = int(requested_target.timestamp() * 1000)
        candidates = [
            candle
            for candle in (candles or [])
            if candle.confirm
            and candle.close_ts_ms <= target_ms
            and candle.close_ts_ms > raw_t0_ms
        ]
        if not candidates:
            return LabelResult(maturity_status=STATUS_INCONCLUSIVE_DATA_GAP, **empty)

        candidates.sort(key=lambda candle: (candle.close_ts_ms, candle.ts_ms))
        endpoint = candidates[-1]
        actual_target = datetime.fromtimestamp(endpoint.close_ts_ms / 1000, tz=UTC)
        alignment_error = max(0.0, (target_ms - endpoint.close_ts_ms) / 1000.0)
        partial_start_bar = endpoint.ts_ms < raw_t0_ms
        path_candles = [candle for candle in candidates if candle.ts_ms >= raw_t0_ms]
        if path_candles:
            path_quality = PATH_QUALITY_FULL
        elif partial_start_bar:
            path_quality = PATH_QUALITY_UNAVAILABLE_PARTIAL_START
        else:
            path_quality = PATH_QUALITY_UNAVAILABLE
        endpoint_quality = ENDPOINT_QUALITY_CLOSED

        if alignment_error > ALIGNMENT_TOLERANCE_SECONDS:
            inconclusive = dict(empty)
            inconclusive.update(
                actual_target_ts=actual_target,
                alignment_error_seconds=alignment_error,
                data_gap=False,
                partial_start_bar=partial_start_bar,
                path_quality=path_quality,
                endpoint_quality=endpoint_quality,
            )
            return LabelResult(maturity_status=STATUS_INCONCLUSIVE_ALIGNMENT, **inconclusive)

        long_gross = (endpoint.close - entry_price) / entry_price * 10000.0
        short_gross = -long_gross
        long_net = long_gross - cost.all_in_cost_bps
        short_net = short_gross - cost.all_in_cost_bps

        future_high = max((candle.high for candle in path_candles), default=None)
        future_low = min((candle.low for candle in path_candles), default=None)
        path_closes = [candle.close for candle in path_candles if candle.close > 0]
        realized_volatility = (
            statistics.pstdev(
                [math.log(path_closes[i] / path_closes[i - 1]) for i in range(1, len(path_closes))]
            )
            * 10000.0
            if len(path_closes) >= 2
            else None
        )
        path_start_ts = (
            datetime.fromtimestamp(path_candles[0].ts_ms / 1000, tz=UTC) if path_candles else None
        )
        path_end_ts = actual_target if path_candles else None

        mature = dict(empty)
        mature.update(
            usable_for_training=True,
            actual_target_ts=actual_target,
            alignment_error_seconds=alignment_error,
            path_start_ts=path_start_ts,
            path_end_ts=path_end_ts,
            data_gap=False,
            future_high=future_high,
            future_low=future_low,
            realized_volatility=realized_volatility,
            long_gross_bps=long_gross,
            short_gross_bps=short_gross,
            long_net_bps=long_net,
            short_net_bps=short_net,
            long_label="PROFITABLE" if long_net > self.min_edge_bps else "NOT_PROFITABLE",
            short_label="PROFITABLE" if short_net > self.min_edge_bps else "NOT_PROFITABLE",
            partial_start_bar=partial_start_bar,
            path_quality=path_quality,
            endpoint_quality=endpoint_quality,
        )
        return LabelResult(maturity_status=STATUS_MATURE_VALID, **mature)

    async def mature_pending(
        self,
        session_factory,
        provider: CandleProvider,
        *,
        now: datetime | None = None,
        limit: int = 400,
        on_result: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, int]:
        now = _utc(now or datetime.now(UTC))
        counts = {
            status: 0
            for status in (
                STATUS_IMMATURE,
                STATUS_MATURE_VALID,
                STATUS_INCONCLUSIVE_DATA_GAP,
                STATUS_INCONCLUSIVE_ALIGNMENT,
                STATUS_TRANSIENT_SOURCE_ERROR,
            )
        }
        async with session_factory() as s:
            snaps = (
                (
                    await s.execute(
                        select(ScanSnapshotORM)
                        .where(ScanSnapshotORM.outcome_status == "PENDING")
                        .order_by(ScanSnapshotORM.captured_at)
                        .limit(max(1, int(limit)))
                    )
                )
                .scalars()
                .all()
            )
            existing_rows = (
                (
                    await s.execute(
                        select(ScanSnapshotLabelORM).where(
                            ScanSnapshotLabelORM.label_version == LABEL_VERSION
                        )
                    )
                )
                .scalars()
                .all()
            )
            existing = {(r.snapshot_id, r.horizon): r for r in existing_rows}
            for snap in snaps:
                t0 = _utc(snap.captured_at)
                for horizon, seconds in HORIZON_SECONDS.items():
                    requested = t0 + timedelta(seconds=seconds)
                    row = existing.get((snap.snapshot_id, horizon))
                    if requested > now:
                        # Persist an explicit IMMATURE row so the backlog and
                        # heartbeat expose truthful progress before maturity.
                        result = self.build_label(snap, horizon, now=now)
                    else:
                        if row is not None and row.maturation_status == STATUS_MATURE_VALID:
                            continue
                        try:
                            candles = await provider.closed_candles(
                                snap.symbol,
                                BAR_FOR_HORIZON[horizon],
                                int(t0.timestamp() * 1000),
                                int(requested.timestamp() * 1000),
                            )
                            result = self.build_label(snap, horizon, candles=candles, now=now)
                        except TransientSourceError:
                            result = self.build_label(
                                snap, horizon, source_error=True, now=now
                            )
                    counts[result.maturity_status] += 1
                    target_row = row
                    if target_row is None:
                        target_row = ScanSnapshotLabelORM(
                            snapshot_id=snap.snapshot_id,
                            symbol=snap.symbol,
                            snapshot_ts=snap.captured_at,
                            horizon=horizon,
                            feature_version="scan-features-v1",
                            label_version=LABEL_VERSION,
                        )
                        s.add(target_row)
                        existing[(snap.snapshot_id, horizon)] = target_row
                    self._apply(target_row, result, now)
                    self._notify(on_result, snap, horizon, result.maturity_status)

                terminal_statuses = {
                    STATUS_MATURE_VALID,
                    STATUS_INCONCLUSIVE_DATA_GAP,
                    STATUS_INCONCLUSIVE_ALIGNMENT,
                }
                if all(
                    (snap.snapshot_id, h) in existing
                    and existing[(snap.snapshot_id, h)].maturation_status in terminal_statuses
                    for h in HORIZON_SECONDS
                ):
                    snap.outcome_status = "LABELED"
                # Per-snapshot transaction: completed factual work survives a
                # later timeout/cancellation on any subsequent snapshot.
                await s.commit()
        return counts

    @staticmethod
    def _notify(
        on_result: Callable[[dict[str, Any]], None] | None,
        snap: ScanSnapshotORM,
        horizon: str,
        status: str,
    ) -> None:
        if on_result is None:
            return
        try:
            on_result(
                {
                    "snapshot_id": snap.snapshot_id,
                    "symbol": snap.symbol,
                    "horizon": horizon,
                    "status": status,
                }
            )
        except Exception:
            pass

    @staticmethod
    def _apply(row: ScanSnapshotLabelORM, r: LabelResult, now: datetime) -> None:
        row.maturation_status = r.maturity_status
        row.usable_for_training = bool(r.usable_for_training)
        row.requested_target_ts = r.requested_target_ts
        row.actual_target_ts = r.actual_target_ts
        row.alignment_error_seconds = r.alignment_error_seconds
        row.endpoint_policy = ENDPOINT_POLICY
        row.path_start_ts = r.path_start_ts
        row.path_end_ts = r.path_end_ts
        row.data_gap = bool(r.data_gap)
        row.factual_source = r.factual_source
        row.entry_price = r.entry_price
        row.cost_version = r.cost.cost_version
        row.cost_components_json = {**r.cost.components, "quality": r.cost.quality}
        row.label_config_version = LABEL_CONFIG_VERSION
        row.alignment_policy_version = r.alignment_policy_version
        row.raw_t0 = r.raw_t0
        row.aligned_bar_start = r.aligned_bar_start
        row.partial_start_bar = bool(r.partial_start_bar)
        row.path_quality = r.path_quality
        row.endpoint_quality = r.endpoint_quality
        row.future_high = r.future_high
        row.future_low = r.future_low
        row.realized_volatility = r.realized_volatility
        row.long_gross_bps = r.long_gross_bps
        row.short_gross_bps = r.short_gross_bps
        row.all_in_cost_bps = r.all_in_cost_bps
        row.long_net_bps = r.long_net_bps
        row.short_net_bps = r.short_net_bps
        row.long_net_edge_bps = r.long_net_bps
        row.short_net_edge_bps = r.short_net_bps
        row.long_label = r.long_label
        row.short_label = r.short_label
        row.matured_at = r.actual_target_ts or r.requested_target_ts or now
