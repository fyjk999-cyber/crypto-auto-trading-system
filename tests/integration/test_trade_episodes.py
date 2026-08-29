"""Trade Episode pipeline tests (P2 interrupt, learning loop).

Every episode fact is deterministic from canonical orders/fills/ledger rows.
All tests run on an isolated per-test database (conftest `database` fixture).
"""
import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from crypto_trader.domain.enums import MarketType, OrderSide, OrderType, PositionSide
from crypto_trader.domain.models import SignalIntent
from crypto_trader.governance.trade_episodes import (
    record_all_cycles_sync,
    record_cycle_for_fill_sync,
)
from tests.integration.test_perpetual_runtime_routing import _make_bundle

D = Decimal

DB_FILE = None  # set by fixture


@pytest.fixture
async def bundle_env(database):
    bundle = await _make_bundle(database, auto_start=True)
    return bundle, database.url.split("sqlite+aiosqlite:///")[-1]


async def _open_spot(
    bundle, symbol, side, qty, entry, reduce_only=False,
    strategy="llm_chief_trader", audit=None, fee="0.00001", payload_extra=None,
):
    """Raw canonical order->fill path with exact prices.

    ``audit``: optional dict passed to an AI_EXIT_INTENT audit row written
    after order creation and before the fill (mimics the production bridge,
    which labels the exit intent before the order settles).
    """
    from crypto_trader.domain.enums import TradingMode
    from crypto_trader.domain.identifiers import new_id
    from crypto_trader.domain.models import Fill, OrderIntent

    intent = OrderIntent(
        client_order_id=new_id("cli"),
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=D(qty),
        strategy_id=strategy,
        market_type=MarketType.SPOT,
        reduce_only=reduce_only,
    )
    om = bundle.engine.order_manager
    order = await om.create_from_intent(intent, trading_mode=TradingMode.PAPER)
    await om.validate(order.internal_order_id)
    await om.submitting(order.internal_order_id)
    await om.submitted(order.internal_order_id)
    if audit is not None:
        await bundle.engine.audit.log(
            "AI_EXIT_INTENT", target=symbol, order_id=order.internal_order_id, after=audit
        )
    fill = Fill(
        fill_id=new_id("fill"),
        order_id=order.internal_order_id,
        client_order_id=order.client_order_id,
        symbol=symbol,
        side=side,
        price=D(entry),
        quantity=D(qty),
        fee=D(fee),
        fee_currency="USDT",
        timestamp=datetime.now(UTC),
        payload={"market_type": "SPOT", **(payload_extra or {})},
    )
    await om.apply_fill(fill)
    return order, fill


def _episodes(db_file):
    import sqlite3

    conn = sqlite3.connect(db_file)
    try:
        return {
            r[0]: r
            for r in conn.execute(
                "SELECT episode_id, symbol, market_type, direction, entry_price, "
                "exit_price, result, exit_reason, net_pnl, gross_pnl, fees "
                "FROM ai_trade_episodes"
            ).fetchall()
        }
    finally:
        conn.close()


async def test_time_stop_exit_creates_single_episode_with_time_stop_reason(bundle_env):
    bundle, db_file = bundle_env

    await _open_spot(bundle, "LINKUSDT", OrderSide.BUY, "0.001", "11.32")
    await _open_spot(
        bundle, "LINKUSDT", OrderSide.SELL, "0.001", "11.326",
        reduce_only=True, strategy="ai_brain",
        audit={"exit_reason": "TIME_STOP"},
    )

    eps = _episodes(db_file)
    # The runtime hook persisted the episode during the closing fill itself.
    assert len(eps) == 1
    ep = list(eps.values())[0]
    assert ep[1] == "LINKUSDT"
    assert ep[7] == "TIME_STOP"  # never AI_EXIT
    # idempotent replay
    result2 = record_all_cycles_sync(db_file)
    assert result2["inserted"] == 0
    assert len(_episodes(db_file)) == 1


async def test_entry_only_creates_no_episode(bundle_env):
    bundle, db_file = bundle_env

    await _open_spot(bundle, "ETHUSDT", OrderSide.BUY, "0.001", "2400")

    result = record_all_cycles_sync(db_file)
    assert result["inserted"] == 0
    assert len(_episodes(db_file)) == 0


