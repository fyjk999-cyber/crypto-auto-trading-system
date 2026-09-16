# Autonomous factual horizon maturement (derived labels; LEARNING_ONLY).
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.persistence.models import (
    OpportunityOutcomeMaturationORM,
    ScanSnapshotORM,
)

OUTCOME_VERSION = "outcome-v1"
COST_VERSION = "all-in-v1"
DEFAULT_COST_BPS = 22.0
HORIZON_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "12h": 43200,
    "24h": 86400,
}
HORIZON_BAR = {
    "1m": "1m",
    "5m": "1m",
    "15m": "1m",
    "30m": "1m",
    "1h": "1m",
    "4h": "5m",
    "12h": "1h",
    "24h": "1h",
}


@dataclass(frozen=True)
class _Candle:
    ts: datetime
    open: float
    high: float
    low: float
    close: float


def resolve_direction(features: dict) -> tuple[str | None, str]:
    if features.get("decision_id"):
        return (features.get("expected_direction") or features.get("direction")), "CORE_LLM"
    if features.get("model_evidence"):
        return features.get("consensus_direction"), "EVIDENCE_REFERENCE"
    return None, "NONE"


def _realized_volatility(closes: list[float]) -> float:
    returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1]
    ]
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(var) * 10000.0


def evaluate_horizon(
    *,
    entry_price: float,
    target_price: float,
    highs: list[float],
    lows: list[float],
    closes: list[float],
    expected_direction: str | None,
    all_in_cost_bps: float,
    direction_source: str,
) -> dict:
    raw = (target_price - entry_price) / entry_price * 10000.0
    long_gross, short_gross = raw, -raw
    long_net, short_net = long_gross - all_in_cost_bps, short_gross - all_in_cost_bps
    direction = (expected_direction or "LONG").upper()

    def signed(p: float) -> float:
        value = (p - entry_price) / entry_price * 10000.0
        return value if direction == "LONG" else -value

    excursions = [signed(p) for p in closes] or [0.0]
    expected_net = long_net if direction == "LONG" else short_net
    label = None
    if expected_direction and direction_source in ("CORE_LLM", "EVIDENCE_REFERENCE"):
        label = "DIRECTION_CORRECT" if expected_net > 0 else "DIRECTION_WRONG"
    return {
        "long_gross_bps": round(long_gross, 6),
        "short_gross_bps": round(short_gross, 6),
        "long_net_bps": round(long_net, 6),
        "short_net_bps": round(short_net, 6),
        "net_edge_bps": round(max(long_net, short_net), 6),
        "future_high": max(highs),
        "future_low": min(lows),
        "mfe_bps": round(max(excursions), 6),
        "mae_bps": round(min(excursions), 6),
        "realized_volatility": round(_realized_volatility(closes), 6),
        "label": label,
    }


