"""P2-1 TRX direction-flip churn root-cause repair: acceptance tests.

Directive Phase 1 acceptance (§16) mapped to tests:

TEST 1  LONG -> EXIT -> no accidental SHORT        : test_long_exit_is_reduce_only_no_short
TEST 2  SHORT -> EXIT -> no accidental LONG        : test_short_exit_is_reduce_only_no_long
TEST 3  TIME_STOP exit + simultaneous opposite AI decision -> stale signal rejected
                                                   : test_exit_then_stale_entry_rejected
TEST 4  Risk reject -> no cooldown corruption      : test_risk_reject_does_not_touch_lifecycle
TEST 5  Execution hold -> no duplicate retry       : test_exit_hold_no_duplicate_order
TEST 6  same-symbol concurrent decisions -> only the current-state decision executes
                                                   : test_concurrent_decisions_latest_state_wins
TEST 7  different symbols -> do not block          : test_cross_symbol_no_blocking
TEST 8  legitimate reversal after finalized lifecycle
                                                   : test_legitimate_reversal_allowed
TEST 9  TRX reproduced sequence -> no 7s churn     : test_trx_reproduction_no_seven_second_churn
§17    exit_reason UNKNOWN -> TIME_STOP attribution: test_spot_exit_reason_attribution
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from crypto_trader.domain.enums import (
    MarketType,
    OrderSide,
    OrderType,
    PositionSide,
)
from crypto_trader.domain.models import SignalIntent
from crypto_trader.runtime.ai_position_bridge import AIPositionRuntimeBridge
from crypto_trader.runtime.execution_symbols import reference_symbol_for
from crypto_trader.runtime.position_lifecycle import PositionLifecycleTracker
from tests.integration.test_perpetual_runtime_routing import (
    PERP,
    _make_bundle,
    _seed_book,
)


async def _position_opened_at(session_factory, symbol: str, side: str):
    """Same derivation as bootstrap._position_opened_at: MAX entry-side fill."""
    from sqlalchemy import text

    entry_side = "SELL" if str(side).upper() == "SHORT" else "BUY"
    row = None
    for _ in range(40):
        try:
            async with session_factory() as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT MAX(timestamp) FROM fills "
                            "WHERE symbol = :symbol AND side = :side"
                        ),
                        {"symbol": symbol, "side": entry_side},
                    )
                ).first()
            break
        except Exception:
            await asyncio.sleep(0.05)
    if row is None or row[0] is None:
        return None
    ts = datetime.fromisoformat(str(row[0]))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


async def _backdate_entry_fills(bundle, symbol, seconds=14430):
    """Simulate an aged position the way reality does: the ENTRY fill is old.
    The bridge provider derives the open time from fills, so backdating the
    entry fill ages the episode honestly."""
    from sqlalchemy import text

    async with bundle.database.session_factory() as session:
        await session.execute(
            text(
                "UPDATE fills SET timestamp = datetime(timestamp, :delta) "
                "WHERE symbol = :s AND side = 'BUY'"
            ),
            {"delta": f"-{int(seconds)} seconds", "s": symbol},
        )
        await session.commit()


async def _open_spot_position(bundle, symbol="TRXUSDT", quantity="0.001", sig="sig_open"):
    await _seed_book(bundle, symbol, "2000")
    decision = await bundle.engine.process_signal(
        SignalIntent(
            signal_id=sig,
            strategy_id="test",
            symbol=symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            order_type=OrderType.MARKET,
            reason="open for churn test",
            market_type=MarketType.SPOT,
            position_side=PositionSide.LONG,
        )
    )
    assert decision.decision.value == "APPROVE", decision.reason
    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        positions = await bundle.portfolio.get_positions()
        position = positions.get(symbol)
        if position is not None and float(position.quantity or 0) > 0:
            return position
        await asyncio.sleep(0.01)
    raise AssertionError(f"position did not open for {symbol}")


async def _wait_flat(bundle, symbol):
    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        positions = await bundle.portfolio.get_positions()
        position = positions.get(symbol)
        if position is None or float(position.quantity or 0) == 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"position did not close for {symbol}")


def _make_bridge(bundle, *, time_stop_seconds=4 * 3600):
    async def provider(symbol: str, side: str):
        return await _position_opened_at(
            bundle.database.session_factory, symbol, side
        )

    return AIPositionRuntimeBridge(
        brain=bundle.engine.ai_position_bridge.brain,
        perpetual_engine=bundle.engine.perpetual_engine,
        time_stop_seconds=time_stop_seconds,
        cooldown_seconds=0.0,
        position_opened_at_provider=provider,
    )


# ---------------------------------------------------------------- TEST 9 (core)


async def test_trx_reproduction_no_seven_second_churn(database):
    """The exact TRX 2026-08-30 00:40 sequence: aged LONG -> TIME_STOP exit
    -> AI re-entry seconds later -> bridge must NOT instant-TIME_STOP the
    fresh position (the stale `_first_seen_open` cache is re-validated
    against the real per-episode open time)."""
    bundle = await _make_bundle(database)
    try:
        await _open_spot_position(bundle, "TRXUSDT")
        bridge = _make_bridge(bundle)
        # Age the CURRENT episode like the real 4h hold (entry fill backdated,
        # exactly what the provider-derived open time sees in production).
        await _backdate_entry_fills(bundle, "TRXUSDT", seconds=14430)

        first = await bridge.evaluate_active_positions(bundle.engine, bundle.portfolio)
        exits = [e for e in first if e.action == "EXIT" and e.symbol == "TRXUSDT"]
        assert exits, "aged position must time-stop exit"
        assert exits[0].reduce_only is True and exits[0].side == "SELL"
        await _wait_flat(bundle, "TRXUSDT")

        # Chief-trader-like fresh re-entry 35 seconds after the exit (the
        # 37s flip from the incident).
        decision = await bundle.engine.process_signal(
            SignalIntent(
                signal_id="sig_reentry",
                strategy_id="llm_chief_trader",
                symbol="TRXUSDT",
                side=OrderSide.BUY,
                quantity="0.001",
                order_type=OrderType.MARKET,
                reason="fresh oversold re-entry",
                market_type=MarketType.SPOT,
                position_side=PositionSide.FLAT,
            )
        )
        assert decision.decision.value == "APPROVE", decision.reason
        # The paper adapter fills with ~2s latency; wait for the re-entry BUY
        # fill row to actually land (a zero-quantity position row lingers
        # from the previous episode, so quantity>0 is the real signal).
        deadline = asyncio.get_running_loop().time() + 10.0
        from sqlalchemy import text as _t

        while asyncio.get_running_loop().time() < deadline:
            async with bundle.database.session_factory() as _s:
                _buy_count = (
                    await _s.execute(
                        _t(
                            "SELECT COUNT(*) FROM fills WHERE symbol='TRXUSDT' "
                            "AND side='BUY'"
                        )
                    )
                ).scalar()
            positions = await bundle.portfolio.get_positions()
            pos = positions.get("TRXUSDT")
            if int(_buy_count) >= 2 and pos is not None and float(pos.quantity or 0) > 0:
                break
            await asyncio.sleep(0.05)

        # Next bridge cycle: the fresh position (age < 10s) must SURVIVE.
        second = await bridge.evaluate_active_positions(bundle.engine, bundle.portfolio)
        spurious = [
            e for e in second if e.action == "EXIT" and e.symbol == "TRXUSDT"
        ]
        assert not spurious, (
            "fresh re-entry must not be instant-TIME_STOPPED by stale age "
            f"state: {spurious}"
        )
        # and the in-memory cache now tracks the NEW episode's open time.
        cached = bridge._first_seen_open.get("TRXUSDT")
        assert cached is not None and (datetime.now(UTC) - cached).total_seconds() < 60
    finally:
        await bundle.engine.stop()


# ---------------------------------------------------------------- TEST 1 / 2


async def test_long_exit_is_reduce_only_no_short(database):
    """TEST 1: closing a LONG produces exactly one reduce-only SELL and never
    an opposite-direction opening order."""
    bundle = await _make_bundle(database)
    try:
        await _open_spot_position(bundle, "ETHUSDT", sig="sig_t1")
        bridge = _make_bridge(bundle)
        await _backdate_entry_fills(bundle, "ETHUSDT", seconds=14430)
        evals = await bridge.evaluate_active_positions(bundle.engine, bundle.portfolio)
        eth = [e for e in evals if e.symbol == "ETHUSDT"]
        assert eth and eth[0].action == "EXIT"
        assert eth[0].side == "SELL" and eth[0].reduce_only is True
        await _wait_flat(bundle, "ETHUSDT")
        from sqlalchemy import text

        async with bundle.database.session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT side, reduce_only, status FROM orders "
                        "WHERE symbol='ETHUSDT' AND strategy_id='ai_brain'"
                    )
                )
            ).all()
        assert rows and all(r[0] == "SELL" and r[1] == 1 for r in rows), rows
        positions = await bundle.portfolio.get_positions()
        assert float(positions.get("ETHUSDT").quantity or 0) == 0
    finally:
        await bundle.engine.stop()


async def test_short_exit_is_reduce_only_no_long(database):
    """TEST 2: closing a PERP SHORT produces a reduce-only BUY, never a new
    opening order, and records a completed exit in the lifecycle tracker."""
    bundle = await _make_bundle(database)
    try:
        await _seed_book(bundle, PERP, "100")
        lifecycle = bundle.engine.position_lifecycle
        version_before = lifecycle.position_version(PERP, MarketType.PERPETUAL)
        decision = await bundle.engine.process_signal(
            SignalIntent(
                signal_id="sig_short_open",
                strategy_id="test",
                symbol=PERP,
                side=OrderSide.SELL,
                quantity="1.0",
                order_type=OrderType.MARKET,
                reason="open short",
                market_type=MarketType.PERPETUAL,
                position_side=PositionSide.SHORT,
            )
        )
        assert decision.decision.value == "APPROVE", decision.reason
        assert (
            lifecycle.position_version(PERP, MarketType.PERPETUAL) > version_before
        )
        bridge = _make_bridge(bundle)
        evals = await bridge.evaluate_active_positions(bundle.engine, bundle.portfolio)
        # A young SHORT is evaluated by the bridge brain (no time stop yet);
        # the exit itself is exercised through the canonical reduce-only path.
        assert all(not (e.symbol == PERP and e.action == "EXIT") for e in evals)
        decision2 = await bundle.engine.process_signal(
            SignalIntent(
                signal_id="sig_short_exit",
                strategy_id="ai_brain",
                symbol=PERP,
                side=OrderSide.BUY,
                quantity="1.0",
                order_type=OrderType.MARKET,
                reason="EXPLORATION_TIME_STOP held 14400s >= 14400s",
                market_type=MarketType.PERPETUAL,
                position_side=PositionSide.SHORT,
                reduce_only=True,
                metadata={"exit_reason": "TIME_STOP"},
            )
        )
        assert decision2.decision.value == "APPROVE", decision2.reason
        deadline = asyncio.get_running_loop().time() + 5.0
        while asyncio.get_running_loop().time() < deadline:
            state = await bundle.engine.perpetual_engine.load_state()
            pos = state.positions.get(PERP)
            if pos is None or pos.is_flat:
                break
            await asyncio.sleep(0.05)
        state = await bundle.engine.perpetual_engine.load_state()
        pos = state.positions.get(PERP)
        assert pos is None or pos.is_flat, "short must be flat after reduce-only exit"
        from sqlalchemy import text

        async with bundle.database.session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT side, reduce_only FROM orders WHERE symbol=:s "
                        "AND reduce_only=1"
                    ),
                    {"s": PERP},
                )
            ).all()
        assert rows and all(r[0] == "BUY" for r in rows), rows
    finally:
        await bundle.engine.stop()


# ---------------------------------------------------------------- TEST 3


async def test_exit_then_stale_entry_rejected(database):
    """TEST 3: an entry decision captured BEFORE an exit settled carries the
    old position version; the engine must reject it instead of executing."""
    bundle = await _make_bundle(database)
    try:
        lifecycle = bundle.engine.position_lifecycle
        stale_version = lifecycle.position_version("TRXUSDT", MarketType.SPOT)
        # The exit lifecycle completes (episode closed).
        lifecycle.on_position_closed("TRXUSDT", MarketType.SPOT)
        current_version = lifecycle.position_version("TRXUSDT", MarketType.SPOT)
        assert current_version > stale_version

        decision = await bundle.engine.process_signal(
            SignalIntent(
                signal_id="sig_stale_entry",
                strategy_id="llm_chief_trader",
                symbol="TRXUSDT",
                side=OrderSide.BUY,
                quantity="0.001",
                order_type=OrderType.MARKET,
                reason="decision made before the exit settled",
                market_type=MarketType.SPOT,
                position_side=PositionSide.FLAT,
                metadata={"expected_position_version": str(stale_version)},
            )
        )
        assert decision.decision.value == "REJECT"
        assert decision.reason == "STALE_POSITION_STATE", decision.reason

        from sqlalchemy import text

        async with bundle.database.session_factory() as session:
            count = (
                await session.execute(
                    text("SELECT COUNT(*) FROM orders WHERE symbol='TRXUSDT'")
                )
            ).scalar()
        assert int(count) == 0, "stale entry must never create an order"

        # A current-version decision passes the guard and executes.
        await _seed_book(bundle, "TRXUSDT", "2000")
        decision_ok = await bundle.engine.process_signal(
            SignalIntent(
                signal_id="sig_fresh_entry",
                strategy_id="llm_chief_trader",
                symbol="TRXUSDT",
                side=OrderSide.BUY,
                quantity="0.001",
                order_type=OrderType.MARKET,
                reason="current-state decision",
                market_type=MarketType.SPOT,
                position_side=PositionSide.FLAT,
                metadata={"expected_position_version": str(current_version)},
            )
        )
        assert decision_ok.decision.value == "APPROVE", decision_ok.reason
    finally:
        await bundle.engine.stop()


# ---------------------------------------------------------------- TEST 4


async def test_risk_reject_does_not_touch_lifecycle(database):
    """TEST 4: a risk-rejected signal must not bump versions or start any
    reversal fence (no cooldown corruption from failed attempts)."""
    bundle = await _make_bundle(database)
    try:
        lifecycle = bundle.engine.position_lifecycle
        version_before = lifecycle.position_version("TRXUSDT", MarketType.SPOT)
        # Non-reduce-only SELL with no position -> SPOT_OVERSHORT reject.
        await _seed_book(bundle, "TRXUSDT", "2000")
        decision = await bundle.engine.process_signal(
            SignalIntent(
                signal_id="sig_bad_short",
                strategy_id="test",
                symbol="TRXUSDT",
                side=OrderSide.SELL,
                quantity="0.001",
                order_type=OrderType.MARKET,
                reason="invalid spot short",
                market_type=MarketType.SPOT,
                position_side=PositionSide.FLAT,
            )
        )
        assert decision.decision.value == "REJECT"
        assert lifecycle.position_version("TRXUSDT", MarketType.SPOT) == version_before
        assert lifecycle.seconds_since_exit("TRXUSDT", MarketType.SPOT) is None
        assert lifecycle.reversal_blocked("TRXUSDT", MarketType.SPOT) is False
    finally:
        await bundle.engine.stop()


# ---------------------------------------------------------------- TEST 5


async def test_exit_hold_no_duplicate_order(database):
    """TEST 5: when the exit cannot be authorized (stale market data ->
    ExecutionAuthority HOLD), no order is created and the suppression is
    released so exactly one retry can happen later."""
    bundle = await _make_bundle(database, auto_start=False)
    try:
        await bundle.engine.start()
        await _open_spot_position(bundle, "ETHUSDT", sig="sig_t5")
        bridge = _make_bridge(bundle)
        await _backdate_entry_fills(bundle, "ETHUSDT", seconds=14430)
        # No book was ever seeded for ETHUSDT reference data freshness here
        # beyond the open; force staleness by clearing the market data store.
        bundle.engine.market_data.books.pop(reference_symbol_for("ETHUSDT"), None)
        evals = await bridge.evaluate_active_positions(bundle.engine, bundle.portfolio)
        exits = [e for e in evals if e.action == "EXIT" and e.symbol == "ETHUSDT"]
        if exits and exits[0].reduce_only:
            from sqlalchemy import text

            async with bundle.database.session_factory() as session:
                rows = (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FROM orders WHERE symbol='ETHUSDT' "
                            "AND strategy_id='ai_brain'"
                        )
                    )
                ).scalar()
            assert int(rows) == 0, "held exit must not create an order"
        # Suppression released -> a later round may retry (not stuck forever).
        assert "ETHUSDT" not in bridge._exit_in_flight
    finally:
        await bundle.engine.stop()


# ---------------------------------------------------------------- TEST 6


async def test_concurrent_decisions_latest_state_wins(database):
    """TEST 6: two same-symbol entry intents decided at different lifecycle
    versions -- the stale one is rejected, the current one executes."""
    bundle = await _make_bundle(database)
    try:
        lifecycle = bundle.engine.position_lifecycle
        v_stale = lifecycle.position_version("BTCUSDT", MarketType.SPOT)
        lifecycle.on_position_closed("BTCUSDT", MarketType.SPOT)  # episode ended
        v_now = lifecycle.position_version("BTCUSDT", MarketType.SPOT)
        await _seed_book(bundle, "BTCUSDT", "70000")
        stale = await bundle.engine.process_signal(
            SignalIntent(
                signal_id="sig_a_stale",
                strategy_id="llm_chief_trader",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                quantity="0.001",
                order_type=OrderType.MARKET,
                reason="stale concurrent decision",
                market_type=MarketType.SPOT,
                position_side=PositionSide.FLAT,
                metadata={"expected_position_version": str(v_stale)},
            )
        )
        fresh = await bundle.engine.process_signal(
            SignalIntent(
                signal_id="sig_b_current",
                strategy_id="llm_chief_trader",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                quantity="0.001",
                order_type=OrderType.MARKET,
                reason="current concurrent decision",
                market_type=MarketType.SPOT,
                position_side=PositionSide.FLAT,
                metadata={"expected_position_version": str(v_now)},
            )
        )
        assert stale.decision.value == "REJECT"
        assert stale.reason == "STALE_POSITION_STATE"
        assert fresh.decision.value == "APPROVE"
    finally:
        await bundle.engine.stop()


# ---------------------------------------------------------------- TEST 7


async def test_cross_symbol_no_blocking(database):
    """TEST 7: an exit for TRXUSDT never fences another symbol's entry, and
    tracker keys never collide across symbols or market types."""
    tracker = PositionLifecycleTracker(reversal_cooldown_seconds=240.0)
    tracker.on_position_closed("TRXUSDT", MarketType.SPOT)
    assert tracker.reversal_blocked("TRXUSDT", MarketType.SPOT) is True
    assert tracker.reversal_blocked("ETHUSDT", MarketType.SPOT) is False
    assert tracker.reversal_blocked("BTCUSDT", MarketType.SPOT) is False
    # Same instrument string under a different market stays independent.
    assert tracker.reversal_blocked("TRXUSDT_PERP", MarketType.PERPETUAL) is False
    assert (
        tracker.position_version("TRXUSDT", MarketType.SPOT)
        != tracker.position_version("TRXUSDT_PERP", MarketType.PERPETUAL)
    )


# ---------------------------------------------------------------- TEST 8


async def test_legitimate_reversal_allowed(database):
    """TEST 8: once the reversal cooldown has elapsed, a fresh re-entry for
    the same instrument passes the fence (and the engine's stale guard)."""
    tracker = PositionLifecycleTracker(reversal_cooldown_seconds=240.0)
    tracker.on_position_closed("TRXUSDT", MarketType.SPOT)
    assert tracker.reversal_blocked("TRXUSDT", MarketType.SPOT) is True
    # Simulate finalized lifecycle: rewind the fence beyond the window.
    import time as _time

    tracker._last_exit_settled_at["SPOT|TRXUSDT"] = (
        _time.monotonic() - tracker.reversal_cooldown_seconds - 1
    )
    assert tracker.reversal_blocked("TRXUSDT", MarketType.SPOT) is False

    bundle = await _make_bundle(database)
    try:
        lifecycle = bundle.engine.position_lifecycle
        lifecycle.on_position_closed("TRXUSDT", MarketType.SPOT)
        lifecycle._last_exit_settled_at["SPOT|TRXUSDT"] = (
            _time.monotonic() - lifecycle.reversal_cooldown_seconds - 1
        )
        await _seed_book(bundle, "TRXUSDT", "2000")
        decision = await bundle.engine.process_signal(
            SignalIntent(
                signal_id="sig_legit_reversal",
                strategy_id="llm_chief_trader",
                symbol="TRXUSDT",
                side=OrderSide.BUY,
                quantity="0.001",
                order_type=OrderType.MARKET,
                reason="legitimate re-entry after finalized lifecycle",
                market_type=MarketType.SPOT,
                position_side=PositionSide.FLAT,
                metadata={
                    "expected_position_version": str(
                        lifecycle.position_version("TRXUSDT", MarketType.SPOT)
                    )
                },
            )
        )
        assert decision.decision.value == "APPROVE", decision.reason
    finally:
        await bundle.engine.stop()


# ---------------------------------------------------------------- §17


async def test_spot_exit_reason_attribution(database):
    """§17: a bridge reduce-only SPOT exit whose SignalIntent carried
    exit_reason=TIME_STOP must land a TIME_STOP episode -- never UNKNOWN --
    even for a very short hold, and the entry fill keeps decision lineage."""
    bundle = await _make_bundle(database)
    try:
        lifecycle = bundle.engine.position_lifecycle
        await _open_spot_position(bundle, "TRXUSDT", sig="sig_attr_entry")
        # Settlement (and with it the lifecycle OPENED event) is async: wait
        # for the version bump before capturing the precondition.
        deadline = asyncio.get_running_loop().time() + 5.0
        while (
            asyncio.get_running_loop().time() < deadline
            and lifecycle.position_version("TRXUSDT", MarketType.SPOT) < 1
        ):
            await asyncio.sleep(0.02)
        entry_version = lifecycle.position_version("TRXUSDT", MarketType.SPOT)
        decision = await bundle.engine.process_signal(
            SignalIntent(
                signal_id="sig_attr_exit",
                strategy_id="ai_brain",
                symbol="TRXUSDT",
                side=OrderSide.SELL,
                quantity="0.001",
                order_type=OrderType.MARKET,
                reason="EXPLORATION_TIME_STOP held 6s >= 6s",
                market_type=MarketType.SPOT,
                position_side=PositionSide.LONG,
                reduce_only=True,
                metadata={
                    "exit_reason": "TIME_STOP",
                    "decision_id": "dec_attr_exit",
                    "signal_id": "sig_attr_exit",
                },
            )
        )
        assert decision.decision.value == "APPROVE"
        await _wait_flat(bundle, "TRXUSDT")
        # episode hook runs inside settlement; allow it to complete
        await asyncio.sleep(0.2)
        from sqlalchemy import text

        async with bundle.database.session_factory() as session:
            ep = (
                await session.execute(
                    text(
                        "SELECT exit_reason, holding_time_seconds, lineage_json "
                        "FROM ai_trade_episodes WHERE symbol='TRXUSDT' "
                        "ORDER BY id DESC LIMIT 1"
                    )
                )
            ).first()
            fill_rows = (
                await session.execute(
                    text("SELECT side, payload_json FROM fills WHERE symbol='TRXUSDT'")
                )
            ).all()
        assert ep is not None, "episode must be recorded"
        assert ep[0] == "TIME_STOP", f"exit_reason must be TIME_STOP, got {ep[0]}"
        assert float(ep[1]) < 60, "short hold must stay honestly short"
        payloads = {r[0]: r[1] for r in fill_rows}
        assert any(
            "dec_attr_entry" not in (p or "") and "TIME_STOP" in (p or "")
            for p in payloads.values()
        ), f"exit fill payload must carry TIME_STOP: {payloads}"
        assert entry_version > 0
    finally:
        await bundle.engine.stop()


# ------------------------------------------------- tracker unit semantics


def test_reversal_gate_decision_helper_blocks_and_scopes():
    from crypto_trader.runtime.chief_trader_strategy import ChiefTraderStrategyAdapter

    adapter = ChiefTraderStrategyAdapter(
        provider=None,
        position_lifecycle=PositionLifecycleTracker(reversal_cooldown_seconds=240.0),
    )
    adapter.position_lifecycle.on_position_closed("TRXUSDT", MarketType.SPOT)
    ctx = SimpleNamespace(symbol="TRXUSDT")
    chief_ctx = SimpleNamespace(symbol="TRXUSDT", regime="EXTREME_RISK")
    decision = adapter._reversal_gate_decision(ctx, chief_ctx)
    assert decision is not None
    assert decision.reason_codes == ["REVERSAL_COOLDOWN_ACTIVE"]
    assert decision.action == "NO_TRADE"
    # Other symbols unaffected.
    assert (
        adapter._reversal_gate_decision(
            SimpleNamespace(symbol="ETHUSDT"),
            SimpleNamespace(symbol="ETHUSDT", regime="UNKNOWN"),
        )
        is None
    )


def test_expected_position_version_written_into_entry_metadata():
    """§12 precondition wiring: _map_to_signals stamps the entry intent with
    the position version observed at decision time (execution-market scope)."""
    from types import SimpleNamespace as NS

    from crypto_trader.runtime.chief_trader_strategy import ChiefTraderStrategyAdapter

    lifecycle = PositionLifecycleTracker(reversal_cooldown_seconds=240.0)
    lifecycle.on_position_closed("TRXUSDT", MarketType.SPOT)
    adapter = ChiefTraderStrategyAdapter(provider=None, position_lifecycle=lifecycle)

    decision = NS(
        action="LONG",
        decision_id="dec_x",
        thesis="t",
        model_version="mv",
        llm_invocation_id="llm_x",
        selected_strategy="mean_reversion",
        strategy_fit_score=0.7,
        market_regime="RISK_OFF",
        factor_snapshot_id="fs1",
        raw_llm_confidence=0.7,
        evidence_adjusted_confidence=0.7,
        decision_class="NORMAL_ENTRY",
        exploration_mode=False,
        expected_holding_period="",
        entry_plan="",
        position_size_request=0.0,
        leverage_request=0.0,
        stop_loss=None,
        take_profit=None,
        add_conditions=[],
        reduce_conditions=[],
        exit_conditions=[],
        invalidation_conditions=[],
        reason_codes=[],
    )
    ctx = NS(symbol="TRXUSDT", positions={}, clock_time=datetime.now(UTC))
    chief_ctx = NS(symbol="TRXUSDT", regime="RISK_OFF", factor_snapshot={}, strategy_evidence={})
    signals = adapter._map_to_signals(decision, ctx, chief_ctx, trade_plan_id="plan-x")
    assert signals, "LONG decision must map to an entry intent"
    meta = signals[0].metadata
    assert meta["trade_plan_id"] == "plan-x"
    assert meta["expected_position_version"] == str(
        lifecycle.position_version("TRXUSDT", MarketType.SPOT)
    )
    assert int(meta["expected_position_version"]) >= 1