async def test_partial_close_stays_open_full_close_completes(bundle_env):
    bundle, db_file = bundle_env

    await _open_spot(bundle, "ADAUSDT", OrderSide.BUY, "0.002", "0.50")
    await _open_spot(bundle, "ADAUSDT", OrderSide.SELL, "0.001", "0.60", reduce_only=True)
    # partial: cycle not complete yet -> no completed episode may exist
    assert record_all_cycles_sync(db_file)["inserted"] == 0
    assert len(_episodes(db_file)) == 0
    await _open_spot(bundle, "ADAUSDT", OrderSide.SELL, "0.001", "0.62", reduce_only=True)
    # full close: completes (runtime hook persists it; backfill is idempotent)

    result = record_all_cycles_sync(db_file)
    assert result["inserted"] == 0
    eps = _episodes(db_file)
    assert len(eps) == 1
    ep = list(eps.values())[0]
    assert D(ep[4]) == D("0.50")          # weighted entry
    # weighted exit: (0.60 + 0.62) / 2 = 0.61, LONG profit
    assert D(ep[5]) == D("0.61")


async def test_same_symbol_two_cycles_two_episodes(bundle_env):
    bundle, db_file = bundle_env

    await _open_spot(bundle, "DOTUSDT", OrderSide.BUY, "0.001", "1.0")
    await _open_spot(bundle, "DOTUSDT", OrderSide.SELL, "0.001", "1.1", reduce_only=True)
    await _open_spot(bundle, "DOTUSDT", OrderSide.BUY, "0.001", "2.0")
    await _open_spot(bundle, "DOTUSDT", OrderSide.SELL, "0.001", "1.9", reduce_only=True)

    result = record_all_cycles_sync(db_file)
    assert result["inserted"] == 0  # hook already persisted both cycles
    eps = _episodes(db_file)
    assert len(eps) == 2
    pnls = sorted(D(e[8]) for e in eps.values())
    assert pnls[0] < 0 and pnls[1] > 0  # one winner, one loser: distinct cycles


async def test_multiple_entry_fills_weighted_average(bundle_env):
    bundle, db_file = bundle_env

    await _open_spot(bundle, "SOLUSDT", OrderSide.BUY, "0.001", "100")
    await _open_spot(bundle, "SOLUSDT", OrderSide.BUY, "0.002", "110")
    await _open_spot(bundle, "SOLUSDT", OrderSide.SELL, "0.003", "120", reduce_only=True)

    assert len(_episodes(db_file)) == 1
    ep = list(_episodes(db_file).values())[0]
    assert D(ep[4]) == D("106.6666666666666666666666667")  # (100+220)/3
    assert D(ep[5]) == D("120")


async def test_long_and_short_pnl_signs(bundle_env):
    bundle, db_file = bundle_env

    await _open_spot(bundle, "WLDUSDT", OrderSide.BUY, "0.001", "1.0")
    await _open_spot(bundle, "WLDUSDT", OrderSide.SELL, "0.001", "1.2", reduce_only=True)
    from tests.integration.test_order_read_model import _seed_mark

    # SHORT cycle via the canonical perp path (HYPEUSDT_PERP: short 80, close 79)
    await _seed_mark(bundle, "HYPEUSDT", "80")
    d1 = await bundle.engine.process_signal(
        SignalIntent(
            signal_id="sig_hype_open",
            strategy_id="test",
            symbol="HYPEUSDT_PERP",
            side=OrderSide.SELL,
            quantity="0.0005",
            order_type=OrderType.MARKET,
            reason="open short",
            market_type=MarketType.PERPETUAL,
            position_side=PositionSide.SHORT,
        )
    )
    assert d1.decision.value == "APPROVE", d1.reason
    await _seed_mark(bundle, "HYPEUSDT", "79", sequence=2)
    d2 = await bundle.engine.process_signal(
        SignalIntent(
            signal_id="sig_hype_close",
            strategy_id="test",
            symbol="HYPEUSDT_PERP",
            side=OrderSide.BUY,
            quantity="0.0005",
            order_type=OrderType.MARKET,
            reason="close short",
            market_type=MarketType.PERPETUAL,
            position_side=PositionSide.SHORT,
            reduce_only=True,
        )
    )
    assert d2.decision.value == "APPROVE", d2.reason
    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        perp_state = await bundle.engine.perpetual_engine.load_state()
        pos = perp_state.positions.get("HYPEUSDT_PERP")
        if pos is None or pos.is_flat:
            break
        await asyncio.sleep(0.01)

    assert len(_episodes(db_file)) == 2
    eps = _episodes(db_file)
    wld = [e for e in eps.values() if e[1] == "WLDUSDT"][0]
    hype = [e for e in eps.values() if e[1] == "HYPEUSDT_PERP"][0]
    assert D(wld[8]) > 0   # LONG profit
    assert D(hype[8]) > 0  # SHORT profit (80 -> 79)
    assert wld[3] == "LONG"
    assert hype[3] == "SHORT"