async def _load_candles(
    client,
    cache: dict,
    symbol: str,
    bar: str,
    start_ts: datetime,
    target_ts: datetime,
    max_pages: int = 20,
) -> tuple:
    """Bounded historical pagination covering [start_ts, target_ts]."""
    bar_seconds = {"1m": 60, "5m": 300, "1h": 3600}.get(bar, 60)
    key = (symbol, bar, int(start_ts.timestamp()) // 60, int(target_ts.timestamp()) // 60)
    if key in cache:
        return cache[key]
    try:
        inst_id = SymbolMapper().to_okx(symbol)
    except ValueError:
        cache[key] = ([], 0, True)
        return cache[key]
    start_ms = int(start_ts.timestamp() * 1000)
    cursor_ms = int(target_ts.timestamp() * 1000) + bar_seconds * 1000
    candles: dict = {}
    pages = 0
    data_gap = False
    while pages < max_pages:
        try:
            rows = await client.get_candles(inst_id, bar, 300, after=cursor_ms)
        except Exception:
            data_gap = True
            break
        parsed = []
        for row in rows or []:
            if not isinstance(row, (list, tuple)) or len(row) < 9 or str(row[8]) != "1":
                continue
            try:
                parsed.append(
                    _Candle(
                        datetime.fromtimestamp(int(row[0]) / 1000, UTC),
                        float(row[1]),
                        float(row[2]),
                        float(row[3]),
                        float(row[4]),
                    )
                )
            except (TypeError, ValueError, IndexError):
                continue
        if not parsed:
            break
        pages += 1
        earliest = min(candle.ts for candle in parsed)
        for candle in parsed:
            candles.setdefault(candle.ts, candle)
        if int(earliest.timestamp() * 1000) <= start_ms:
            break
        if pages > 1 and int(earliest.timestamp() * 1000) >= cursor_ms:
            data_gap = True
            break
        cursor_ms = int(earliest.timestamp() * 1000)
    ordered = sorted(candles.values(), key=lambda candle: candle.ts)
    if not ordered or ordered[0].ts > start_ts:
        data_gap = True
    cache[key] = (ordered, pages, data_gap)
    return cache[key]


async def mature_due(
    session_factory,
    client,
    *,
    now: datetime | None = None,
    max_observations: int = 500,
    horizons: dict | None = None,
) -> dict:
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    horizon_map = horizons or HORIZON_SECONDS
    summary = {
        "written": 0,
        "skipped_existing": 0,
        "skipped_immature": 0,
        "errors": 0,
        "unaligned": 0,
        "inconclusive": 0,
        "history_pages": 0,
        "data_gaps": 0,
        "by_direction_source": {},
    }
    cache: dict = {}
    async with session_factory() as session:
        observations = (
            (
                await session.execute(
                    select(ScanSnapshotORM)
                    .where(ScanSnapshotORM.trading_day.is_not(None))
                    .where(ScanSnapshotORM.candidate.is_(True))
                    .order_by(ScanSnapshotORM.captured_at.asc())
                    .limit(max_observations)
                )
            )
            .scalars()
            .all()
        )
        existing = {
            (row[0], row[1], row[2])
            for row in (
                await session.execute(
                    select(
                        OpportunityOutcomeMaturationORM.observation_id,
                        OpportunityOutcomeMaturationORM.horizon,
                        OpportunityOutcomeMaturationORM.outcome_version,
                    )
                )
            ).all()
        }
        for observation in observations:
            features = observation.features_json or {}
            entry_price = features.get("price")
            captured = observation.captured_at
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=UTC)
            direction, source = resolve_direction(features)
            for horizon, seconds in horizon_map.items():
                identity = (observation.snapshot_id, horizon, OUTCOME_VERSION)
                if identity in existing:
                    summary["skipped_existing"] += 1
                    continue
                if captured + timedelta(seconds=seconds) > moment:
                    summary["skipped_immature"] += 1
                    continue
                if not entry_price:
                    summary["errors"] += 1
                    continue
                bar = HORIZON_BAR.get(horizon, "1m")
                target_ts = captured + timedelta(seconds=seconds)
                bar_seconds = {"1m": 60, "5m": 300, "1h": 3600}.get(bar, 60)
                bar_delta = timedelta(seconds=bar_seconds)
                candles, pages_fetched, data_gap = await _load_candles(
                    client, cache, observation.symbol, bar, captured, target_ts
                )
                summary["history_pages"] += pages_fetched
                if data_gap:
                    summary["data_gaps"] += 1
                # STRICT: only fully-closed bars whose end is at/before the horizon.
                path = [
                    candle
                    for candle in candles
                    if captured <= candle.ts and candle.ts + bar_delta <= target_ts
                ]
                if not path:
                    summary["inconclusive"] += 1
                    continue
                target_candle = path[-1]
                actual_target_ts = target_candle.ts + bar_delta
                alignment_error = (target_ts - actual_target_ts).total_seconds()
                alignment_ok = alignment_error <= bar_seconds and not data_gap
                if not alignment_ok:
                    summary["unaligned"] += 1
                all_in_cost = float(
                    (features.get("costs") or {}).get("total_cost_bps") or DEFAULT_COST_BPS
                )
                metrics = evaluate_horizon(
                    entry_price=float(entry_price),
                    target_price=target_candle.close,
                    highs=[c.high for c in path],
                    lows=[c.low for c in path],
                    closes=[c.close for c in path],
                    expected_direction=direction,
                    all_in_cost_bps=all_in_cost,
                    direction_source=source,
                )
                session.add(
                    OpportunityOutcomeMaturationORM(
                        observation_id=observation.snapshot_id,
                        trading_day=observation.trading_day,
                        symbol=observation.symbol,
                        horizon=horizon,
                        outcome_version=OUTCOME_VERSION,
                        market_source="OKX_PUBLIC_CANDLES",
                        direction_source=source,
                        expected_direction=(direction.upper() if direction else None),
                        entry_price=float(entry_price),
                        target_price=target_candle.close,
                        requested_target_ts=target_ts,
                        actual_target_ts=actual_target_ts,
                        alignment_error_seconds=alignment_error,
                        alignment_ok=alignment_ok,
                        endpoint_policy="CLOSED_BAR_END_LE_TARGET",
                        final_bar_partial=False,
                        data_gap=data_gap,
                        pages_fetched=pages_fetched,
                        path_start_ts=path[0].ts,
                        path_end_ts=actual_target_ts,
                        long_gross_bps=metrics["long_gross_bps"],
                        short_gross_bps=metrics["short_gross_bps"],
                        all_in_cost_bps=all_in_cost,
                        long_net_bps=metrics["long_net_bps"],
                        short_net_bps=metrics["short_net_bps"],
                        net_edge_bps=metrics["net_edge_bps"],
                        future_high=metrics["future_high"],
                        future_low=metrics["future_low"],
                        mfe_bps=metrics["mfe_bps"],
                        mae_bps=metrics["mae_bps"],
                        realized_volatility=metrics["realized_volatility"],
                        label=metrics["label"],
                        cost_version=COST_VERSION,
                        authority="LEARNING_ONLY",
                    )
                )
                existing.add(identity)
                summary["written"] += 1
                summary["by_direction_source"][source] = (
                    summary["by_direction_source"].get(source, 0) + 1
                )
        await session.commit()
    return summary
