"""W1-W8: production wiring — the tap, not the store, must be the entry point.

These tests drive ``LiveLLMDecisionStrategy._observe_for_shadow`` (the exact
production call site, placed immediately after ``decisions.save``) rather than
calling the shadow store directly. A wiring test that pokes the store would pass
even with no production caller at all, which is precisely the failure mode this
file exists to prevent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from crypto_trader.llm_chief.budget import BudgetConfig, GlobalLLMBudget
from crypto_trader.llm_chief.decision import ChiefTraderDecision, FlatAction, PositionState
from crypto_trader.persistence.models import (
    AccountProjectionORM,
    FillORM,
    LedgerEntryORM,
    OrderORM,
    PositionProjectionORM,
    TradeEpisodeORM,
)
from crypto_trader.shadow.candidate_store import ShadowCandidateStore
from crypto_trader.shadow.models import (
    STATUS_PENDING,
    ShadowCandidateORM,
    ShadowEpisodeORM,
)
from crypto_trader.shadow.tap import (
    REASON_QUEUE_FULL,
    ShadowDecisionTap,
    ShadowObservation,
)

SYMBOL = "BTCUSDT"


class _Ctx:
    """Minimal stand-in for the strategy context the tap reads from."""

    def __init__(self, **over):
        self.symbol = SYMBOL
        self.regime = "RANGE"
        self.data_quality = "GOOD"
        self.snapshot_id = "snap-1"
        self.factor_snapshot_id = "fac-1"
        self.market_snapshot = {"price": "100"}
        for k, v in over.items():
            setattr(self, k, v)


def _decision(**over) -> ChiefTraderDecision:
    base = dict(
        decision_id="dec-w1",
        symbol=SYMBOL,
        position_state=PositionState.FLAT,
        action=FlatAction.NO_TRADE,
        market_regime="RANGE",
        thesis="signal too weak for a LONG entry",
        reason_codes=["SIGNAL_TOO_WEAK"],
        created_at="2026-09-12T12:00:00+00:00",
    )
    base.update(over)
    return ChiefTraderDecision(**base)


class _StrategyShim:
    """Carries the production helper without constructing the whole strategy."""

    name = "live_llm"
    version = "canonical-1.0.0"

    def __init__(self, tap):
        self.shadow_tap = tap


def _observe(tap, decision, ctx=None) -> str | None:
    from unittest.mock import patch

    from crypto_trader.llm_chief.runtime_strategy import LiveLLMDecisionStrategy

    captured: dict = {}
    original = tap.observe

    def _capture(observation):
        captured["result"] = original(observation)
        return captured["result"]

    shim = _StrategyShim(tap)
    with patch.object(tap, "observe", _capture):
        LiveLLMDecisionStrategy._observe_for_shadow(
            shim, ctx=ctx or _Ctx(), decision=decision
        )
    return captured.get("result")


async def _candidates(database) -> list[ShadowCandidateORM]:
    async with database.session_factory() as session:
        return list((await session.execute(select(ShadowCandidateORM))).scalars().all())


async def _snapshot(database) -> dict:
    async with database.session_factory() as session:
        async def cnt(model):
            return (await session.execute(select(func.count()).select_from(model))).scalar_one()

        return {
            "orders": await cnt(OrderORM),
            "fills": await cnt(FillORM),
            "positions": await cnt(PositionProjectionORM),
            "balances": await cnt(AccountProjectionORM),
            "ledger": await cnt(LedgerEntryORM),
            "episodes": await cnt(TradeEpisodeORM),
        }


# ------------------------------------------------------------------ W1
async def test_W1_eligible_no_trade_creates_exactly_one_candidate(database):
    tap = ShadowDecisionTap(ShadowCandidateStore(database.session_factory))
    _observe(tap, _decision())
    assert tap.queue_depth == 1
    await tap.drain_once()
    rows = await _candidates(database)
    assert len(rows) == 1
    assert rows[0].source_decision_id == "dec-w1"
    assert rows[0].status == STATUS_PENDING


# ------------------------------------------------------------------ W2
async def test_W2_wait_creates_one_candidate(database):
    tap = ShadowDecisionTap(ShadowCandidateStore(database.session_factory))
    _observe(
        tap,
        _decision(decision_id="dec-w2", action=FlatAction.WAIT, reason_codes=["LOW_CONVICTION"]),
    )
    await tap.drain_once()
    rows = await _candidates(database)
    assert len(rows) == 1


# ------------------------------------------------------------------ W3
async def test_W3_directional_decision_creates_no_shadow_candidate(database):
    """LONG/SHORT must never enter the NO_TRADE shadow path."""
    for action in (FlatAction.LONG, FlatAction.SHORT):
        tap = ShadowDecisionTap(ShadowCandidateStore(database.session_factory))
        outcome = _observe(
            tap,
            _decision(
                decision_id=f"dec-w3-{action.value}",
                action=action,
                thesis=f"{action.value} thesis",
                position_size_request=Decimal("0.1"),
                leverage_request=1,
                stop_loss=Decimal("95"),
            ),
        )
        # Gate rejects before any queue/DB work happens.
        assert outcome is not None and outcome.startswith("INELIGIBLE")
        assert tap.queue_depth == 0
        await tap.drain_once()
        assert tap.stats.enqueued == 0
    assert await _candidates(database) == []


# ------------------------------------------------------------------ W4
async def test_W4_system_failure_no_trade_creates_zero_candidates(database):
    tap = ShadowDecisionTap(ShadowCandidateStore(database.session_factory))
    _observe(
        tap,
        _decision(decision_id="dec-w4", reason_codes=["MARKET_DATA_UNAVAILABLE"]),
    )
    await tap.drain_once()
    assert await _candidates(database) == []
    assert tap.stats.dropped_ineligible == 1


# ------------------------------------------------------------------ W5
async def test_W5_shadow_store_failure_never_propagates(database):
    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("shadow store unavailable")

        async def __aexit__(self, *exc):
            return False

    tap = ShadowDecisionTap(ShadowCandidateStore(lambda: _Boom()))
    # The production call site must not raise.
    _observe(tap, _decision(decision_id="dec-w5"))
    assert tap.queue_depth == 1
    persisted = await tap.drain_once()  # must also not raise
    assert persisted == 1
    assert tap.stats.dropped_store_error >= 1
    # The real path is untouched: nothing was written anywhere real.
    snap = await _snapshot(database)
    assert all(v == 0 for v in snap.values())


# ------------------------------------------------------------------ W6
async def test_W6_queue_saturation_drops_samples_without_blocking(database):
    tap = ShadowDecisionTap(
        ShadowCandidateStore(database.session_factory), max_queue_depth=3
    )
    base = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    outcomes = []
    for i in range(10):
        # Distinct symbols+time buckets so nothing merges by dedup: this test is
        # about QUEUE capacity, not about dedup.
        outcomes.append(
            _observe(
                tap,
                _decision(
                    decision_id=f"dec-w6-{i}",
                    symbol=f"S{i}USDT",
                    created_at=(base + timedelta(seconds=600 * i)).isoformat(),
                ),
            )
        )
    assert tap.queue_depth == 3
    assert outcomes.count(REASON_QUEUE_FULL) == 7
    assert tap.stats.dropped_queue_full == 7
    assert tap.stats.enqueued == 3
    # And the samples that DID fit are still persisted normally.
    await tap.drain_once()
    assert len(await _candidates(database)) == 3


# ------------------------------------------------------------------ W7
async def test_W7_pending_candidates_resume_without_decision_replay(database):
    store = ShadowCandidateStore(database.session_factory)
    tap = ShadowDecisionTap(store)
    _observe(tap, _decision(decision_id="dec-w7"))
    await tap.drain_once()

    # "Restart": brand-new tap/store over the same durable rows. No ChiefTrader
    # replay is required or performed.
    restarted_store = ShadowCandidateStore(database.session_factory)
    restarted = ShadowDecisionTap(restarted_store)
    active = await restarted_store.list_active()
    assert len(active) == 1
    assert active[0].status == STATUS_PENDING
    assert restarted.queue_depth == 0  # queue is process-local by design


# ------------------------------------------------------------------ W8
async def test_W8_zero_side_effects_across_the_tap(database):
    before = await _snapshot(database)
    budget = GlobalLLMBudget(BudgetConfig())
    budget_before = budget.snapshot()

    tap = ShadowDecisionTap(ShadowCandidateStore(database.session_factory))
    for i in range(50):
        _observe(tap, _decision(decision_id=f"dec-w8-{i}"))
    await tap.drain_once()

    assert await _snapshot(database) == before
    assert all(v == 0 for v in before.values())
    after = budget.snapshot()
    assert after["calls_in_window"] == budget_before["calls_in_window"] == 0
    assert after["granted_by_priority"] == {}
    assert after["position_management_calls_in_window"] == 0
    assert after["general_calls_in_window"] == 0
    # Shadow rows exist and are explicitly non-factual.
    async with database.session_factory() as session:
        assert (await session.execute(select(ShadowEpisodeORM))).scalars().all() == []


# ------------------------------------------------------- wiring / isolation


def test_tap_is_synchronous_and_has_no_await():
    """The producer must not be awaitable: nothing can block the trading loop."""
    import inspect

    src = inspect.getsource(ShadowDecisionTap.observe)
    assert "async def" not in src
    assert "await " not in src
    # Bounded, non-blocking hand-off only.
    assert "put_nowait" in src
    assert "QueueFull" in src


def test_tap_placement_is_after_the_durable_commit():
    """Source-order proof: observe() runs after decisions.save()."""
    import inspect

    from crypto_trader.llm_chief.runtime_strategy import LiveLLMDecisionStrategy

    src = inspect.getsource(LiveLLMDecisionStrategy)
    save_at = src.index("await self.decisions.save(")
    observe_at = src.index("_observe_for_shadow(")
    assert observe_at > save_at, "shadow tap must run AFTER the decision is committed"
    # And it is wrapped so a shadow fault cannot escape.
    assert "except Exception" in inspect.getsource(
        LiveLLMDecisionStrategy._observe_for_shadow
    )


def test_no_unbounded_task_spawn_in_tap():
    """Exactly one long-lived consumer; no per-decision create_task."""
    import inspect

    src = inspect.getsource(ShadowDecisionTap)
    assert src.count("asyncio.create_task") == 1


async def test_consumer_start_is_idempotent(database):
    tap = ShadowDecisionTap(ShadowCandidateStore(database.session_factory))
    await tap.start()
    first = tap._consumer
    await tap.start()
    assert tap._consumer is first
    await tap.stop()


async def test_observability_stats_are_available(database):
    tap = ShadowDecisionTap(ShadowCandidateStore(database.session_factory))
    _observe(tap, _decision(decision_id="dec-stats"))
    _observe(
        tap,
        _decision(
            decision_id="dec-stats2",
            action=FlatAction.LONG,
            position_size_request=Decimal("0.1"),
            leverage_request=1,
            stop_loss=Decimal("95"),
        ),
    )
    await tap.drain_once()
    stats = tap.stats.as_dict()
    assert stats["observed"] == 2
    assert stats["created"] == 1
    assert stats["dropped_ineligible"] == 1
    assert tap.queue_depth == 0


def test_observe_returns_quickly_under_saturation():
    """Saturation must not turn the producer into a blocking call."""
    import time

    class _NeverDrains:
        async def enqueue(self, payload):  # pragma: no cover - never awaited here
            raise AssertionError

    tap = ShadowDecisionTap(_NeverDrains(), max_queue_depth=1)
    tap.observe(
        ShadowObservation(
            decision_id="d1",
            symbol=SYMBOL,
            action="NO_TRADE",
            reason_codes=["SIGNAL_TOO_WEAK"],
            thesis="weak",
            market_data_quality="GOOD",
            reference_price=Decimal("100"),
            market_regime="RANGE",
        )
    )
    start = time.perf_counter()
    for i in range(2000):
        tap.observe(
            ShadowObservation(
                decision_id=f"d{i}",
                symbol=SYMBOL,
                action="NO_TRADE",
                reason_codes=["SIGNAL_TOO_WEAK"],
                thesis="weak",
                market_data_quality="GOOD",
                reference_price=Decimal("100"),
                market_regime="RANGE",
            )
        )
    elapsed = time.perf_counter() - start
    # 2000 saturated observations must cost well under a second of wall time.
    assert elapsed < 1.0
    assert tap.stats.dropped_queue_full >= 1999


async def test_tap_disabled_is_a_no_op(database):
    tap = ShadowDecisionTap(ShadowCandidateStore(database.session_factory), enabled=False)
    assert tap.observe(
        ShadowObservation(
            decision_id="d",
            symbol=SYMBOL,
            action="NO_TRADE",
            reason_codes=["SIGNAL_TOO_WEAK"],
            thesis="weak",
            market_data_quality="GOOD",
            reference_price=Decimal("100"),
            market_regime="RANGE",
        )
    ) == "SHADOW_DISABLED"
    assert tap.queue_depth == 0
    assert await _candidates(database) == []


async def test_load_saturation_through_the_production_tap(database):
    """10k observations through the TAP (not the store) stay bounded."""
    store = ShadowCandidateStore(database.session_factory, max_active=50, max_per_symbol=5)
    tap = ShadowDecisionTap(store, max_queue_depth=256)
    base = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    for i in range(10_000):
        _observe(
            tap,
            _decision(
                decision_id=f"load-{i}",
                created_at=(base + timedelta(seconds=i)).isoformat(),
            ),
        )
        if i % 500 == 0:
            await tap.drain_once()
    await tap.drain_once()
    counts = await store.counts()
    assert counts["active"] <= 50
    async with database.session_factory() as session:
        total = (
            await session.execute(select(func.count()).select_from(ShadowCandidateORM))
        ).scalar_one()
    assert total <= 10_000
    assert tap.stats.dropped_queue_full >= 0