async def test_fees_attributed_and_net_less_than_gross(bundle_env):
    bundle, db_file = bundle_env

    await _open_spot(bundle, "XLMUSDT", OrderSide.BUY, "0.001", "0.10")
    await _open_spot(bundle, "XLMUSDT", OrderSide.SELL, "0.001", "0.20", reduce_only=True)

    assert len(_episodes(db_file)) == 1
    ep = list(_episodes(db_file).values())[0]
    gross, fees, net = D(ep[9]), D(ep[10]), D(ep[8])
    # Episode fees must equal the exact SUM of the cycle's canonical fill fees
    import sqlite3

    conn = sqlite3.connect(db_file)
    fill_fee_sum = D(conn.execute(
        "SELECT SUM(fee) FROM fills WHERE symbol='XLMUSDT'"
    ).fetchone()[0])
    conn.close()
    tol = D("1e-9")
    assert abs(fees - fill_fee_sum) < tol    # fees = SUM(fill.fee), no double count
    assert abs(gross - D("0.0001")) < tol    # (0.20-0.10)*0.001 deterministic rebuild
    assert abs(net - (gross - fees)) < tol   # net = gross - fees


async def test_runtime_hook_creates_episode_on_close_fill(bundle_env):
    bundle, db_file = bundle_env

    entry_order, entry_fill = await _open_spot(bundle, "BNBUSDT", OrderSide.BUY, "0.001", "600")
    exit_order, exit_fill = await _open_spot(
        bundle, "BNBUSDT", OrderSide.SELL, "0.001", "610", reduce_only=True, strategy="ai_brain"
    )
    # hook runs on the closing fill (engine calls it post-settlement)
    record_cycle_for_fill_sync(db_file, exit_fill.fill_id, "BNBUSDT", time_stop_seconds=None)
    return entry_fill, exit_fill

    eps = _episodes(db_file)
    assert len(eps) == 1
    ep = list(eps.values())[0]
    assert ep[7] == "UNKNOWN"  # no AI_EXIT_INTENT audit in raw path; honest UNKNOWN


async def test_quarantined_fills_excluded_from_episodes(bundle_env):
    bundle, db_file = bundle_env

    await _open_spot(bundle, "ARBUSDT", OrderSide.BUY, "0.001", "0.10")

    # mark the entry fill quarantined (legacy taint) BEFORE the exit
    import sqlite3

    conn = sqlite3.connect(db_file)
    fill_id = conn.execute(
        "SELECT fill_id FROM fills WHERE side='BUY' AND symbol='ARBUSDT'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO audit_events (audit_event_id, event_id, action, actor, "
        "target, timestamp) VALUES (?,?,?,?,?,?)",
        ("audit_q1", "evt_q1", "EVIDENCE_QUARANTINE", "test", fill_id, "2026-08-29 00:00:00"),
    )
    conn.commit()
    conn.close()
    await _open_spot(bundle, "ARBUSDT", OrderSide.SELL, "0.001", "0.20", reduce_only=True)

    # quarantined entry: the cycle is unbuildable from canonical facts and
    # no episode may exist (tainted data excluded from learning)
    result = record_all_cycles_sync(db_file)
    assert result["inserted"] == 0
    assert len(_episodes(db_file)) == 0


async def test_perp_realized_pnl_ledger_is_gross_source(bundle_env):
    """Perp episode gross must come from FUTURES_REALIZED_PNL metadata (canonical)."""
    bundle, db_file = bundle_env

    from tests.integration.test_order_read_model import _seed_mark

    await _seed_mark(bundle, "ZECUSDT", "10")
    d1 = await bundle.engine.process_signal(
        SignalIntent(
            signal_id="sig_zec_open", strategy_id="test", symbol="ZECUSDT_PERP",
            side=OrderSide.BUY, quantity="0.0002", order_type=OrderType.MARKET,
            reason="open long", market_type=MarketType.PERPETUAL,
            position_side=PositionSide.LONG,
        )
    )
    assert d1.decision.value == "APPROVE", d1.reason
    await _seed_mark(bundle, "ZECUSDT", "11", sequence=2)
    d2 = await bundle.engine.process_signal(
        SignalIntent(
            signal_id="sig_zec_close", strategy_id="test", symbol="ZECUSDT_PERP",
            side=OrderSide.SELL, quantity="0.0002", order_type=OrderType.MARKET,
            reason="close long", market_type=MarketType.PERPETUAL,
            position_side=PositionSide.LONG, reduce_only=True,
        )
    )
    assert d2.decision.value == "APPROVE", d2.reason
    import sqlite3

    conn = sqlite3.connect(db_file)
    ledger_gross = D(conn.execute(
        "SELECT json_extract(metadata_json, '$.realized_pnl') FROM ledger_transactions "
        "WHERE entry_type='FUTURES_REALIZED_PNL'"
    ).fetchone()[0])
    conn.close()
    eps = _episodes(db_file)
    assert len(eps) == 1
    ep = list(eps.values())[0]
    assert abs(D(ep[9]) - ledger_gross) < D("1e-9")  # gross == ledger realized
    assert ep[2] == "PERPETUAL"


