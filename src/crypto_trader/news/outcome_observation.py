"""Factual horizon-aligned market observation for News outcome reviews.

The provider uses only closed public OKX candles. It never substitutes a
current ticker price, never reads beyond the requested horizon target, and
returns an explicit INCONCLUSIVE_DATA_GAP or TRANSIENT_SOURCE_ERROR rather
than fabricating completion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.news.outcome import (
    OUTCOME_HORIZONS,
    MarketObservation,
    NewsObservationResult,
)

SOURCE_NAME = "OKX_PUBLIC_CANDLES"
CANDLE_ENDPOINT = "/api/v5/market/candles"
PAGE_LIMIT = 300
MAX_PAGES = 10

HORIZON_BAR = {
    "+5m": "1m",
    "+15m": "1m",
    "+30m": "1m",
    "+1h": "1m",
    "+4h": "5m",
    "+12h": "1h",
    "+24h": "1h",
}
BAR_SECONDS = {"1m": 60, "5m": 300, "1h": 3600, "4h": 14400}


class CandleClient(Protocol):
    async def get_candles(
        self,
        inst_id: str,
        bar: str,
        limit: int = 300,
        *,
        after: int | None = None,
        before: int | None = None,
    ) -> list[list[str]]: ...


@dataclass(frozen=True, slots=True)
class _Candle:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def close_time(self) -> datetime:
        return self.ts

    def with_bar(self, bar_seconds: int) -> ClosedCandle:
        return ClosedCandle(self, self.ts + timedelta(seconds=bar_seconds))


@dataclass(frozen=True, slots=True)
class ClosedCandle:
    candle: _Candle
    closed_at: datetime


def _aware(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    elif isinstance(value, datetime):
        parsed = value
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _horizon_delta(horizon: str) -> timedelta | None:
    known = OUTCOME_HORIZONS.get(horizon)
    if known is not None:
        return known
    text = str(horizon or "").strip().lower().lstrip("+")
    multiplier = {"m": 60, "h": 3600, "d": 86400}
    if len(text) < 2 or text[-1] not in multiplier:
        return None
    try:
        amount = float(text[:-1])
    except ValueError:
        return None
    if amount <= 0:
        return None
    return timedelta(seconds=amount * multiplier[text[-1]])


def _parse_row(row: Any) -> _Candle | None:
    if not isinstance(row, (list, tuple)) or len(row) < 9:
        return None
    if str(row[8]) != "1":
        return None
    try:
        ts = datetime.fromtimestamp(int(row[0]) / 1000, UTC)
        volume = float(row[6] or row[5] or 0.0)
        return _Candle(
            ts=ts,
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=max(0.0, volume),
        )
    except (TypeError, ValueError, IndexError):
        return None


def _sample_std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(max(0.0, variance))


class NewsMarketObservationProvider:
    """Read-only, bounded public-candle provider for outcome reviews."""

    source_name = SOURCE_NAME

    def __init__(
        self,
        client: CandleClient,
        *,
        symbol_mapper: SymbolMapper | None = None,
        page_limit: int = PAGE_LIMIT,
        max_pages: int = MAX_PAGES,
    ) -> None:
        self.client = client
        self.symbol_mapper = symbol_mapper or SymbolMapper()
        self.page_limit = min(max(1, page_limit), 300)
        self.max_pages = max(1, min(max_pages, 20))

    async def close(self) -> None:
        closer = getattr(self.client, "disconnect", None) or getattr(self.client, "aclose", None)
        if closer is not None:
            result = closer()
            if hasattr(result, "__await__"):
                await result

    async def observe(
        self,
        *,
        symbol: str,
        horizon: str,
        due_at: datetime | str,
        news_evidence_id: str,
    ) -> NewsObservationResult:
        del news_evidence_id  # provenance is carried by the review row
        target = _aware(due_at)
        delta = _horizon_delta(horizon)
        base = NewsObservationResult(
            status="INCONCLUSIVE_DATA_GAP",
            source=SOURCE_NAME,
            endpoint=CANDLE_ENDPOINT,
            target_at=target,
            alignment_quality="UNAVAILABLE",
        )
        if target is None or delta is None:
            return base.with_status("INCONCLUSIVE_DATA_GAP", "INVALID_REVIEW_TIME_OR_HORIZON")
        if not symbol or str(symbol).upper() in {"UNIVERSE", "BROAD"}:
            return base.with_status("INCONCLUSIVE_DATA_GAP", "NO_DIRECT_SYMBOL")
        try:
            inst_id = self.symbol_mapper.to_okx(str(symbol))
        except ValueError:
            return base.with_status("INCONCLUSIVE_DATA_GAP", "UNMAPPED_SYMBOL")

        bar = HORIZON_BAR.get(horizon, "1m")
        bar_seconds = BAR_SECONDS.get(bar, 60)
        start = target - delta
        prior_start = start - delta
        max_candles = int((2 * delta.total_seconds()) // bar_seconds) + 20
        try:
            raw_rows = await self._fetch_history(inst_id, bar, prior_start, target, bar_seconds)
        except Exception as exc:
            return base.with_status(
                "TRANSIENT_SOURCE_ERROR", f"SOURCE_ERROR:{type(exc).__name__}:{exc}"[:300]
            )

        future_excluded = 0
        parsed: list[_Candle] = []
        for row in raw_rows:
            candle = _parse_row(row)
            if candle is None:
                continue
            if candle.ts + timedelta(seconds=bar_seconds) > target + timedelta(seconds=1):
                future_excluded += 1
                continue
            parsed.append(candle)
        parsed.sort(key=lambda candle: candle.ts)
        if len(parsed) > max_candles:
            parsed = parsed[-max_candles:]
        if len(parsed) < 2:
            return base.with_status("INCONCLUSIVE_DATA_GAP", "INSUFFICIENT_CLOSED_CANDLES")

        observation_candles = [
            candle for candle in parsed if start <= candle.ts <= target
        ]
        if len(observation_candles) < 2:
            return base.with_status("INCONCLUSIVE_DATA_GAP", "NO_CANDLES_IN_HORIZON_WINDOW")
        observation_candles = observation_candles[-max_candles:]

        first = observation_candles[0]
        last = observation_candles[-1]
        coverage_start = first.ts + timedelta(seconds=bar_seconds)
        coverage_end = last.ts + timedelta(seconds=bar_seconds)
        if coverage_start > start + timedelta(seconds=bar_seconds * 2):
            return base.with_status("INCONCLUSIVE_DATA_GAP", "HORIZON_START_NOT_COVERED")
        if coverage_end < target - timedelta(seconds=bar_seconds * 2):
            return base.with_status("INCONCLUSIVE_DATA_GAP", "HORIZON_END_NOT_COVERED")

        alignment = (
            "EXACT"
            if coverage_start <= start + timedelta(seconds=bar_seconds)
            and target - coverage_end <= timedelta(seconds=bar_seconds)
            else "PARTIAL"
        )

        entry = first.close
        if not entry:
            return base.with_status("INCONCLUSIVE_DATA_GAP", "ZERO_ENTRY_PRICE")
        closes = [candle.close for candle in observation_candles]
        highs = [candle.high for candle in observation_candles]
        lows = [candle.low for candle in observation_candles]
        returns = [
            (closes[index] - closes[index - 1]) / closes[index - 1]
            for index in range(1, len(closes))
            if closes[index - 1]
        ]
        realized_volatility = _sample_std(returns)
        if realized_volatility is not None:
            realized_volatility *= 10000.0

        prior_candles: list[_Candle] = []
        if prior_start < start:
            prior_candles = [candle for candle in parsed if prior_start <= candle.ts < start]
        observation_volume = sum(candle.volume for candle in observation_candles)
        prior_volume = sum(candle.volume for candle in prior_candles)
        rvol = None
        unavailable: list[str] = []
        if prior_volume > 0 and observation_volume > 0:
            rvol = observation_volume / prior_volume
        else:
            unavailable.append("RVOL_UNAVAILABLE_NO_PRIOR_VOLUME")
        unavailable.extend(
            [
                "SPREAD_HISTORY_UNAVAILABLE",
                "OI_HISTORY_UNAVAILABLE",
                "FUNDING_HISTORY_UNAVAILABLE",
            ]
        )
        if future_excluded:
            unavailable.append(f"FUTURE_CANDLES_EXCLUDED={future_excluded}")
        observation = MarketObservation(
            price_return=(last.close - entry) / entry,
            mfe=(max(highs) - entry) / entry,
            mae=(min(lows) - entry) / entry,
            realized_volatility=realized_volatility,
            rvol=rvol,
            spread_change=None,
            oi_change=None,
            funding_change=None,
            payload={
                "counterfactual": False,
                "future_candles_excluded": future_excluded,
                "prior_volume": prior_volume,
                "observation_volume": observation_volume,
            },
        )
        return NewsObservationResult(
            status="COMPLETED",
            observation=observation,
            source=SOURCE_NAME,
            endpoint=CANDLE_ENDPOINT,
            target_at=target,
            alignment_quality=alignment,
            unavailable_reasons=sorted(set(unavailable)),
            observed_start_at=coverage_start,
            observed_end_at=coverage_end,
            bars_used=len(observation_candles),
        )

    async def _fetch_history(
        self,
        inst_id: str,
        bar: str,
        start: datetime,
        end: datetime,
        bar_seconds: int,
    ) -> list[list[str]]:
        """Fetch public candles in bounded pages, walking backwards from end."""
        cursor_ms = int(end.timestamp() * 1000) + bar_seconds * 1000
        rows: dict[int, list[str]] = {}
        previous_earliest = cursor_ms
        for _ in range(self.max_pages):
            page = await self.client.get_candles(
                inst_id, bar, self.page_limit, after=cursor_ms
            )
            if not page:
                break
            parsed_ts: list[int] = []
            for row in page:
                if isinstance(row, (list, tuple)) and len(row) >= 1:
                    try:
                        parsed_ts.append(int(row[0]))
                    except (TypeError, ValueError):
                        continue
                    rows.setdefault(int(row[0]), list(row))
            if not parsed_ts:
                break
            earliest = min(parsed_ts)
            if earliest <= int(start.timestamp() * 1000) - bar_seconds * 1000:
                break
            if earliest >= previous_earliest:
                break
            previous_earliest = earliest
            cursor_ms = earliest
        return [rows[key] for key in sorted(rows)]
