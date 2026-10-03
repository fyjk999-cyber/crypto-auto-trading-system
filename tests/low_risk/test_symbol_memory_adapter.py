from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from crypto_trader.config import Settings
from crypto_trader.symbol_memory import (
    MEMORY_SCHEMA_VERSION,
    LowRiskSymbolMemoryAdapter,
    MemoryRequest,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
PROVENANCE = dict(
    strategy_version="s1",
    factor_version="f1",
    model_version="m1",
    source_sha="fixture-sha",
    memory_schema_version=MEMORY_SCHEMA_VERSION,
)


class Port:
    def __init__(self, rows):
        self.rows = rows
        self.requests = []

    def retrieve(self, request):
        self.requests.append(request)
        if isinstance(self.rows, Exception):
            raise self.rows
        return self.rows


def request():
    return MemoryRequest("BTCUSDT", NOW, PROVENANCE)


def row():
    return dict(
        namespace="lowrisk/BTCUSDT",
        symbol="BTCUSDT",
        episode_id="fixture-id",
        factual=True,
        factual_as_of=NOW.isoformat(),
        closed_at=NOW.isoformat(),
        net_pnl="-2",
        action="BUY",
        review_summary="factual loss",
        **PROVENANCE,
    )


def test_disabled_default_no_io():
    port = Port([row()])
    assert not Settings().lowrisk_symbol_memory_enabled
    result = LowRiskSymbolMemoryAdapter(port).retrieve(request())
    assert result.status == "MEMORY_UNAVAILABLE"
    assert port.requests == []


def test_namespace_and_evidence_only_preserves_losses():
    port = Port([row()])
    result = LowRiskSymbolMemoryAdapter(port, enabled=True).retrieve(request())
    assert port.requests[0].namespace == "lowrisk/BTCUSDT"
    assert result.records[0]["net_pnl"] == "-2"
    assert "action" not in result.records[0]
    assert '"authority": "NONE"' in result.prompt_block()


def test_outage_is_not_empty_history_and_no_secret_in_error():
    result = LowRiskSymbolMemoryAdapter(Port(ValueError("fixture-secret")), enabled=True)
    result = result.retrieve(request())
    assert result.status == "MEMORY_UNAVAILABLE"
    assert "fixture-secret" not in result.prompt_block()
    empty = LowRiskSymbolMemoryAdapter(Port([]), enabled=True).retrieve(request())
    assert empty.status == "NO_RELEVANT_PRIOR_EXPERIENCE"


@pytest.mark.parametrize(
    "key,value",
    [
        ("namespace", "turbo/BTCUSDT"),
        ("symbol", "ETHUSDT"),
        ("model_version", "m2"),
        ("source_sha", None),
        ("factual", False),
        ("closed_at", (NOW + timedelta(seconds=1)).isoformat()),
        ("factual_as_of", (NOW + timedelta(seconds=1)).isoformat()),
    ],
)
def test_namespace_version_temporal_fail_closed(key, value):
    item = row()
    item[key] = value
    result = LowRiskSymbolMemoryAdapter(Port([item]), enabled=True).retrieve(request())
    assert result.status == "MEMORY_UNAVAILABLE"
    assert result.records == ()


def test_missing_request_provenance_is_not_invented():
    port = Port([])
    result = LowRiskSymbolMemoryAdapter(port, enabled=True).retrieve(
        replace(request(), provenance={})
    )
    assert result.reason == "PROVENANCE_MISSING"
    assert port.requests == []
    assert result.provenance["source_sha"] is None


@pytest.mark.parametrize("symbol", ["turbo/BTC", "../BTC", "", "BTC USDT"])
def test_invalid_namespace_path(symbol):
    with pytest.raises(ValueError, match="INVALID_MEMORY_SYMBOL"):
        assert replace(request(), symbol=symbol).namespace
