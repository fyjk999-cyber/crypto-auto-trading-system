"""Market Intelligence & Active Research V1 — Gate 1 (market truth) tests.

Every test asserts a FAIL-CLOSED, factual behaviour: provider failure is never
rendered as a valid value, timestamps are validated rather than clamped, and
requested candle counts are never mistaken for usable history.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.factors import (
    OrderbookImbalanceFactor,
    SymbolFacts,
)
from crypto_trader.market_data.opportunity.oi import (
    DEFAULT_OI_WINDOWS,
    OiSample,
    OiTimeSeries,
)
from crypto_trader.market_data.opportunity.service import OpportunityScannerService
from crypto_trader.market_data.opportunity.universe import Instrument
from crypto_trader.market_data.quality import (
    FUTURE_TIMESTAMP,
    MALFORMED,
    MISSING,
    NON_FINITE,
    REQUEST_FAILED,
    STALE,
    VALID,
    build_candle_truth,
    numeric_fact,
    timestamp_fact,
)


# --------------------------------------------------------------------- quality
def test_numeric_integrity_rejects_nan_and_infinity():
    for bad in (float("nan"), float("inf"), float("-inf"), "not-a-number", "NaN"):
        fact = numeric_fact(bad, source="test")
        assert fact.quality in {NON_FINITE, MALFORMED}
        assert fact.value is None
        assert fact.usable is False
    assert numeric_fact("0", source="test").quality == VALID
    assert numeric_fact("0", source="test").value == 0.0
    assert numeric_fact("-5", source="test", allow_negative=False).quality == MALFORMED
    assert numeric_fact(None, source="test").quality == MISSING


def test_missing_timestamp_is_missing_not_fresh():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    observed, quality, reason = timestamp_fact(None, now=now, source="t")
    assert observed is None
    assert quality == MISSING
    assert reason


def test_future_timestamp_is_not_clamped_to_zero_age():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    future_ms = int((now + timedelta(minutes=10)).timestamp() * 1000)
    observed, quality, _ = timestamp_fact(future_ms, now=now, source="t")
    assert quality == FUTURE_TIMESTAMP
    assert observed is not None  # the raw truth is retained, not rewritten
    assert observed > now


def test_stale_and_valid_timestamps_are_distinguished():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    fresh_ms = int((now - timedelta(seconds=5)).timestamp() * 1000)
    stale_ms = int((now - timedelta(seconds=600)).timestamp() * 1000)
    assert timestamp_fact(fresh_ms, now=now, source="t", max_age_seconds=120)[1] == VALID
    assert timestamp_fact(stale_ms, now=now, source="t", max_age_seconds=120)[1] == STALE
    assert timestamp_fact("garbage", now=now, source="t")[1] == MALFORMED


# ---------------------------------------------------------------------- candles
def _candle_rows(count: int, *, step_ms: int = 60_000, start_ms: int = 1_700_000_000_000):
    rows = []
    for index in range(count):
        ts = start_ms + index * step_ms
        rows.append([str(ts), "1", "2", "0.5", "1.5", "10", "0", "0", "1"])
    return rows


def test_requested_120_received_20_is_not_prewarm_ready():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    rows = _candle_rows(20, start_ms=int((now - timedelta(minutes=20)).timestamp() * 1000))
    candles, truth = build_candle_truth(
        requested_count=120, rows=rows, bar_seconds=60.0, now=now
    )
    assert truth.requested_count == 120
    assert truth.received_count == 20
    assert truth.unique_closed_count == 20
    assert truth.contiguous_tail_count == 20
    assert truth.as_dict()["coverage_ratio"] == round(20 / 120, 4)
    # 20 real candles must never be presented as "120 candles available"
    assert truth.as_dict()["candles_available_is_requested_count"] is False
    assert len(candles) == 20


def test_open_candles_excluded_and_duplicates_deduplicated():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    base = int((now - timedelta(minutes=10)).timestamp() * 1000)
    rows = _candle_rows(5, start_ms=base)
    rows.append(list(rows[2]))  # duplicate open candle
    rows.append([str(base + 5 * 60_000), "1", "2", "0.5", "1.5", "10", "0", "0", "0"])  # open
    candles, truth = build_candle_truth(
        requested_count=120, rows=rows, bar_seconds=60.0, now=now
    )
    assert truth.received_count == 7
    assert truth.unique_closed_count == 5
    assert len(candles) == 5
    assert len({c[0] for c in candles}) == 5


def test_gaps_reduce_contiguous_tail_and_mark_partial():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    base = int((now - timedelta(minutes=20)).timestamp() * 1000)
    rows = _candle_rows(5, start_ms=base)
    # add a candle 10 minutes after the last -> a real gap
    rows.append([str(base + 15 * 60_000), "1", "2", "0.5", "1.5", "10", "0", "0", "1"])
    _, truth = build_candle_truth(requested_count=120, rows=rows, bar_seconds=60.0, now=now)
    assert truth.gap_count == 1
    assert truth.contiguous_tail_count == 1
    assert truth.quality == "PARTIAL"
    assert truth.analysis_ready is True


# ------------------------------------------------------------------------ OI
def test_irregular_oi_sampling_does_not_fake_fixed_window_change():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    series = OiTimeSeries()
    # three rapid samples ~ the "last N calls" trap: huge jump but only seconds apart
    series.record(OiSample("BTCUSDT", 100.0, now - timedelta(seconds=30)))
    series.record(OiSample("BTCUSDT", 130.0, now - timedelta(seconds=20)))
    series.record(OiSample("BTCUSDT", 160.0, now - timedelta(seconds=10)))
    fact = series.window_change("BTCUSDT", now=now, window="15m")
    assert fact.quality == "UNSUPPORTED"
    assert fact.value is None
    assert "OI_CHANGE_UNAVAILABLE" in (fact.reason or "")

    # a proper T-15m baseline yields a factual change
    series.record(OiSample("BTCUSDT", 100.0, now - timedelta(seconds=900)))
    series.record(OiSample("BTCUSDT", 120.0, now))
    fact = series.window_change("BTCUSDT", now=now, window="15m")
    assert fact.quality == VALID
    assert fact.value == pytest.approx(20.0)


def test_oi_windows_are_data_driven_and_bounded():
    labels = [w.label for w in DEFAULT_OI_WINDOWS]
    assert labels == ["5m", "15m", "1h"]
    series = OiTimeSeries()
    assert series.window_change("X", now=datetime.now(UTC)).quality == "UNSUPPORTED"
    assert series.window_change("X", now=datetime.now(UTC), window="9h").quality == "UNSUPPORTED"


# ------------------------------------------------------------------ orderbook
def test_top_of_book_sizes_reach_the_imbalance_factor():
    factor = OrderbookImbalanceFactor()
    facts = SymbolFacts(
        symbol="ETHUSDT",
        bid=100.0,
        ask=100.1,
        bid_qty=30.0,
        ask_qty=5.0,
    )
    observation = factor.evaluate(facts)
    assert observation.status == "TRIGGERED"
    assert observation.facts["imbalance_scope"] == "TOP_OF_BOOK"
    assert observation.facts["best_bid_size"] == 30.0
    assert observation.facts["best_ask_size"] == 5.0
    assert observation.facts["bid_ask_qty_ratio"] == pytest.approx(6.0)

    missing = factor.evaluate(SymbolFacts(symbol="ETHUSDT"))
    assert missing.status == "UNAVAILABLE"
    assert missing.unavailable_reason == "NO_TOP_OF_BOOK_QUANTITIES"


# ------------------------------------------------------- funding contract (fake)
class _FakeUniverse:
    class _Snap:
        instruments = {
            "BTCUSDT": Instrument(
                symbol="BTCUSDT",
                inst_id="BTC-USDT-SWAP",
                state="live",
                settle_ccy="USDT",
                ct_val="0.01",
                list_time=None,
                raw={},
            )
        }
        size = 1

    async def refresh(self, force=False):
        return self._Snap()


class _FakeClient:
    def __init__(self, *, funding_rows, funding_error=None, ticker_ts=None):
        self._funding_rows = funding_rows
        self._funding_error = funding_error
        self._ticker_ts = ticker_ts
        self.funding_calls = 0
        self.fallback_calls = 0

    async def get_tickers(self, inst_type):
        ts = self._ticker_ts or str(int(datetime.now(UTC).timestamp() * 1000))
        return [
            {
                "instId": "BTC-USDT-SWAP",
                "last": "50000",
                "open24h": "49000",
                "bidPx": "49999",
                "askPx": "50001",
                "bidSz": "12",
                "askSz": "4",
                "vol24h": "1000",
                "volCcy24h": "50",
                "ts": ts,
            }
        ]

    async def get_open_interests(self, inst_type):
        return [{"instId": "BTC-USDT-SWAP", "oi": "70000"}]

    async def get_funding_rates(self, inst_type):
        self.funding_calls += 1
        if self._funding_error is not None:
            raise self._funding_error
        return self._funding_rows

    async def get_funding_rate_fallback(self, inst_id):
        self.fallback_calls += 1
        raise RuntimeError("no fallback available")

    async def get_candles(self, inst_id, bar, limit):
        return _candle_rows(5)


def _scan(client):
    board = OpportunityBoard()
    service = OpportunityScannerService(
        universe=_FakeUniverse(), okx_client=client, board=board, candle_limit=120
    )
    summary = asyncio.run(service.scan_once())
    return board, summary


def test_funding_provider_failure_is_not_zero_funding():
    client = _FakeClient(funding_rows=[], funding_error=RuntimeError("okx 500"))
    board, summary = _scan(client)
    snapshot = board.current_snapshot()
    row = snapshot.observable_rows[0]
    assert row["funding_rate"] is None
    assert row["funding_quality"] == REQUEST_FAILED
    assert snapshot.data_quality_summary["batch"]["funding"] == REQUEST_FAILED
    assert summary["candidates"] is not None
    assert row["funding_rate"] != 0.0


def test_valid_zero_funding_stays_valid_zero():
    client = _FakeClient(
        funding_rows=[{"instId": "BTC-USDT-SWAP", "fundingRate": "0"}]
    )
    board, _ = _scan(client)
    row = board.current_snapshot().observable_rows[0]
    assert row["funding_rate"] == 0.0
    assert row["funding_quality"] == VALID


def test_missing_instrument_in_funding_batch_is_missing_not_zero():
    client = _FakeClient(funding_rows=[{"instId": "ETH-USDT-SWAP", "fundingRate": "0.001"}])
    board, _ = _scan(client)
    row = board.current_snapshot().observable_rows[0]
    assert row["funding_rate"] is None
    assert row["funding_quality"] == MISSING
    # the bounded per-instrument fallback was attempted (and failed safely)
    assert client.fallback_calls == 1


def test_future_ticker_timestamp_is_refused_as_freshness_proof():
    future = str(int((datetime.now(UTC) + timedelta(minutes=30)).timestamp() * 1000))
    client = _FakeClient(funding_rows=[], funding_error=RuntimeError("x"), ticker_ts=future)
    board, summary = _scan(client)
    row = board.current_snapshot().observable_rows[0]
    assert row["ticker_quality"] == FUTURE_TIMESTAMP
    assert summary["eligible"] == 0  # no honest freshness proof -> not eligible


def test_turnover_is_labelled_estimated_in_snapshot_facts():
    client = _FakeClient(funding_rows=[{"instId": "BTC-USDT-SWAP", "fundingRate": "0"}])
    board, _ = _scan(client)
    snapshot = board.current_snapshot()
    row = snapshot.observable_rows[0]
    assert row["vol_usd_24h"] == pytest.approx(2_500_000.0)
    assert snapshot.broad_market_summary["top_abs_movers_24h"][0]["turnover_quality"] == "ESTIMATED"
    assert "estimated_quote_turnover_24h" in snapshot.data_quality_summary["turnover_semantics"]
