"""Dynamic OKX instrument registry + resolver tests (Phase B).

All HTTP is mocked (httpx.MockTransport) - no live API in CI. The registry is
the truth source for universe membership: delisted instruments can never
enter the tradeable universe (§52), and the resolver never invents mappings
(§6/§53).
"""
import sqlite3
from decimal import Decimal

import httpx
import pytest

from crypto_trader.market_registry.registry import (
    InstrumentRecord,
    OkxPublicClient,
    fetch_registry_snapshot,
    persist_registry_sync,
    refresh_sync,
    registry_stats_sync,
    tradeable_universe_sync,
)
from crypto_trader.market_registry.resolver import InstrumentResolver

D = Decimal


def _inst(inst_id: str, inst_type: str, state: str = "live", **extra) -> dict:
    base, _, quote = inst_id.partition("-")
    row = {
        "instId": inst_id,
        "instType": inst_type,
        "baseCcy": base if inst_type == "SPOT" else None,
        "quoteCcy": quote or None,
        "settleCcy": "USDT" if inst_type in ("SWAP", "FUTURES") else None,
        "state": state,
        "tickSz": "0.01",
        "lotSz": "0.0001",
        "minSz": "0.0001",
        "ctVal": "0.01" if inst_type == "SWAP" else "",
        "ctValCcy": base if inst_type == "SWAP" else "",
        "ctType": "linear" if inst_type == "SWAP" else "",
        "lever": "10" if inst_type in ("SWAP", "FUTURES") else "",
        "expTime": "",
        "listTime": "1700000000000",
        "uly": inst_id if inst_type == "SWAP" else "",
    }
    row.update(extra)
    return row


def _client_with(rows_by_type: dict[str, list[dict]], underlyings: list[str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)
        if path == "/api/v5/public/instruments":
            rows = rows_by_type.get(params.get("instType", ""), [])
            return httpx.Response(200, json={"code": "0", "data": rows})
        if path == "/api/v5/public/underlying":
            return httpx.Response(200, json={"code": "0", "data": [underlyings or []]})
        return httpx.Response(200, json={"code": "0", "data": []})

    return OkxPublicClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def test_instrument_record_from_api_fields():
    raw = _inst("BTC-USDT", "SPOT")
    rec = InstrumentRecord.from_api(raw)
    assert rec.inst_id == "BTC-USDT"
    assert rec.base_ccy == "BTC"
    assert rec.quote_ccy == "USDT"
    assert rec.state == "live"
    assert rec.tick_sz == "0.01"
    assert rec.ct_type is None  # SPOT has no contract type


def test_fetch_snapshot_counts_and_option_underlyings():
    client = _client_with(
        {
            "SPOT": [_inst("BTC-USDT", "SPOT"), _inst("ETH-USDT", "SPOT")],
            "SWAP": [_inst("BTC-USDT-SWAP", "SWAP")],
            "FUTURES": [],
        },
        underlyings=["BTC-USD", "ETH-USD"],
    )
    records, snapshot, opt = fetch_registry_snapshot(client)
    assert opt == 2
    assert snapshot.counts == {"SPOT": 2, "SWAP": 1, "FUTURES": 0}
    assert len(records) == 3
    assert all(isinstance(r, InstrumentRecord) for r in records)


def test_persist_upsert_and_delisting(tmp_path):
    db = str(tmp_path / "reg.db")
    client = _client_with({"SPOT": [_inst("BTC-USDT", "SPOT"), _inst("OLD-USDT", "SPOT")]})
    records, snapshot, _ = fetch_registry_snapshot(client)
    snap = persist_registry_sync(db, records, snapshot)
    assert snap.inserted == 2 and snap.updated == 0

    # second refresh: OLD-USDT vanished, NEW-USDT appears, BTC stays
    client2 = _client_with({"SPOT": [_inst("BTC-USDT", "SPOT"), _inst("NEW-USDT", "SPOT")]})
    records2, snapshot2, _ = fetch_registry_snapshot(client2)
    snap2 = persist_registry_sync(db, records2, snapshot2)
    assert snap2.inserted == 1  # NEW-USDT
    assert snap2.updated == 1  # BTC-USDT

    conn = sqlite3.connect(db)
    states = dict(conn.execute("SELECT inst_id, state FROM okx_instruments").fetchall())
    conn.close()
    assert states["OLD-USDT"] == "DELISTED"  # kept as history
    assert states["BTC-USDT"] == "live"
    assert states["NEW-USDT"] == "live"


def test_delisted_never_in_tradeable_universe(tmp_path):
    db = str(tmp_path / "reg.db")
    client = _client_with({"SPOT": [_inst("BTC-USDT", "SPOT"), _inst("OLD-USDT", "SPOT")]})
    records, snapshot, _ = fetch_registry_snapshot(client)
    persist_registry_sync(db, records, snapshot)
    client2 = _client_with({"SPOT": [_inst("BTC-USDT", "SPOT")]})
    records2, snapshot2, _ = fetch_registry_snapshot(client2)
    persist_registry_sync(db, records2, snapshot2)

    universe = tradeable_universe_sync(db, "SPOT", "USDT")
    assert "BTC-USDT" in universe
    assert "OLD-USDT" not in universe  # delisted instruments cannot trade (§52)
    assert all(u.endswith("USDT") for u in universe)


def test_registry_stats(tmp_path):
    db = str(tmp_path / "reg.db")
    snap = refresh_sync(db, _client_with(
        {
            "SPOT": [_inst("BTC-USDT", "SPOT")],
            "SWAP": [_inst("BTC-USDT-SWAP", "SWAP", state="suspend")],
        },
    ))
    assert snap["inserted"] == 2
    stats = registry_stats_sync(db)
    assert stats["by_type"]["SPOT"]["live"] == 1
    assert stats["by_type"]["SWAP"]["live"] == 0  # suspended not live
    assert stats["last_refreshed_at"]


def test_resolver_registry_checked_mapping(tmp_path):
    db = str(tmp_path / "reg.db")
    records, snapshot, _ = fetch_registry_snapshot(_client_with({
        "SPOT": [_inst("BTC-USDT", "SPOT")],
        "SWAP": [],  # no BTC-USDT-SWAP instrument
    }))
    persist_registry_sync(db, records, snapshot)
    resolver = InstrumentResolver(db)

    assert resolver.to_okx_spot("BTCUSDT") == "BTC-USDT"
    assert resolver.from_okx("BTC-USDT-SWAP") == "BTCUSDT"
    assert resolver.reference_symbol("BTC-USDT-SWAP") == "BTCUSDT"
    assert resolver.triple("BTCUSDT").okx_swap == "BTC-USDT-SWAP"

    # registry-checked swap resolution: BTC-USDT-SWAP missing -> NOT invented
    with pytest.raises(KeyError):
        resolver.to_okx_swap("BTCUSDT")

    # unknown spot instrument: fail loud, never string-surgery fallback (§53)
    with pytest.raises(KeyError):
        resolver.to_okx_spot("FAKEUSDT")


def test_resolver_relation_mode_without_registry():
    resolver = InstrumentResolver(None)
    assert resolver.to_okx_spot("ETHUSDT") == "ETH-USDT"
    assert resolver.to_okx_swap("ETHUSDT") == "ETH-USDT-SWAP"
    assert resolver.from_okx("SOL-USDT-SWAP") == "SOLUSDT"
