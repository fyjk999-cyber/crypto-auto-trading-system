"""Adapter behaviour against the real service envelopes.

The payload shapes below are taken from the live service at http://127.0.0.1:8770.
They pin two contract facts that a naive row-only reader gets wrong:

  * /v1/health is a flat service document -- it has no ``data`` and no ``coverage``.
  * /v1/regime/<SYMBOL> returns ``data`` as a single document, not a row series.

They also pin that the consumer never learns storage internals.
"""

from __future__ import annotations

import json

from crypto_trader.shared_history import COMPLETE, DATA_UNAVAILABLE, SharedHistoryEvidence
from crypto_trader.shared_history.adapter import REASON_FUTURE_DATA
from tests.shared_history.conftest import candle_payload

# Trimmed but faithful copy of a real /v1/health response.
HEALTH = {
    "service_status": "OK",
    "parquet_status": "OK",
    "data_root": "/Users/huhongjie/Library/Application Support/SharedMarketHistory",
    "universe_size": 478,
    "symbols_with_history": 478,
    "writer_count": 1,
    "external_writer_active": True,
    "implementation_sha": "4fd7e3419dc4022f1389902c433283d28a876787",
    "full_market": "PASS",
    "full_market_backfill_complete": "YES",
    "universe_processed_count": 478,
    "unresolved_symbol_count": 0,
    "symbols_terminal_complete": 62,
    "symbols_terminal_partial": 416,
    "symbols_terminal_data_unavailable": 0,
    "pending_backfill_tasks": 0,
    "health_snapshot_stale": False,
    "maintenance_phase": "INCREMENTAL_VERIFY",
    "incremental_updater": "WAITING",
    "latest_1m_freshness_seconds": 1849.108,
    "soak": "WAITING_FOR_GATES",
    "llm_contract": {"DEEPSEEK_CALLS": 0, "GLM_CALLS": 0},
    "historical_schema_version": "smh.parquet.v1",
    "feature_set_version": "smh.feature_set.v1",
    "regime_schema_version": "smh.regime.v1",
}

# Trimmed but faithful copy of a real /v1/regime/<SYMBOL> response.
REGIME = {
    "symbol": "BTCUSDT",
    "source": "okx-derived",
    "timeframe": "5m+15m+1h+4h+1d",
    "first_timestamp": None,
    "last_timestamp": 1790641200000,
    "row_count": 5,
    "freshness": "FRESH",
    "coverage": "COMPLETE",
    "max_source_timestamp": 1790641200000,
    "regime_schema_version": "smh.regime.v1",
    "historical_schema_version": "smh.parquet.v1",
    "schema_version": "smh.api.v1",
    "data": {
        "symbol": "BTCUSDT",
        "coverage": "COMPLETE",
        "last_timestamp": 1790641200000,
        "max_source_timestamp": 1790641200000,
        "regime_5m": "RANGE",
        "regime_1h": "TREND_UP",
    },
}

# Trimmed but faithful copy of a real /v1/universe response (no top-level coverage).
UNIVERSE = {
    "source": "okx",
    "schema_version": "smh.parquet.v1",
    "as_of": 1790640770683,
    "count": 478,
    "live_usdt_swap_count": 478,
    "symbols": [
        {
            "inst_id": "0G-USDT-SWAP",
            "historical_coverage": "DATA_UNAVAILABLE",
            "last_historical_timestamp": None,
        },
        {
            "inst_id": "BTC-USDT-SWAP",
            "historical_coverage": "COMPLETE",
            "last_historical_timestamp": 1790641200000,
        },
    ],
}


def _evidence(api_url) -> SharedHistoryEvidence:
    return SharedHistoryEvidence(enabled=True, base_url=api_url)


def test_health_is_a_document_not_a_row_series(fake_api, api_url):
    fake_api.routes["/v1/health"] = (200, HEALTH)
    result = _evidence(api_url).health()
    assert result.available is True
    assert result.status == COMPLETE
    assert result.rows == ()
    assert result.reason is None


def test_health_surfaces_required_observability(fake_api, api_url):
    fake_api.routes["/v1/health"] = (200, HEALTH)
    extra = _evidence(api_url).health().extra
    assert extra["writer_count"] == 1
    assert extra["implementation_sha"] == "4fd7e3419dc4022f1389902c433283d28a876787"
    assert extra["llm_contract"] == {"DEEPSEEK_CALLS": 0, "GLM_CALLS": 0}
    assert extra["universe_size"] == 478
    assert extra["full_market"] == "PASS"
    assert extra["feature_set_version"] == "smh.feature_set.v1"


def test_health_never_leaks_storage_internals(fake_api, api_url):
    """The service exposes data_root; the LowRisk evidence layer must not carry it."""
    fake_api.routes["/v1/health"] = (200, HEALTH)
    extra = _evidence(api_url).health().extra
    assert "data_root" not in extra
    rendered = json.dumps(extra)
    assert "/Users/" not in rendered
    assert "/Volumes/" not in rendered
    assert "My PSSD" not in rendered


def test_degraded_service_status_is_surfaced_not_hidden(fake_api, api_url):
    fake_api.routes["/v1/health"] = (200, {**HEALTH, "service_status": "DEGRADED"})
    extra = _evidence(api_url).health().extra
    assert extra["service_status"] == "DEGRADED"


def test_regime_document_payload_is_available(fake_api, api_url):
    fake_api.routes["/v1/regime/BTCUSDT"] = (200, REGIME)
    result = _evidence(api_url).regime("BTCUSDT")
    assert result.available is True
    assert result.status == COMPLETE
    # row_count always describes this evidence's own rows (one document here); the
    # service's declared count of covered timeframes is preserved in provenance.
    assert result.row_count == 1
    assert result.extra["row_count"] == 5
    assert result.last_timestamp == 1790641200000
    assert result.source == "okx-derived"
    assert result.schema_version == "smh.regime.v1"
    assert result.extra["api_schema_version"] == "smh.api.v1"
    assert result.extra["historical_schema_version"] == "smh.parquet.v1"
    assert result.freshness == {"status": "FRESH"}


def test_regime_future_envelope_timestamp_is_rejected(fake_api, api_url):
    """A document has no row timestamps, so the envelope timestamp must be checked."""
    fake_api.routes["/v1/regime/BTCUSDT"] = (200, REGIME)
    result = _evidence(api_url).regime("BTCUSDT", decision_as_of=1790640000000)
    assert result.status == DATA_UNAVAILABLE
    assert result.reason == REASON_FUTURE_DATA
    assert result.rows == ()


def test_universe_listing_is_complete_not_partial(fake_api, api_url):
    fake_api.routes["/v1/universe"] = (200, UNIVERSE)
    result = _evidence(api_url).universe()
    assert result.available is True
    assert result.status == COMPLETE
    assert result.row_count == 2
    assert result.extra["live_usdt_swap_count"] == 478


def test_service_document_semantics_do_not_leak_into_row_series(fake_api, api_url):
    """An empty candle series is still DATA_UNAVAILABLE, never COMPLETE."""
    fake_api.routes["/v1/latest"] = (200, candle_payload([], coverage="DATA_UNAVAILABLE"))
    result = _evidence(api_url).latest_candles("BTCUSDT", "1h")
    assert result.status == DATA_UNAVAILABLE
    assert result.available is False
