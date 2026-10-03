"""The read contract and the transport contract of the reused client.

Proves the required read interface exists, that the client speaks GET only, that it
identifies itself for observability, and that it refuses a non-loopback target.
"""

from __future__ import annotations

import pytest

from crypto_trader.shared_history import (
    LowRiskSharedHistoryClient,
    SharedHistoryClientError,
    is_loopback_url,
)
from tests.shared_history.conftest import candle_payload, candle_rows

START = 1_700_000_000_000

REQUIRED_READ_METHODS = (
    "health",
    "universe",
    "latest_candles",
    "historical_candles",
    "features",
    "regime",
    "funding",
    "open_interest",
)


def test_required_read_interface_exists():
    for name in REQUIRED_READ_METHODS:
        assert callable(getattr(LowRiskSharedHistoryClient, name)), name


def test_every_read_uses_the_expected_endpoint(fake_api, api_url):
    fake_api.routes["/v1/health"] = (200, {"service_status": "OK"})
    fake_api.routes["/v1/universe"] = (200, {"symbols": [], "count": 0})
    fake_api.routes["/v1/latest"] = (200, candle_payload(candle_rows(START, 2)))
    fake_api.routes["/v1/candles"] = (200, candle_payload(candle_rows(START, 2)))
    fake_api.routes["/v1/features/BTCUSDT"] = (200, {"data": [{"close": 1.0}]})
    fake_api.routes["/v1/regime/BTCUSDT"] = (200, {"data": [{"regime": "TREND_UP"}]})
    fake_api.routes["/v1/funding/BTCUSDT"] = (200, {"data": [{"funding_time": START}]})
    fake_api.routes["/v1/open-interest/BTCUSDT"] = (200, {"data": [{"ts": START}]})

    client = LowRiskSharedHistoryClient(api_url)
    client.health()
    client.universe()
    client.latest_candles("btcusdt", "1h", limit=2)
    client.historical_candles("BTCUSDT", "1h", start=START, end=START + 10, limit=2)
    client.features("BTCUSDT")
    client.regime("BTCUSDT")
    client.funding("BTCUSDT")
    client.open_interest("BTCUSDT")

    paths = [r["path"] for r in fake_api.requests]
    assert paths == [
        "/v1/health",
        "/v1/universe",
        "/v1/latest",
        "/v1/candles",
        "/v1/features/BTCUSDT",
        "/v1/regime/BTCUSDT",
        "/v1/funding/BTCUSDT",
        "/v1/open-interest/BTCUSDT",
    ]


def test_candle_query_parameters_are_forwarded(fake_api, api_url):
    """Candle reads forward symbol/timeframe/limit unchanged.

    This preserves the reused client's exact behavior. The candle endpoints normalise
    the symbol service-side; the path endpoints normalise it client-side (covered by
    the next test). LowRisk does not rewrite the accepted client's semantics.
    """
    fake_api.routes["/v1/latest"] = (200, candle_payload(candle_rows(START, 1)))
    LowRiskSharedHistoryClient(api_url).latest_candles("BTCUSDT", "1h", limit=5)
    query = fake_api.requests[0]["query"]
    assert query["symbol"] == ["BTCUSDT"]
    assert query["timeframe"] == ["1h"]
    assert query["limit"] == ["5"]


def test_path_endpoints_normalise_the_symbol(fake_api, api_url):
    fake_api.routes["/v1/funding/BTCUSDT"] = (200, {"data": [{"funding_time": START}]})
    LowRiskSharedHistoryClient(api_url).funding(" btcusdt ")
    assert fake_api.requests[0]["path"] == "/v1/funding/BTCUSDT"


def test_transport_is_get_only(fake_api, api_url):
    """The client must never issue a mutating verb."""
    fake_api.routes["/v1/health"] = (200, {"service_status": "OK"})
    client = LowRiskSharedHistoryClient(api_url)
    client.health()
    assert fake_api.methods_seen == {"GET"}


def test_consumer_header_is_informational(fake_api, api_url):
    fake_api.routes["/v1/health"] = (200, {"service_status": "OK"})
    LowRiskSharedHistoryClient(api_url).health()
    headers = fake_api.requests[0]["headers"]
    assert headers["x-consumer"] == "lowrisk"


def test_non_get_methods_are_not_exposed():
    """No POST/PUT/PATCH/DELETE helper exists on the LowRisk client."""
    forbidden = ("post", "put", "patch", "delete", "write", "append", "ingest", "admin")
    for name in dir(LowRiskSharedHistoryClient):
        if name.startswith("_"):
            continue
        lowered = name.lower()
        assert not lowered.startswith(forbidden), name


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://127.0.0.1:8770", True),
        ("http://127.0.0.1", True),
        ("http://localhost:8770", True),
        ("http://[::1]:8770", True),
        ("https://127.0.0.1:8770", True),
        ("http://192.168.1.10:8770", False),
        ("https://shared-history.example.com", False),
        ("http://0.0.0.0:8770", False),
        ("ftp://127.0.0.1", False),
        ("not-a-url", False),
    ],
)
def test_loopback_detection(url, expected):
    assert is_loopback_url(url) is expected


def test_non_loopback_target_is_refused():
    with pytest.raises(SharedHistoryClientError):
        LowRiskSharedHistoryClient("https://shared-history.example.com")


def test_http_error_is_fail_closed(fake_api, api_url):
    fake_api.routes["/v1/candles"] = (500, {"error": "internal_error"})
    with pytest.raises(SharedHistoryClientError) as excinfo:
        LowRiskSharedHistoryClient(api_url).historical_candles("BTCUSDT", "1h")
    assert "HTTP 500" in str(excinfo.value)


def test_non_object_json_is_fail_closed(fake_api, api_url):
    fake_api.raw_body = "[1, 2, 3]"
    with pytest.raises(SharedHistoryClientError):
        LowRiskSharedHistoryClient(api_url).health()


def test_invalid_json_is_fail_closed(fake_api, api_url):
    fake_api.raw_body = "{ not json"
    with pytest.raises(SharedHistoryClientError):
        LowRiskSharedHistoryClient(api_url).health()


def test_unreachable_service_is_fail_closed():
    # Port 1 on loopback: reserved and not listening.
    with pytest.raises(SharedHistoryClientError):
        LowRiskSharedHistoryClient("http://127.0.0.1:1", timeout=1.0).health()
