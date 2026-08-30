"""PHASE 1 (TERRA/CODEX 2026-08-30): deterministic ACKNOWLEDGED->terminal
exit-order recovery + immutable exit-attribution evidence tests.

Scope: directive-required tests that were NOT yet covered by
tests/integration/test_trx_churn_lifecycle.py (Codex-owned acceptance set):

* The DOGE-class defect (2026-08-30): a reduce-only exit order left in the
  non-terminal ACKNOWLEDGED state for 41 minutes (01:28:41 -> 02:09:35),
  while the sim exchange side had already applied the sell, producing
  local/exchange divergence caught by reconciliation. Recovery evidence:
  ord_71ffb76b REJECTED (terminal) at 02:09:35.837, retry SELL
  ord_0e9773ef FILLED at 02:09:47.036.

This file proves the same class deterministically on an ISOLATED test
database (the canonical data/crypto_trader.db is never touched):

TEST A  exit order acked but never filled  -> bridge suppresses duplicates
        while outstanding, arms a result-aware retry once the order becomes
        non-outstanding, and the retry closes the position through the REAL
        RiskEngine + ExecutionAuthority path.
TEST B  the stuck order can be driven to a terminal state (REJECTED) and
        the recovery retry is the ONLY filled exit (no duplicates).
TEST C  exit-attribution is evidence-bound: durable fill-payload /
        AI_EXIT_INTENT lineage wins; with NO evidence and a short holding
        time the honest UNKNOWN is kept (never silently relabelled), while
        the legacy fallback requires >= 95% of the configured time-stop
        window.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from crypto_trader.governance.trade_episodes import _exit_reason_for
from tests.integration.test_exit_lifecycle import _make_bridge, _open_spot_position
from tests.integration.test_perpetual_runtime_routing import _make_bundle


async def _wait_until(predicate, timeout_seconds=5.0, interval=0.02):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(interval)
    return False


async def test_acknowledged_exit_suppresses_duplicates_then_recovers(database):
    """TEST A/B: acked-but-never-filled exit stays suppressed while
    outstanding, reaches a terminal state deterministically, and the
    result-aware retry closes the position exactly once."""
    bundle = await _make_bundle(database)
    try:
        await _open_spot_position(bundle, "ETHUSDT")
        bridge = await _make_bridge(bundle.engine)
        bridge._first_seen_open["ETHUSDT"] = datetime.now(UTC) - timedelta(hours=2)

        # Hijack ONLY the exchange submit leg: the engine's own lifecycle
        # (create -> validate -> submitting -> submitted -> ack) runs for
        # real, but the exchange never delivers a fill. The order lands in
        # the exact DOGE state: ACKNOWLEDGED, non-terminal, no fills.
        stuck: dict = {}
        real_submit = bundle.engine.adapter.submit_order

        async def stuck_submit(order):
            stuck["order_id"] = order.internal_order_id
            stuck["exchange_order_id"] = f"sim_stuck_{order.internal_order_id}"
            return SimpleNamespace(
                exchange_order_id=stuck["exchange_order_id"],
                status=SimpleNamespace(value="ACKNOWLEDGED"),
            )

        bundle.engine.adapter.submit_order = stuck_submit  # type: ignore[method-assign]
        try:
            evaluations = await bridge.evaluate_active_positions(
                bundle.engine, bundle.portfolio
            )
        finally:
            bundle.engine.adapter.submit_order = real_submit  # type: ignore[method-assign]

        exits = [e for e in evaluations if e.action == "EXIT"]
        assert exits, "time-stop must produce an EXIT evaluation"
        assert exits[0].reduce_only is True and exits[0].side == "SELL"

        order = await bundle.engine.order_manager.get(stuck["order_id"])
        assert order is not None
        assert order.status.value == "ACKNOWLEDGED", (
            f"expected the DOGE-class stuck state, got {order.status.value}"
        )

        # While outstanding (ACKNOWLEDGED is in list_open), the bridge must
        # NOT fire a duplicate EXIT for the same symbol.
        evals2 = await bridge.evaluate_active_positions(bundle.engine, bundle.portfolio)
        assert not [e for e in evals2 if e.action == "EXIT"], (
            "duplicate EXIT while the first is outstanding is forbidden"
        )
        assert "ETHUSDT" in bridge._exit_in_flight
        assert not any(
            h.get("action") == "EXIT_RETRY_ARMED" for h in bridge.decision_history
        ), "retry must not arm while the order is genuinely outstanding"

        # Deterministic terminal transition (mirrors the DOGE recovery:
        # ACKNOWLEDGED -> REJECTED after 41 minutes; here driven explicitly
        # so the test is deterministic, not wall-clock dependent).
        await bundle.engine.order_manager.reject(
            stuck["order_id"], "deterministic terminal (test)"
        )
        order = await bundle.engine.order_manager.get(stuck["order_id"])
        assert order.status.value == "REJECTED"

        # Next bridge round: the order is no longer outstanding while the
        # position is still open -> retry arms and a fresh reduce-only EXIT
        # fires through the REAL adapter path.
        evals3 = await bridge.evaluate_active_positions(bundle.engine, bundle.portfolio)
        assert any(e.action == "EXIT" for e in evals3), (
            "result-aware retry must re-arm the exit once the stuck order is terminal"
        )
        assert any(
            h.get("action") == "EXIT_RETRY_ARMED" for h in bridge.decision_history
        )

        async def _flat():
            positions = await bundle.engine.portfolio.get_positions()
            pos = positions.get("ETHUSDT")
            return pos is None or float(pos.quantity or 0) == 0

        assert await _wait_until(_flat), "retry exit must close the position"

        rows = []
        from sqlalchemy import text

        async with bundle.database.session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT status FROM orders WHERE symbol='ETHUSDT' "
                        "AND strategy_id='ai_brain' AND reduce_only=1 "
                        "ORDER BY created_at"
                    )
                )
            ).all()
        statuses = [r[0] for r in rows]
        assert statuses.count("FILLED") == 1, (
            f"exactly one settled reduce-only exit allowed, got {statuses}"
        )
        assert "REJECTED" in statuses, "the stuck attempt must remain as evidence"

        # One more bridge round: the position is now flat, so the in-flight
        # marker must converge (no permanent suppression of the symbol).
        await bridge.evaluate_active_positions(bundle.engine, bundle.portfolio)
        assert "ETHUSDT" not in bridge._exit_in_flight
    finally:
        await bundle.engine.stop()


def test_exit_attribution_is_evidence_bound_and_honest():
    """Immutable attribution rule: durable lineage wins; absent evidence
    keeps the honest UNKNOWN; the legacy TIME_STOP fallback requires >=95%
    of the configured window. This is the rule the 6.47s TRX episode label
    must satisfy before TIME_STOP can be accepted (currently PENDING)."""
    entry_short = "2026-08-30T00:40:45Z"
    # 7s holding to the exit timestamp baked into the fill fixture below.
    fill_payload = {
        "order_id": "ord_x",
        "strategy_id": "ai_brain",
        "payload": {},
        "timestamp": "2026-08-30T00:40:52Z",
    }

    # Evidence path 1: durable fill-payload lineage (from SignalIntent
    # metadata via the engine's fill enrichment) is authoritative.
    fills = [dict(fill_payload, payload={"exit_reason": "TIME_STOP"})]
    assert (
        _exit_reason_for(fills, {}, entry_ts=entry_short, time_stop_seconds=14400)
        == "TIME_STOP"
    )

    # Evidence path 2: durable AI_EXIT_INTENT audit mapping is authoritative.
    fills = [dict(fill_payload)]
    assert (
        _exit_reason_for(fills, {"ord_x": "AI_EXIT"}, entry_ts=entry_short, time_stop_seconds=14400)
        == "AI_EXIT"
    )

    # NO evidence + short holding -> honest UNKNOWN; never invented.
    assert (
        _exit_reason_for(fills, {}, entry_ts=entry_short, time_stop_seconds=14400)
        == "UNKNOWN"
    )

    # NO evidence + holding >= 95% of the window + pure bridge strategy ->
    # legacy TIME_STOP fallback (exit timestamp lives in the fill fixture:
    # 00:40:52Z vs the long entry below = ~4h holding).
    entry_long = "2026-08-29T20:40:00Z"
    assert (
        _exit_reason_for(fills, {}, entry_ts=entry_long, time_stop_seconds=14400)
        == "TIME_STOP"
    )

    # Non-bridge strategies never get the legacy fallback.
    fills_chief = [dict(fill_payload, strategy_id="llm_chief_trader")]
    assert (
        _exit_reason_for(fills_chief, {}, entry_ts=entry_long, time_stop_seconds=14400)
        != "TIME_STOP"
    )
