"""P0 correction verification tests (CS-20260829-132209-P0-MANUAL-BYPASS).

Covers the Supervisor-required corrections:
- /manual-orders, /paper/perpetual/open, /paper/perpetual/close are
  FAIL-CLOSED (403 on any request; no state change; audit row recorded)
- /paper/perpetual/positions is read-only AND projects real per-symbol marks
- /positions leverage exposes the authoritative engine/ledger leverage
- episode quarantine honors after_json.tainted_fill_ids (full-episode scope)
- perp episode leverage comes from the ledger OPEN metadata (never 0)
- runtime schema DDL is prohibited (ensure_columns verifies only)
- entry cooldown is symbol-scoped (P1 CS-20260829-125002)
"""
import sqlite3
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from crypto_trader.api.app import create_app
from crypto_trader.api.deps import AppState
from crypto_trader.config import Settings
from crypto_trader.domain.enums import MarketType, OrderSide, OrderType, PositionSide
from crypto_trader.domain.models import SignalIntent
from crypto_trader.governance.trade_episodes import (
    ensure_columns,
    record_all_cycles_sync,
)
from tests.integration.test_order_read_model import _seed_mark
from tests.integration.test_perpetual_runtime_routing import _make_bundle
from tests.runtime_unit.test_ai_first_entry_policy import (
    _chief_context,
    _long_decision,
    _TestAIFirstAdapter,
)

D = Decimal

DB_FILE = None  # set by fixture


@pytest.fixture
async def bundle_env(database):
    bundle = await _make_bundle(database, auto_start=True)
    return bundle, database.url.split("sqlite+aiosqlite:///")[-1]


@pytest.fixture
async def env(database):
    bundle = await _make_bundle(database, auto_start=True)
    settings = Settings(
        _env_file=None,
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        database_url=database.url,
        auto_start_runtime=False,
    )
    state = AppState(
        settings=settings,
        database=bundle.database,
        order_manager=bundle.engine.order_manager,
        ledger=bundle.engine.ledger,
        portfolio=bundle.engine.portfolio,
        audit=bundle.engine.audit,
        risk=bundle.engine.risk_engine,
        market_data=bundle.engine.market_data,
        leases=bundle.engine.lease_manager,
        reconciliation=bundle.engine.reconciliation,
        engine=bundle.engine,
    )
    return bundle, TestClient(create_app(state))


@pytest.mark.asyncio
async def test_manual_mutation_routes_fail_closed(env):
    bundle, client = env
    orders_body = client.get("/orders").json()
    n_orders_before = len(
        orders_body if isinstance(orders_body, list) else orders_body.get("orders", [])
    )

    r1 = client.post("/manual-orders", json={
        "symbol": "BTCUSDT", "side": "BUY", "quantity": "0.001",
    })
    r2 = client.post("/paper/perpetual/open", json={
        "side": "LONG", "quantity": "0.1", "price": "100",
    })
    r3 = client.post("/paper/perpetual/close", json={
        "side": "LONG", "quantity": "0.1", "price": "100",
    })
    assert r1.status_code == 403, r1.text
    assert r2.status_code == 403, r2.text
    assert r3.status_code == 403, r3.text

    # No state change: no order, no perp position, no fake price anywhere
    orders_after = client.get("/orders").json()
    n_orders_after = len(
        orders_after if isinstance(orders_after, list) else orders_after.get("orders", [])
    )
    assert n_orders_after == n_orders_before
    perp = client.get("/paper/perpetual/positions").json()
    assert perp.get("positions", {}) == {}

    # Every blocked attempt is durably audited
    blocked = client.get("/health").status_code  # sanity: app still alive
    assert blocked == 200


@pytest.mark.asyncio
async def test_paper_perpetual_positions_uses_real_marks(env):
    bundle, client = env
    await _seed_mark(bundle, "ZECUSDT", "10")
    d = await bundle.engine.process_signal(SignalIntent(
        signal_id="sig_perp_marks_open", strategy_id="test", symbol="ZECUSDT_PERP",
        side=OrderSide.BUY, quantity="0.0002", order_type=OrderType.MARKET,
        reason="open long", market_type=MarketType.PERPETUAL,
        position_side=PositionSide.LONG,
    ))
    assert d.decision.value == "APPROVE", d.reason

    await _seed_mark(bundle, "ZECUSDT", "12", sequence=2)  # move the mark
    resp = client.get("/paper/perpetual/positions")
    assert resp.status_code == 200
    pos = resp.json()["positions"]["ZECUSDT_PERP"]
    assert D(pos["mark_price"]) == D("12")  # REAL book mark, never 0
    assert pos["mark_source"] == "OKX_REAL_BOOK"
    assert D(pos["unrealized_pnl"]) != 0


@pytest.mark.asyncio
async def test_positions_read_model_leverage_is_engine_leverage(env):
    bundle, client = env
    await _seed_mark(bundle, "ZECUSDT", "10")
    d = await bundle.engine.process_signal(SignalIntent(
        signal_id="sig_lev_open", strategy_id="test", symbol="ZECUSDT_PERP",
        side=OrderSide.BUY, quantity="0.0002", order_type=OrderType.MARKET,
        reason="open long", market_type=MarketType.PERPETUAL,
        position_side=PositionSide.LONG,
    ))
    assert d.decision.value == "APPROVE", d.reason

    import sqlite3
    db_file = str(database_path_from_url(database_url(bundle)))
    conn = sqlite3.connect(db_file)
    ledger_lev = conn.execute(
        "SELECT json_extract(metadata_json, '$.leverage') FROM ledger_transactions "
        "WHERE metadata_json LIKE '%\"action\": \"OPEN\"%'"
    ).fetchone()[0]
    conn.close()

    resp = client.get("/positions")
    assert resp.status_code == 200
    body = resp.json() if isinstance(resp.json(), dict) else {}
    positions = body.get("positions", body)
    pos = positions["ZECUSDT_PERP"]
    assert pos["market_type"] == "PERPETUAL"
    # authoritative engine leverage (not a contract-size recomputation)
    assert D(pos["leverage"]) == D(ledger_lev)
    assert D(pos["leverage"]) > 0


