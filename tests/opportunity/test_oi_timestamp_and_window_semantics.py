"""OI factual timing + window-quality semantics.

Covers the closure requirements:

* OI samples keep the PROVIDER observation timestamp (never the scan start time)
* identical provider timestamps deduplicate (no fake two-timepoint acceleration)
* insufficient history / missing baseline / zero baseline are MISSING (evidence
  limitations), NOT UNSUPPORTED (capability absence)
* an unimplemented window remains UNSUPPORTED
* a stale latest sample is STALE
* a factual zero OI stays a VALID fact and never becomes a percentage denominator
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.factors import (
    OpenInterestFactor,
    SymbolFacts,
)
from crypto_trader.market_data.opportunity.oi import OiSample, OiTimeSeries
from crypto_trader.market_data.opportunity.scanner import FactorScanner
from crypto_trader.market_data.opportunity.service import (
    OpportunityScannerService,
    ScannerConfig,
)
from crypto_trader.market_data.quality import MISSING, STALE, UNSUPPORTED, VALID
from tests.opportunity.test_oi_semantics_and_exploration import FakeUniverse, OiClient

NOW = datetime(2026, 1, 1, 12, 15, 10, tzinfo=UTC)
PROVIDER_TS = datetime(2026, 1, 1, 12, 15, 2, tzinfo=UTC)


def _scan_with_service(client, **config_kwargs):
    from crypto_trader.market_data.cache import MarketDataCache

    board = OpportunityBoard()
    service = OpportunityScannerService(
        universe=FakeUniverse(),
        okx_client=client,
        board=board,
        scanner=FactorScanner(factors=()),
        config=ScannerConfig(candle_limit=120, **config_kwargs),
        cache=MarketDataCache(),
    )
    summary = asyncio.run(service.scan_once())
    return board, summary, service


# ------------------------------------------------------- provider timestamp
def test_oi_sample_keeps_provider_timestamp_not_scan_time():
    # a real, fresh provider timestamp (the ticker freshness bound applies to
    # OI too, so the provider ts must be recent)
    provider_ms = int((datetime.now(UTC) - timedelta(seconds=2)).timestamp() * 1000)
    provider_ts = datetime.fromtimestamp(provider_ms / 1000, tz=UTC)  # ms precision
    client = OiClient(oi_ts=str(provider_ms))
    board, summary, service = _scan_with_service(client)

    sample = service.oi_series.export_state()["AAAUSDT"][0]
    stored = datetime.fromisoformat(sample["observed_at"])
    snapshot = board.current_snapshot()
    assert stored == provider_ts                      # provider time preserved
    assert stored != snapshot.started_at              # NOT the scan start time
    assert "open-interest" in sample["source"]
    assert "open-interests" not in sample["source"]


def test_identical_provider_timestamps_deduplicate():
    series = OiTimeSeries()
    assert series.record(OiSample("BTCUSDT", 100.0, PROVIDER_TS)) is True
    assert series.record(OiSample("BTCUSDT", 100.0, PROVIDER_TS)) is True
    # a re-published identical instant replaces, it does not append
    assert series.sample_count("BTCUSDT") == 1
    fact = series.window_change("BTCUSDT", now=PROVIDER_TS + timedelta(seconds=5))
    assert fact.quality == MISSING
    assert "INSUFFICIENT_HISTORY" in (fact.reason or "")


def test_invalid_provider_timestamp_does_not_create_a_sample():
    client = OiClient(oi_ts=str(int((datetime.now(UTC) + timedelta(hours=1)).timestamp() * 1000)))
    board, _, service = _scan_with_service(client)
    # future provider timestamp -> not a VALID fact -> no OI sample recorded
    assert service.oi_series.export_state() == {}


# ------------------------------------------------------------- window quality
def test_insufficient_history_is_missing_not_unsupported():
    series = OiTimeSeries()
    series.record(OiSample("BTCUSDT", 100.0, NOW - timedelta(seconds=60)))
    fact = series.window_change("BTCUSDT", now=NOW, window="15m")
    assert fact.quality == MISSING
    assert fact.quality != UNSUPPORTED
    assert "INSUFFICIENT_HISTORY" in (fact.reason or "")


def test_missing_fifteen_minute_baseline_is_missing():
    series = OiTimeSeries()
    series.record(OiSample("BTCUSDT", 100.0, NOW - timedelta(seconds=60)))
    series.record(OiSample("BTCUSDT", 105.0, NOW))
    fact = series.window_change("BTCUSDT", now=NOW, window="15m")
    assert fact.quality == MISSING
    assert "NO_BASELINE_IN_WINDOW" in (fact.reason or "")


def test_stale_latest_sample_is_stale():
    series = OiTimeSeries()
    series.record(OiSample("BTCUSDT", 100.0, NOW - timedelta(seconds=3600)))
    series.record(OiSample("BTCUSDT", 105.0, NOW - timedelta(seconds=1800)))
    fact = series.window_change("BTCUSDT", now=NOW, window="15m")
    assert fact.quality == STALE
    assert "STALE" in (fact.reason or "")


def test_unknown_window_remains_unsupported():
    series = OiTimeSeries()
    fact = series.window_change("BTCUSDT", now=NOW, window="7h")
    assert fact.quality == UNSUPPORTED
    assert "unknown OI window" in (fact.reason or "")


def test_valid_window_change_uses_factual_timestamps():
    series = OiTimeSeries()
    series.record(OiSample("BTCUSDT", 100.0, NOW - timedelta(seconds=900)))
    series.record(OiSample("BTCUSDT", 120.0, NOW))
    fact = series.window_change("BTCUSDT", now=NOW, window="15m")
    assert fact.quality == VALID
    assert fact.value is not None and abs(fact.value - 20.0) < 1e-9
    assert "baseline_age=900s" in (fact.reason or "")


# ------------------------------------------------------------- zero semantics
def test_factual_zero_oi_is_stored_and_never_a_denominator():
    series = OiTimeSeries()
    assert series.record(OiSample("BTCUSDT", 0.0, NOW - timedelta(seconds=900))) is True
    assert series.record(OiSample("BTCUSDT", 10.0, NOW)) is True
    assert series.sample_count("BTCUSDT") == 2

    fact = series.window_change("BTCUSDT", now=NOW, window="15m")
    assert fact.quality == MISSING
    assert fact.value is None
    assert "ZERO_BASELINE" in (fact.reason or "")

    # the zero itself stays a VALID fact in the series
    assert series.export_state()["BTCUSDT"][0]["open_interest"] == 0.0


def test_negative_and_non_finite_samples_are_rejected():
    series = OiTimeSeries()
    assert series.record(OiSample("BTCUSDT", -1.0, NOW)) is False
    assert series.record(OiSample("BTCUSDT", float("nan"), NOW)) is False
    assert series.record(OiSample("BTCUSDT", float("inf"), NOW)) is False
    assert series.sample_count("BTCUSDT") == 0


def test_zero_oi_does_not_trigger_the_oi_factor_without_change():
    """A valid zero fact alone must not fabricate an acceleration signal."""
    factor = OpenInterestFactor()
    observation = factor.evaluate(
        SymbolFacts(
            symbol="BTCUSDT",
            open_interest=0.0,
            oi_change_pct=None,
            oi_samples=1,
            oi_change_quality=MISSING,
            oi_change_reason="OI_CHANGE_UNAVAILABLE:ZERO_BASELINE",
        )
    )
    assert observation.status == "UNAVAILABLE"
    assert "OI_CHANGE_UNAVAILABLE" in (observation.unavailable_reason or "")