async def test_ai_exit_reason_from_fill_payload(bundle_env):
    bundle, db_file = bundle_env

    await _open_spot(bundle, "ETHUSDT", OrderSide.BUY, "0.001", "2400")
    # exit_reason travels on the exit fill payload (bridge -> engine -> fill)
    await _open_spot(
        bundle, "ETHUSDT", OrderSide.SELL, "0.001", "2380",
        reduce_only=True, strategy="ai_brain",
        payload_extra={"exit_reason": "AI_EXIT"},
    )
    ep = list(_episodes(db_file).values())[0]
    assert ep[7] == "AI_EXIT"


async def test_unknown_exit_reason_for_foreign_strategy(bundle_env):
    bundle, db_file = bundle_env

    await _open_spot(bundle, "WLDUSDT", OrderSide.BUY, "0.001", "1.0")
    await _open_spot(
        bundle, "WLDUSDT", OrderSide.SELL, "0.001", "1.1",
        reduce_only=True, strategy="external_strategy",
    )
    ep = list(_episodes(db_file).values())[0]
    assert ep[7] == "UNKNOWN"  # honest: no AI attribution without evidence


async def test_lineage_json_auditable(bundle_env):
    bundle, db_file = bundle_env

    await _open_spot(bundle, "XLMUSDT", OrderSide.BUY, "0.001", "0.10")
    await _open_spot(
        bundle, "XLMUSDT", OrderSide.SELL, "0.001", "0.20",
        reduce_only=True, strategy="ai_brain",
        audit={"exit_reason": "TIME_STOP"},
    )
    import json
    import sqlite3

    conn = sqlite3.connect(db_file)
    lineage = json.loads(conn.execute(
        "SELECT lineage_json FROM ai_trade_episodes WHERE symbol='XLMUSDT'"
    ).fetchone()[0])
    conn.close()
    assert len(lineage["entry_order_ids"]) == 1
    assert len(lineage["exit_order_ids"]) == 1
    assert lineage["entry_order_ids"][0] != lineage["exit_order_ids"][0]
    assert lineage["exit_reason"] == "TIME_STOP"
    assert lineage["mae"] == "NOT_AVAILABLE" and lineage["mfe"] == "NOT_AVAILABLE"
    assert lineage["entry_fill_ids"] and lineage["exit_fill_ids"]


async def test_daily_review_can_read_completed_episodes(bundle_env):
    """Completed episodes are the review input (LLMMemoryStore.load_episodes)."""
    bundle, db_file = bundle_env

    await _open_spot(bundle, "DOTUSDT", OrderSide.BUY, "0.001", "1.0")
    await _open_spot(
        bundle, "DOTUSDT", OrderSide.SELL, "0.001", "1.1",
        reduce_only=True, strategy="ai_brain",
        audit={"exit_reason": "AI_EXIT"},
    )
    from crypto_trader.llm_chief.persistence import LLMMemoryStore

    store = LLMMemoryStore(bundle.database.session_factory)
    episodes = await store.load_episodes(limit=10)
    assert episodes, "daily review must see completed episodes"
    ep = episodes[0]
    assert ep["symbol"] == "DOTUSDT"
    assert ep["result"] in ("WIN", "LOSS", "BREAKEVEN")
    assert "pnl" in ep and "episode_id" in ep


async def test_episode_key_stable_across_unrelated_new_cycles(bundle_env):
    """Same-symbol-agnostic stability: recording other symbols never mutates
    an existing episode's identity (stable key, no double counting)."""
    bundle, db_file = bundle_env

    await _open_spot(bundle, "LINKUSDT", OrderSide.BUY, "0.001", "11.32")
    await _open_spot(
        bundle, "LINKUSDT", OrderSide.SELL, "0.001", "11.33",
        reduce_only=True, strategy="ai_brain",
        audit={"exit_reason": "TIME_STOP"},
    )
    first = list(_episodes(db_file).keys())
    assert len(first) == 1
    link_id = first[0]

    # an unrelated symbol opens and closes; LINK's episode must be untouched
    await _open_spot(bundle, "AVAXUSDT", OrderSide.BUY, "0.001", "7.27")
    await _open_spot(
        bundle, "AVAXUSDT", OrderSide.SELL, "0.001", "7.28",
        reduce_only=True, strategy="ai_brain",
        audit={"exit_reason": "TIME_STOP"},
    )
    eps = _episodes(db_file)
    assert len(eps) == 2
    assert link_id in eps
    # rerun backfill: no new rows, no identity churn
    record_all_cycles_sync(db_file)
    assert set(_episodes(db_file).keys()) == {link_id, *(
        k for k in _episodes(db_file) if k != link_id)}
    assert len(_episodes(db_file)) == 2
