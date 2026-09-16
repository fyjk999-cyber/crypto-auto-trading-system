"""Label-v2 exact factual outcome engine (LEARNING_ONLY).

For every scanner snapshot at T0 and horizon H the maturer reconstructs the
factual OKX path that ended at exactly T0+H, using only closed candles whose
close time is <= target. label-v1 stays archival and is never read here.
"""

from __future__ import annotations

import asyncio
import math
import statistics
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
    """Bounded pagination over OKX public history-candles with a small cache."""

    def __init__(
        self,
        client: OKXAdapter,
        *,
        page_limit: int = 100,
        max_pages: int = 12,
        cache_ttl_seconds: float = 300.0,
        page_delay_seconds: float = 0.05,
    ) -> None:
        from crypto_trader.exchange.symbol_mapper import SymbolMapper

        self.client = client
        self.page_limit = max(1, min(int(page_limit), 100))
        self.max_pages = max(1, int(max_pages))
        self.cache_ttl_seconds = float(cache_ttl_seconds)
        self.page_delay_seconds = float(page_delay_seconds)
        self.mapper = SymbolMapper()
        self._cache: dict[tuple[str, str, int, int], tuple[float, list[Candle]]] = {}

    async def closed_candles(
        self, symbol: str, bar: str, start_ms: int, end_ms: int
    ) -> list[Candle]:
        key = (symbol, bar, int(start_ms), int(end_ms))
        now_mono = asyncio.get_running_loop().time()
        cached = self._cache.get(key)
        if cached and now_mono - cached[0] <= self.cache_ttl_seconds:
            return list(cached[1])

        inst_id = self.mapper.to_okx(symbol)
        bar_ms = self._bar_ms(bar)
        collected: dict[int, Candle] = {}
        before = int(end_ms) + 1
        pages = 0
        while pages < self.max_pages:
            try:
                rows = await self.client.get_history_candles(
                    inst_id, bar, before=before, limit=self.page_limit
                )
            except OKXDiagnosticError as exc:
                raise TransientSourceError("HISTORY_CANDLES_FAILED") from exc
            except Exception as exc:  # network/transport
                raise TransientSourceError("HISTORY_CANDLES_TRANSPORT") from exc
            if not rows:
                break
            parsed = parse_okx_candles(rows, bar_ms)
            if not parsed:
                break
            for candle in parsed:
                if start_ms <= candle.ts_ms <= end_ms:
                    collected[candle.ts_ms] = candle
            oldest = min(int(row[0]) for row in rows if len(row) >= 1 and str(row[0]).isdigit())
            pages += 1
            if oldest <= int(start_ms):
                break
            before = oldest
            if self.page_delay_seconds:
                await asyncio.sleep(self.page_delay_seconds)
        candles = [collected[ts] for ts in sorted(collected)]
        self._cache[key] = (now_mono, candles)
        return candles

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
    factual_source: str = "OKX_HISTORY_CANDLES"


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