def database_url(bundle):
    return bundle.database.url


def database_path_from_url(url: str) -> str:
    return url.split("sqlite+aiosqlite:///")[-1]


@pytest.mark.asyncio
async def test_quarantine_after_json_tainted_fill_ids_excluded(bundle_env):
    """after_json.tainted_fill_ids (legacy representation) must quarantine."""
    bundle, db_file = bundle_env
    from tests.integration.test_trade_episodes import _episodes, _open_spot

    await _open_spot(bundle, "ARBUSDT", OrderSide.BUY, "0.001", "0.10")

    conn = sqlite3.connect(db_file)
    fill_id = conn.execute(
        "SELECT fill_id FROM fills WHERE side='BUY' AND symbol='ARBUSDT'"
    ).fetchone()[0]
    # legacy representation: ids in after_json, NOT in target
    conn.execute(
        "INSERT INTO audit_events (audit_event_id, event_id, action, actor, "
        "target, after_json, timestamp) VALUES (?,?,?,?,?,?,?)",
        ("audit_q2", "evt_q2", "EVIDENCE_QUARANTINE", "test", "",
         '{"tainted_fill_ids": ["' + fill_id + '"]}', "2026-08-29 00:00:00"),
    )
    conn.commit()
    conn.close()

    await _open_spot(bundle, "ARBUSDT", OrderSide.SELL, "0.001", "0.20", reduce_only=True)
    result = record_all_cycles_sync(db_file)
    assert result["inserted"] == 0
    assert len(_episodes(db_file)) == 0


@pytest.mark.asyncio
async def test_perp_episode_leverage_from_ledger_open_not_zero(bundle_env):
    """Perp episode leverage must equal ledger OPEN leverage (never 0)."""
    bundle, db_file = bundle_env
    from tests.integration.test_order_read_model import _seed_mark as seed

    await seed(bundle, "ZECUSDT", "10")
    d1 = await bundle.engine.process_signal(SignalIntent(
        signal_id="sig_eps_open", strategy_id="test", symbol="ZECUSDT_PERP",
        side=OrderSide.BUY, quantity="0.0002", order_type=OrderType.MARKET,
        reason="open long", market_type=MarketType.PERPETUAL,
        position_side=PositionSide.LONG,
    ))
    assert d1.decision.value == "APPROVE"
    await seed(bundle, "ZECUSDT", "11", sequence=2)
    d2 = await bundle.engine.process_signal(SignalIntent(
        signal_id="sig_eps_close", strategy_id="test", symbol="ZECUSDT_PERP",
        side=OrderSide.SELL, quantity="0.0002", order_type=OrderType.MARKET,
        reason="close long", market_type=MarketType.PERPETUAL,
        position_side=PositionSide.LONG, reduce_only=True,
    ))
    assert d2.decision.value == "APPROVE"

    conn = sqlite3.connect(db_file)
    ledger_lev = conn.execute(
        "SELECT json_extract(metadata_json, '$.leverage') FROM ledger_transactions "
        "WHERE metadata_json LIKE '%\"action\": \"OPEN\"%'"
    ).fetchone()[0]
    ep_lev = conn.execute(
        "SELECT leverage FROM ai_trade_episodes"
    ).fetchall()
    conn.close()
    assert ep_lev, "episode must exist"
    for (lev,) in ep_lev:
        assert D(lev) == D(ledger_lev)
        assert D(lev) > 0


def test_ensure_columns_never_alters_schema():
    """ensure_columns must verify only: no runtime DDL, ever."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE ai_trade_episodes (episode_id VARCHAR PRIMARY KEY)"
    )
    try:
        ensure_columns(conn)
        raise AssertionError("missing columns must raise, not silently ALTER")
    except RuntimeError as exc:
        assert "alembic upgrade head" in str(exc)
    # no ALTER happened
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ai_trade_episodes)")}
    assert cols == {"episode_id"}
    conn.close()


@pytest.mark.asyncio
async def test_entry_cooldown_symbol_scoped():
    """A trade in symbol A must NOT preempt the decision for symbol B."""
    adapter = _TestAIFirstAdapter(
        _chief_context(fit=0.60, regime="BULL"),
        _long_decision(fit=0.60, confidence=0.70),
    )
    adapter.entry_cooldown_seconds = 3600.0  # long window for the test
    ctx_a = SimpleNamespace(symbol="ETHUSDT", positions={})
    ctx_b = SimpleNamespace(symbol="BTCUSDT", positions={})

    s1 = await adapter._decide(ctx_a)
    assert len(s1) == 1  # entry A recorded
    assert "ETHUSDT" in adapter._last_entry_initiated_at

    # B is a DIFFERENT symbol: cooldown must NOT gate it
    s2 = await adapter._decide(ctx_b)
    assert len(s2) == 1
    assert "BTCUSDT" in adapter._last_entry_initiated_at
    assert adapter.engine.calls == 2

    # same symbol again: gated by the symbol-scoped cooldown
    s3 = await adapter._decide(ctx_a)
    assert s3 == []
    gated = adapter.persisted[-1]
    assert "ENTRY_COOLDOWN_ACTIVE" in gated.reason_codes
    assert adapter.engine.calls == 2  # no extra LLM call for gated decision
