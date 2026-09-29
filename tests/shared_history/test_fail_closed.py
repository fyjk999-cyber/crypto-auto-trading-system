"""Failure semantics.

Every failure must surface as an explicit DATA_UNAVAILABLE result with no rows.
The adapter must never guess, invent, zero-fill, or silently substitute stale or
synthetic values.

Invariants under test:
    UNAVAILABLE != ZERO
    STALE       != FRESH
    PARTIAL_HISTORY != COMPLETE
"""

from __future__ import annotations

from crypto_trader.shared_history import (
    COMPLETE,
    DATA_UNAVAILABLE,
    PARTIAL_HISTORY,
    STALE,
    SharedHistoryEvidence,
)
from crypto_trader.shared_history.adapter import (
    REASON_DISABLED,
    REASON_EMPTY,
    REASON_HTTP_ERROR,
    REASON_UNREACHABLE,
)
from tests.shared_history.conftest import candle_payload, candle_rows

START = 1_700_000_000_000


def _evidence(api_url, **kwargs) -> SharedHistoryEvidence:
    return SharedHistoryEvidence(enabled=True, base_url=api_url, **kwargs)


def test_disabled_by_default_performs_no_io(fake_api, api_url):
    evidence = SharedHistoryEvidence()  # enabled=False is the production default
    result = evidence.latest_candles("BTCUSDT", "1h")
    assert result.available is False
    assert result.status == DATA_UNAVAILABLE
    assert result.reason == REASON_DISABLED
    assert result.row_count == 0
    assert result.rows == ()
    assert fake_api.count() == 0, "a disabled adapter must not touch the network"


def test_unreachable_service_yields_data_unavailable():
    evidence = SharedHistoryEvidence(enabled=True, base_url="http://127.0.0.1:1", timeout=1.0)
    result = evidence.latest_candles("BTCUSDT", "1h")
    assert result.status == DATA_UNAVAILABLE
    assert result.available is False
    assert result.reason == REASON_UNREACHABLE
    assert result.rows == ()


def test_http_error_yields_data_unavailable(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (500, {"error": "internal_error"})
    result = _evidence(api_url).latest_candles("BTCUSDT", "1h")
    assert result.status == DATA_UNAVAILABLE
    assert result.available is False
    assert result.reason == REASON_HTTP_ERROR
    assert result.rows == ()


def test_malformed_payload_yields_data_unavailable(fake_api, api_url):
    fake_api.raw_body = "{ not json"
    result = _evidence(api_url).latest_candles("BTCUSDT", "1h")
    assert result.status == DATA_UNAVAILABLE
    assert result.available is False
    assert result.rows == ()


def test_empty_dataset_is_unavailable_not_zero(fake_api, api_url):
    """An absent dataset must not become a row of zeros."""
    fake_api.routes["/v1/latest"] = (200, candle_payload([], coverage="DATA_UNAVAILABLE"))
    result = _evidence(api_url).latest_candles("BTCUSDT", "1h")
    assert result.status == DATA_UNAVAILABLE
    assert result.available is False
    assert result.reason == REASON_EMPTY
    assert result.row_count == 0
    assert result.rows == ()
    # Nothing was fabricated: there is no candle carrying a zero price.
    assert not any(row.get("close") == 0 for row in result.rows)


def test_unavailable_is_not_zero(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (200, candle_payload([], coverage="DATA_UNAVAILABLE"))
    evidence = _evidence(api_url)
    result = evidence.latest_candles("BTCUSDT", "1h")
    assert result.available is False
    assert result.row_count == 0
    assert result.first_timestamp is None
    assert result.last_timestamp is None


def test_partial_history_is_preserved_not_upgraded(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (
        200,
        candle_payload(candle_rows(START, 3), coverage=PARTIAL_HISTORY),
    )
    result = _evidence(api_url).latest_candles("BTCUSDT", "1h")
    assert result.status == PARTIAL_HISTORY
    assert result.is_partial is True
    assert result.is_complete is False


def test_complete_history_is_reported_complete(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (200, candle_payload(candle_rows(START, 3)))
    result = _evidence(api_url).latest_candles("BTCUSDT", "1h")
    assert result.status == COMPLETE
    assert result.is_complete is True
    assert result.row_count == 3


def test_absent_coverage_is_never_reported_complete(fake_api, api_url):
    """Conservative default: unknown coverage is partial, never COMPLETE."""
    payload = candle_payload(candle_rows(START, 2))
    del payload["coverage"]
    fake_api.routes["/v1/latest"] = (200, payload)
    result = _evidence(api_url).latest_candles("BTCUSDT", "1h")
    assert result.status == PARTIAL_HISTORY
    assert result.status != COMPLETE


def test_stale_is_not_reported_fresh(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (
        200,
        candle_payload(candle_rows(START, 2), coverage="STALE"),
    )
    result = _evidence(api_url).latest_candles("BTCUSDT", "1h")
    assert result.status == STALE
    assert result.status != COMPLETE


def test_health_and_universe_fail_closed(fake_api, api_url):
    fake_api.fail_all = 503
    evidence = _evidence(api_url)
    assert evidence.health().status == DATA_UNAVAILABLE
    assert evidence.universe().status == DATA_UNAVAILABLE


def test_counters_record_unavailability(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (500, {"error": "internal_error"})
    evidence = _evidence(api_url)
    evidence.latest_candles("BTCUSDT", "1h")
    evidence.latest_candles("ETHUSDT", "1h")
    counters = evidence.counters()
    assert counters["unavailable_count"] == 2
    assert counters["read_count"] == 2


def test_disabled_adapter_counts_but_never_reads():
    evidence = SharedHistoryEvidence(enabled=False)
    evidence.latest_candles("BTCUSDT", "1h")
    assert evidence.counters()["read_count"] == 0
    assert evidence.counters()["unavailable_count"] == 1