class LabelV2Maturer:
    """Builds exact post-cost labels or an explicit inconclusive status."""

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
        requested_target = t0 + timedelta(seconds=HORIZON_SECONDS[horizon])
        bar_ms = _bar_ms(horizon)
        features = snapshot.features_json or {}
        entry = features.get("price")
        entry_price = float(entry) if isinstance(entry, (int, float)) else None
        cost = decision_time_cost(features)
        empty = dict(
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
        )
        if now < requested_target:
            return LabelResult(maturity_status=STATUS_IMMATURE, **empty)
        if source_error:
            return LabelResult(maturity_status=STATUS_TRANSIENT_SOURCE_ERROR, **empty)
        if entry_price is None or entry_price <= 0:
            return LabelResult(maturity_status=STATUS_INCONCLUSIVE_DATA_GAP, **empty)

        target_ms = int(requested_target.timestamp() * 1000)
        usable = [c for c in (candles or []) if c.confirm and c.close_ts_ms <= target_ms]
        usable = [c for c in usable if c.ts_ms >= int(t0.timestamp() * 1000)]
        if not usable:
            return LabelResult(maturity_status=STATUS_INCONCLUSIVE_DATA_GAP, **empty)
        usable.sort(key=lambda c: (c.ts_ms, c.close_ts_ms))
        endpoint = max(usable, key=lambda c: c.close_ts_ms)
        actual_target = datetime.fromtimestamp(endpoint.close_ts_ms / 1000, tz=UTC)
        alignment_error = max(0.0, (target_ms - endpoint.close_ts_ms) / 1000.0)
        expected_bars = max(1, HORIZON_SECONDS[horizon] * 1000 // bar_ms)
        if len(usable) < max(1, int(expected_bars * self.gap_ratio)):
            return LabelResult(
                maturity_status=STATUS_INCONCLUSIVE_DATA_GAP,
                actual_target_ts=actual_target,
                alignment_error_seconds=alignment_error,
                path_start_ts=datetime.fromtimestamp(usable[0].ts_ms / 1000, tz=UTC),
                path_end_ts=actual_target,
                data_gap=True,
                entry_price=entry_price,
                **{
                    k: empty[k]
                    for k in (
                        "requested_target_ts",
                        "usable_for_training",
                        "all_in_cost_bps",
                        "future_high",
                        "future_low",
                        "realized_volatility",
                        "long_gross_bps",
                        "short_gross_bps",
                        "long_net_bps",
                        "short_net_bps",
                        "long_label",
                        "short_label",
                        "cost",
                    )
                },
            )
        if alignment_error > ALIGNMENT_TOLERANCE_SECONDS:
            return LabelResult(
                maturity_status=STATUS_INCONCLUSIVE_ALIGNMENT,
                actual_target_ts=actual_target,
                alignment_error_seconds=alignment_error,
                path_start_ts=datetime.fromtimestamp(usable[0].ts_ms / 1000, tz=UTC),
                path_end_ts=actual_target,
                data_gap=False,
                entry_price=entry_price,
                **{
                    k: empty[k]
                    for k in (
                        "requested_target_ts",
                        "usable_for_training",
                        "all_in_cost_bps",
                        "future_high",
                        "future_low",
                        "realized_volatility",
                        "long_gross_bps",
                        "short_gross_bps",
                        "long_net_bps",
                        "short_net_bps",
                        "long_label",
                        "short_label",
                        "cost",
                    )
                },
            )

        long_gross = (endpoint.close - entry_price) / entry_price * 10000.0
        short_gross = -long_gross
        long_net = long_gross - cost.all_in_cost_bps
        short_net = short_gross - cost.all_in_cost_bps
        closes = [c.close for c in usable if c.close > 0]
        realized = (
            statistics.pstdev([math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))])
            * 10000.0
            if len(closes) >= 2
            else 0.0
        )
        return LabelResult(
            maturity_status=STATUS_MATURE_VALID,
            usable_for_training=True,
            requested_target_ts=requested_target,
            actual_target_ts=actual_target,
            alignment_error_seconds=alignment_error,
            path_start_ts=datetime.fromtimestamp(usable[0].ts_ms / 1000, tz=UTC),
            path_end_ts=actual_target,
            data_gap=False,
            entry_price=entry_price,
            future_high=max(c.high for c in usable),
            future_low=min(c.low for c in usable),
            realized_volatility=realized,
            long_gross_bps=long_gross,
            short_gross_bps=short_gross,
            all_in_cost_bps=cost.all_in_cost_bps,
            long_net_bps=long_net,
            short_net_bps=short_net,
            long_label="PROFITABLE" if long_net > self.min_edge_bps else "NOT_PROFITABLE",
            short_label="PROFITABLE" if short_net > self.min_edge_bps else "NOT_PROFITABLE",
            cost=cost,
        )

    async def mature_pending(
        self,
        session_factory,
        provider: CandleProvider,
        *,
        now: datetime | None = None,
        limit: int = 400,
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
                    if requested > now:
                        counts[STATUS_IMMATURE] += 1
                        continue
                    row = existing.get((snap.snapshot_id, horizon))
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
                        result = self.build_label(snap, horizon, source_error=True, now=now)
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
                if all(
                    (snap.snapshot_id, h) in existing
                    and existing[(snap.snapshot_id, h)].maturation_status == STATUS_MATURE_VALID
                    for h in HORIZON_SECONDS
                ):
                    snap.outcome_status = "LABELED"
            await s.commit()
        return counts

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
