import copy
import hashlib
import json
import math
from pathlib import Path

import pytest

from crypto_trader.shared_history.readiness import (
    evaluate_history_readiness,
    operational_health_failure,
)


def golden():
    return json.loads((Path(__file__).parent / "fixtures/operational_health_v1.json").read_text())


def test_exact_producer_golden_legacy_age_is_not_operational_age():
    result = evaluate_history_readiness(golden(), ["A", "B"], {"A": 300, "B": 1}, now_ms=1200000)
    assert result.status == "PASS"
    assert golden()["incremental_updater"] == "PASS"
    fixture = Path(__file__).parent / "fixtures/operational_health_v1.json"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == (
        "c85373925bd54f68efd91864d8b28da9568ac8fd41a7e1a874b9d486cc4f05c6"
    )


@pytest.mark.parametrize(
    "component,key,value",
    [
        ("resource", "state", "HIGH"),
        ("resource", "state", "CRITICAL"),
        ("resource", "state", "UNKNOWN"),
        ("resource", "state", None),
        ("scheduler", "running", False),
        ("scheduler", "running", None),
        ("scheduler", "running", 1),
        ("incremental", "last_outcome", "NOT_RUN"),
        ("incremental", "last_outcome", "WAITING"),
        ("incremental", "last_outcome", "ACTIVE"),
        ("resource", "error", "FAILURE"),
        ("scheduler", "error", "FAILURE"),
    ],
)
def test_current_facts_fail_closed(component, key, value):
    data = golden()
    data["operational_health"][component][key] = value
    assert operational_health_failure(data, now_ms=1200000)


@pytest.mark.parametrize(
    "component,key",
    [
        ("resource", "collected_at_ms"),
        ("scheduler", "collected_at_ms"),
        ("incremental", "completed_at_ms"),
        (None, "published_at_ms"),
    ],
)
@pytest.mark.parametrize("value", [None, True, math.nan, math.inf, -1, "1200000", 1200001])
def test_invalid_timestamps(component, key, value):
    data = golden()
    target = data["operational_health"]
    if component:
        target = target[component]
    target[key] = value
    assert operational_health_failure(data, now_ms=1200000)


@pytest.mark.parametrize("component", ["resource", "scheduler"])
def test_ttl_exact_boundary_and_stale(component):
    data = golden()
    data["operational_health"][component]["collected_at_ms"] = 1140000
    assert operational_health_failure(data, now_ms=1200000) is None
    data["operational_health"][component]["collected_at_ms"] -= 1
    assert operational_health_failure(data, now_ms=1200000)


@pytest.mark.parametrize(
    "key,value",
    [("schema_version", 2), ("schema_version", True), ("generation", 0), ("generation", True)],
)
def test_schema_and_generation(key, value):
    data = golden()
    data["operational_health"][key] = value
    assert operational_health_failure(data, now_ms=1200000)


def test_missing_stale_mixed_generations_and_independent_market_freshness():
    data = golden()
    missing = copy.deepcopy(data)
    missing.pop("operational_health")
    assert operational_health_failure(missing, now_ms=1200000)
    assert operational_health_failure(data, now_ms=1260001)
    data["operational_health"]["published_at_ms"] = 1199999
    assert operational_health_failure(data, now_ms=1200000)
    data = golden()
    assert evaluate_history_readiness(data, ["A"], {"A": 301}, now_ms=1200000).status == "STALE"
    assert evaluate_history_readiness(data, [], {}, now_ms=1200000).status != "PASS"
    assert evaluate_history_readiness(data, ["A", "B"], {"A": 1}, now_ms=1200000).status != "PASS"


def test_operational_degradation_invalidates_adapter_cache(fake_api, api_url, monkeypatch):
    from crypto_trader.shared_history.adapter import SharedHistoryEvidence
    monkeypatch.setattr("crypto_trader.shared_history.adapter._now_ms", lambda: 1200000)
    data = golden()
    fake_api.routes["/v1/health"] = (200, data)
    fake_api.routes["/v1/latest"] = (200, {"data": [{"close": 1}], "coverage": "COMPLETE"})
    adapter = SharedHistoryEvidence(enabled=True, base_url=api_url)
    assert adapter.health().available
    assert adapter.latest_candles("BTC", "1m").available
    data["operational_health"]["resource"]["state"] = "CRITICAL"
    assert not adapter.health().available
    assert not adapter.latest_candles("BTC", "1m").available
    assert fake_api.count("/v1/latest") == 1
