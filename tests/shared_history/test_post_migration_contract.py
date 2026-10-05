from __future__ import annotations

import json
import math
import time
from pathlib import Path

import pytest

from crypto_trader.shared_history.adapter import SharedHistoryEvidence
from crypto_trader.shared_history.consumer import RuntimeHistoryConsumer
from crypto_trader.shared_history.readiness import evaluate_history_readiness


def health():
    data = json.loads((Path(__file__).parent / "fixtures/operational_health_v1.json").read_text())
    now = time.time() * 1000
    envelope = data["operational_health"]
    envelope["published_at_ms"] = now
    envelope["resource"]["collected_at_ms"] = now
    envelope["scheduler"]["collected_at_ms"] = now
    envelope["incremental"]["completed_at_ms"] = now - 100000
    return data


@pytest.mark.parametrize("count", [1, 3, 17])
def test_dynamic_complete_universe(count):
    universe = [f"SYM{i}" for i in range(count)]
    result = evaluate_history_readiness(health(), universe, dict.fromkeys(universe, 300))
    assert result.status == "PASS"
    assert result.eligible_universe == count
    assert result.outside_300s == 0


@pytest.mark.parametrize(
    "universe,values", [([], {}), (["A"], {}), (["A", "B"], {"A": 1}), (["A", "A"], {"A": 1})]
)
def test_missing_evidence_never_vacuous_pass(universe, values):
    assert evaluate_history_readiness(health(), universe, values).status == "NOT_VERIFIED"


@pytest.mark.parametrize("value", [None, math.inf, math.nan, -1, True, "0"])
def test_unknown_freshness_is_not_pass(value):
    assert evaluate_history_readiness(health(), ["A"], {"A": value}).status == "NOT_VERIFIED"


def test_no_threshold_relaxation_or_symbol_exclusion():
    result = evaluate_history_readiness(health(), ["A", "B"], {"A": 0, "B": 300.01})
    assert result.status == "STALE"
    assert result.outside_300s == 1
    assert result.eligible_universe == 2


@pytest.mark.parametrize(
    "key,value",
    [
        ("service_status", "UNAVAILABLE"),
        ("writer_count", 2),
        ("writer_count", True),
        ("health_snapshot_stale", True),
    ],
)
def test_resource_health_fail_closed(key, value):
    data = health()
    data[key] = value
    assert evaluate_history_readiness(data, ["A"], {"A": 0}).status != "PASS"


def test_health_missing_resource_field_not_inferred_normal():
    data = health()
    del data["operational_health"]["resource"]
    assert evaluate_history_readiness(data, ["A"], {"A": 0}).status != "PASS"


@pytest.mark.parametrize("state", ["PAUSED_RESOURCE_CRITICAL", "STALE", "UNAVAILABLE"])
def test_adapter_does_not_relabel_successful_http_as_healthy(fake_api, api_url, state):
    fake_api.routes["/v1/health"] = (200, {"service_status": state, "writer_count": 1})
    result = SharedHistoryEvidence(enabled=True, base_url=api_url).health()
    assert not result.available
    assert result.reason == "HISTORICAL_DATA_UNAVAILABLE"


def test_observed_degraded_health_invalidates_cached_candles(fake_api, api_url):
    fake_api.routes["/v1/latest"] = (200, {"data": [{"close": 1}], "coverage": "COMPLETE"})
    adapter = SharedHistoryEvidence(enabled=True, base_url=api_url)
    assert adapter.latest_candles("BTC", "1m").available
    fake_api.routes["/v1/health"] = (200, {"service_status": "PAUSED_RESOURCE_CRITICAL"})
    assert not adapter.health().available
    assert not adapter.latest_candles("BTC", "1m").available


def test_feature_version_cache_is_pure(fake_api, api_url):
    adapter = SharedHistoryEvidence(enabled=True, base_url=api_url)
    for version in ("v1", "v2"):
        fake_api.routes["/v1/features/BTC"] = (
            200,
            {
                "data": [{"feature": 1}],
                "feature_set_version": version,
            },
        )
        assert adapter.features("BTC", feature_set_version=version).schema_version == version
    assert fake_api.count("/v1/features/BTC") == 2
    assert not adapter.features("BTC", feature_set_version="v3").available


def test_redirect_cannot_escape_loopback(fake_api, api_url, monkeypatch):
    import urllib.request

    from crypto_trader.shared_history.client import _NoRedirect

    with pytest.raises(Exception, match="redirects are forbidden"):
        _NoRedirect().redirect_request(
            urllib.request.Request(api_url), None, 302, "Found", {}, "https://external.invalid"
        )


def test_runtime_consumer_checks_current_health_before_cached_read(fake_api, api_url):
    current = {
        **health(),
        "health_snapshot_generated_at": time.time() * 1000,
        "latest_1m_freshness_seconds": 10,
    }
    fake_api.routes["/v1/health"] = (200, current)
    fake_api.routes["/v1/latest"] = (200, {"data": [{"close": 1}], "coverage": "COMPLETE"})
    consumer = RuntimeHistoryConsumer(SharedHistoryEvidence(enabled=True, base_url=api_url))
    assert consumer.read("latest_candles", "BTC", "1m").available
    current["latest_1m_freshness_seconds"] = 301
    assert not consumer.read("latest_candles", "BTC", "1m").available
    assert fake_api.count("/v1/latest") == 1
    with pytest.raises(ValueError, match="READ_ONLY"):
        consumer.read("backfill")


def test_application_bootstrap_binding_and_default_off():
    # Test construction elsewhere uses the same bootstrap; inspect the explicit
    # binding without starting the runtime, DB, providers or services here.
    import inspect

    from crypto_trader.config import Settings
    from crypto_trader.runtime.bootstrap import build_system

    assert "historical_evidence=RuntimeHistoryConsumer" in inspect.getsource(build_system)
    assert not Settings().shared_history_enabled
