"""The new active-cycle contract is additive to all existing safety gates."""

import json
import math
from pathlib import Path

import pytest

from crypto_trader.shared_history.readiness import (
    evaluate_history_readiness,
    operational_health_failure,
)


def test_missing_active_metadata_fails_closed():
    health = json.loads((Path(__file__).parent / "fixtures/operational_health_v1.json").read_text())
    for key in list(health["operational_health"]["incremental"]):
        if key.startswith("current_"):
            health["operational_health"]["incremental"].pop(key)
    assert (
        operational_health_failure(health, now_ms=1200000) == "ACTIVE_INCREMENTAL_STATE_UNAVAILABLE"
    )


def healthy():
    health = json.loads((Path(__file__).parent / "fixtures/operational_health_v1.json").read_text())
    health["operational_health"]["incremental"].update(
        current_active=False,
        current_cycle_id=None,
        current_started_at_ms=None,
        current_age_seconds=None,
        current_stale=False,
        current_stale_limit_seconds=300,
    )
    return health


@pytest.mark.parametrize(
    "age,expected",
    [(0, None), (299, None), (300, None), (300.001, "ACTIVE_INCREMENTAL_CYCLE_STALE")],
)
def test_independent_age_boundary(age, expected):
    health = healthy()
    health["operational_health"]["incremental"].update(
        current_active=True,
        current_cycle_id="current",
        current_started_at_ms=1200000 - age * 1000,
        current_age_seconds=0,
    )
    assert operational_health_failure(health, now_ms=1200000) == expected


@pytest.mark.parametrize(
    "key,value",
    [
        ("current_active", None),
        ("current_active", 1),
        ("current_stale", 0),
        ("current_stale_limit_seconds", True),
        ("current_stale_limit_seconds", 301),
        ("current_cycle_id", None),
        ("current_started_at_ms", None),
        ("current_started_at_ms", True),
        ("current_started_at_ms", math.nan),
        ("current_started_at_ms", 1200001),
        ("current_age_seconds", math.nan),
        ("current_age_seconds", True),
        ("current_age_seconds", -1),
    ],
)
def test_invalid_active_metadata_blocks(key, value):
    health = healthy()
    health["operational_health"]["incremental"].update(
        current_active=True,
        current_cycle_id="current",
        current_started_at_ms=1190000,
        current_age_seconds=10,
    )
    health["operational_health"]["incremental"][key] = value
    assert (
        operational_health_failure(health, now_ms=1200000) == "ACTIVE_INCREMENTAL_STATE_UNAVAILABLE"
    )


def test_idle_and_old_gates_and_monotonic_stale_cannot_be_revived():
    health = healthy()
    assert operational_health_failure(health, now_ms=1200000) is None
    health["operational_health"]["incremental"].update(
        current_active=True,
        current_cycle_id="current",
        current_started_at_ms=1190000,
        current_age_seconds=301,
        current_stale=True,
    )
    assert operational_health_failure(health, now_ms=1200000) == "ACTIVE_INCREMENTAL_CYCLE_STALE"
    health = healthy()
    health["operational_health"]["incremental"]["last_outcome"] = "WAITING"
    assert operational_health_failure(health, now_ms=1200000) == "INCREMENTAL_NOT_PASS"
    health = healthy()
    health["operational_health"]["incremental"]["current_started_at_ms"] = 1190000
    assert (
        operational_health_failure(health, now_ms=1200000) == "ACTIVE_INCREMENTAL_STATE_UNAVAILABLE"
    )


def test_active_health_does_not_replace_complete_market_freshness():
    health = healthy()
    assert evaluate_history_readiness(health, ["A"], {"A": 301}, now_ms=1200000).status == "STALE"
    assert evaluate_history_readiness(health, ["A", "B"], {"A": 1}, now_ms=1200000).status != "PASS"
    assert evaluate_history_readiness(health, [], {}, now_ms=1200000).status != "PASS"


def test_stale_active_invalidates_existing_adapter_cache(fake_api, api_url, monkeypatch):
    from crypto_trader.shared_history.adapter import SharedHistoryEvidence

    monkeypatch.setattr("crypto_trader.shared_history.adapter._now_ms", lambda: 1200000)
    health = healthy()
    fake_api.routes["/v1/health"] = (200, health)
    fake_api.routes["/v1/latest"] = (200, {"data": [{"close": 1}], "coverage": "COMPLETE"})
    adapter = SharedHistoryEvidence(enabled=True, base_url=api_url)
    assert adapter.health().available
    assert adapter.latest_candles("BTC", "1m").available
    health["operational_health"]["incremental"].update(
        current_active=True,
        current_cycle_id="current",
        current_started_at_ms=899999,
        current_age_seconds=301,
        current_stale=True,
    )
    assert not adapter.health().available
    assert not adapter.latest_candles("BTC", "1m").available
    assert fake_api.count("/v1/latest") == 1
