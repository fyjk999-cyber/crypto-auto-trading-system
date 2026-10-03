"""Temporal / as-of integrity.

A decision made at ``decision_as_of`` must never see a fact that postdates it.
Required invariant: MAX_DATA_TIMESTAMP <= decision_as_of,
and SHARED_HISTORY_FUTURE_ROWS_VISIBLE == 0.
"""

from __future__ import annotations

from crypto_trader.shared_history import DATA_UNAVAILABLE, SharedHistoryEvidence
from crypto_trader.shared_history.adapter import REASON_FUTURE_DATA
from tests.shared_history.conftest import candle_payload, candle_rows

START = 1_700_000_000_000
HOUR = 3_600_000


def _evidence(api_url) -> SharedHistoryEvidence:
    return SharedHistoryEvidence(enabled=True, base_url=api_url)


def test_future_rows_are_rejected_whole(fake_api, api_url):
    """A payload containing any post-decision fact is rejected, not trimmed."""
    rows = candle_rows(START, 5)  # covers START .. START+4h
    fake_api.routes["/v1/latest"] = (200, candle_payload(rows))
    decision_as_of = START + 2 * HOUR  # 3 rows are in the future

    result = _evidence(api_url).latest_candles("BTCUSDT", "1h", decision_as_of=decision_as_of)

    assert result.status == DATA_UNAVAILABLE
    assert result.available is False
    assert result.reason == REASON_FUTURE_DATA
    assert result.rows == ()
    assert result.row_count == 0


def test_future_row_visibility_counter_is_zero_for_valid_reads(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (200, candle_payload(candle_rows(START, 3)))
    evidence = _evidence(api_url)
    result = evidence.latest_candles("BTCUSDT", "1h", decision_as_of=START + 10 * HOUR)
    assert result.available is True
    assert evidence.counters()["future_data_rejections"] == 0
    assert result.last_timestamp <= START + 10 * HOUR


def test_max_data_timestamp_never_exceeds_decision_as_of(fake_api, api_url):
    rows = candle_rows(START, 6)
    fake_api.routes["/v1/latest"] = (200, candle_payload(rows))
    decision_as_of = START + 4 * HOUR

    result = _evidence(api_url).latest_candles("BTCUSDT", "1h", decision_as_of=decision_as_of)

    # Either the payload is rejected, or everything visible is at or before as_of.
    if result.available:
        assert result.last_timestamp is not None
        assert result.last_timestamp <= decision_as_of
    else:
        assert result.status == DATA_UNAVAILABLE


def test_historical_window_end_is_clamped_to_decision_as_of(fake_api, api_url):
    fake_api.routes["/v1/candles"] = (200, candle_payload(candle_rows(START, 2)))
    decision_as_of = START + 2 * HOUR

    _evidence(api_url).historical_candles(
        "BTCUSDT", "1h", start=START, end=START + 99 * HOUR, decision_as_of=decision_as_of
    )

    query = fake_api.requests[0]["query"]
    assert int(query["end"][0]) <= decision_as_of
    assert int(query["as_of"][0]) == decision_as_of


def test_window_end_defaults_to_decision_as_of(fake_api, api_url):
    fake_api.routes["/v1/candles"] = (200, candle_payload(candle_rows(START, 2)))
    decision_as_of = START + 3 * HOUR

    _evidence(api_url).historical_candles(
        "BTCUSDT", "1h", start=START, decision_as_of=decision_as_of
    )

    query = fake_api.requests[0]["query"]
    assert int(query["end"][0]) == decision_as_of


def test_as_of_is_forwarded_to_the_service(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (200, candle_payload(candle_rows(START, 1)))
    decision_as_of = START + HOUR
    _evidence(api_url).latest_candles("BTCUSDT", "1h", decision_as_of=decision_as_of)
    assert int(fake_api.requests[0]["query"]["as_of"][0]) == decision_as_of


def test_live_read_without_as_of_sends_no_as_of_parameter(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (200, candle_payload(candle_rows(START, 1)))
    _evidence(api_url).latest_candles("BTCUSDT", "1h")
    assert "as_of" not in fake_api.requests[0]["query"]


def test_funding_and_open_interest_honour_as_of(fake_api, api_url):
    decision_as_of = START + HOUR
    fake_api.routes["/v1/funding/BTCUSDT"] = (
        200,
        {"data": [{"funding_time": START}], "coverage": "COMPLETE"},
    )
    fake_api.routes["/v1/open-interest/BTCUSDT"] = (
        200,
        {"data": [{"ts": START}], "coverage": "COMPLETE"},
    )
    evidence = _evidence(api_url)
    evidence.funding("BTCUSDT", decision_as_of=decision_as_of)
    evidence.open_interest("BTCUSDT", decision_as_of=decision_as_of)
    assert int(fake_api.requests[0]["query"]["as_of"][0]) == decision_as_of
    assert int(fake_api.requests[1]["query"]["as_of"][0]) == decision_as_of


def test_future_funding_is_rejected(fake_api, api_url):
    fake_api.routes["/v1/funding/BTCUSDT"] = (
        200,
        {"data": [{"funding_time": START + 5 * HOUR}], "coverage": "COMPLETE"},
    )
    result = _evidence(api_url).funding("BTCUSDT", decision_as_of=START + HOUR)
    assert result.status == DATA_UNAVAILABLE
    assert result.reason == REASON_FUTURE_DATA


def test_future_open_interest_is_rejected(fake_api, api_url):
    fake_api.routes["/v1/open-interest/BTCUSDT"] = (
        200,
        {"data": [{"ts": START + 5 * HOUR}], "coverage": "COMPLETE"},
    )
    result = _evidence(api_url).open_interest("BTCUSDT", decision_as_of=START + HOUR)
    assert result.status == DATA_UNAVAILABLE
    assert result.reason == REASON_FUTURE_DATA
