"""Bounded reads and the bounded cache.

The cache must have an explicit TTL and an explicit size bound, must retain source
and freshness metadata on every hit, and must never be silently presented as a fresh
read.
"""

from __future__ import annotations

from crypto_trader.shared_history import SharedHistoryEvidence
from crypto_trader.shared_history.adapter import _MAX_LIMIT
from tests.shared_history.conftest import candle_payload, candle_rows

START = 1_700_000_000_000


def _evidence(api_url, **kwargs) -> SharedHistoryEvidence:
    return SharedHistoryEvidence(enabled=True, base_url=api_url, **kwargs)


def test_second_identical_read_is_served_from_cache(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (200, candle_payload(candle_rows(START, 2)))
    evidence = _evidence(api_url)

    first = evidence.latest_candles("BTCUSDT", "1h")
    second = evidence.latest_candles("BTCUSDT", "1h")

    assert first.cached is False
    assert second.cached is True
    assert fake_api.count("/v1/latest") == 1
    assert evidence.counters()["cache_hit_count"] == 1


def test_cached_result_retains_provenance(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (200, candle_payload(candle_rows(START, 2)))
    evidence = _evidence(api_url)
    evidence.latest_candles("BTCUSDT", "1h")
    cached = evidence.latest_candles("BTCUSDT", "1h")

    assert cached.source == "okx"
    assert cached.schema_version == "smh.parquet.v1"
    assert cached.row_count == 2
    assert cached.first_timestamp == START
    assert cached.last_timestamp is not None
    assert cached.freshness is not None
    assert cached.read_at > 0


def test_different_as_of_is_a_different_cache_key(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (200, candle_payload(candle_rows(START, 2)))
    evidence = _evidence(api_url)
    evidence.latest_candles("BTCUSDT", "1h", decision_as_of=START + 10 * 3_600_000)
    evidence.latest_candles("BTCUSDT", "1h", decision_as_of=START + 20 * 3_600_000)
    assert fake_api.count("/v1/latest") == 2


def test_different_symbol_is_a_different_cache_key(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (200, candle_payload(candle_rows(START, 2)))
    evidence = _evidence(api_url)
    evidence.latest_candles("BTCUSDT", "1h")
    evidence.latest_candles("ETHUSDT", "1h")
    assert fake_api.count("/v1/latest") == 2


def test_expired_entry_is_refetched(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (200, candle_payload(candle_rows(START, 2)))
    evidence = _evidence(api_url, cache_ttl_seconds=0.0)
    evidence.latest_candles("BTCUSDT", "1h")
    evidence.latest_candles("BTCUSDT", "1h")
    assert fake_api.count("/v1/latest") == 2


def test_cache_size_is_bounded(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (200, candle_payload(candle_rows(START, 2)))
    evidence = _evidence(api_url, cache_max_entries=3)
    for i in range(8):
        evidence.latest_candles(f"SYM{i}USDT", "1h")
    assert evidence.cache_size <= 3
    assert evidence.counters()["cache_eviction_count"] >= 5


def test_row_limit_is_bounded(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (200, candle_payload(candle_rows(START, 2)))
    _evidence(api_url).latest_candles("BTCUSDT", "1h", limit=99_999_999)
    assert int(fake_api.requests[0]["query"]["limit"][0]) == _MAX_LIMIT


def test_non_positive_limit_is_floored(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (200, candle_payload(candle_rows(START, 2)))
    _evidence(api_url).latest_candles("BTCUSDT", "1h", limit=0)
    assert int(fake_api.requests[0]["query"]["limit"][0]) == 1


def test_cache_clear_empties_the_cache(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (200, candle_payload(candle_rows(START, 2)))
    evidence = _evidence(api_url)
    evidence.latest_candles("BTCUSDT", "1h")
    evidence.cache_clear()
    assert evidence.cache_size == 0
    evidence.latest_candles("BTCUSDT", "1h")
    assert fake_api.count("/v1/latest") == 2


def test_adapter_normalises_symbol_for_query_and_cache(fake_api, api_url):
    """The cache key, the outgoing query and the recorded provenance must agree."""
    fake_api.routes["/v1/latest"] = (200, candle_payload(candle_rows(START, 2)))
    evidence = _evidence(api_url)
    first = evidence.latest_candles(" btcusdt ", "1h")
    second = evidence.latest_candles("BTCUSDT", "1h")
    assert fake_api.requests[0]["query"]["symbol"] == ["BTCUSDT"]
    assert first.symbol == "BTCUSDT"
    assert second.cached is True
    assert fake_api.count("/v1/latest") == 1


def test_failed_read_is_not_cached(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (500, {"error": "internal_error"})
    evidence = _evidence(api_url)
    evidence.latest_candles("BTCUSDT", "1h")
    assert evidence.cache_size == 0


def test_empty_result_is_not_cached_as_data(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (200, candle_payload([], coverage="DATA_UNAVAILABLE"))
    evidence = _evidence(api_url)
    evidence.latest_candles("BTCUSDT", "1h")
    assert evidence.cache_size == 0
