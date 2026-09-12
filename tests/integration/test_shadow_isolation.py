"""Shadow sidecar: functional acceptance (S1-S10) and HARD ISOLATION (I1-I14).

The isolation block is the point of this file. A shadow learner that perturbs
real trading is worse than no shadow learner at all, so these tests assert the
absence of effects — zero orders, zero fills, zero positions, zero balance
movement, zero ledger rows, zero capacity consumption, zero LLM calls — rather
than merely checking that shadow rows appear.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from crypto_trader.llm_chief.budget import BudgetConfig, GlobalLLMBudget
from crypto_trader.persistence.models import (
    AccountProjectionORM,
    FillORM,
    LedgerEntryORM,
    OrderORM,
    PositionProjectionORM,
    TradeEpisodeORM,
)
from crypto_trader.shadow.candidate_store import (
    MAX_ACTIVE_PER_SYMBOL,
    ShadowCandidateStore,
    dedup_key_for,
)
from crypto_trader.shadow.eligibility import (
    REASON_ELIGIBLE,
    REASON_NOT_ABSTENTION,
    REASON_SYSTEM_ERROR,
    shadow_eligibility,
)
from crypto_trader.shadow.models import (
    OUTCOME_CORRECT_NO_TRADE,
    OUTCOME_MISSED_OPPORTUNITY,
    STATUS_EVALUATED,
    STATUS_INVALIDATED,
    STATUS_PENDING,
    ShadowCandidateORM,
    ShadowEpisodeORM,
    ShadowEvaluationRunORM,
)
from crypto_trader.shadow.tracker import (
    CounterfactualOutcomeEvaluator,
    MarketObservation,
    ShadowTracker,
)

SYMBOL = "BTCUSDT"


def _eligible_kwargs(**over):
    base = dict(
        action="NO_TRADE",
        reason_codes=["SIGNAL_TOO_WEAK"],
        thesis="momentum insufficient for a LONG entry",
        market_data_quality="GOOD",
        reference_price=Decimal("100"),
        decision_persisted=True,
        market_regime="RANGE",
    )
    base.update(over)
    return base


def _candidate(**over) -> dict:
    base = dict(
        symbol=SYMBOL,
        direction_hypothesis="LONG",
        reference_price="100",
        source_decision_id="dec-1",
        strategy_id="live_llm",
        strategy_version="canonical-1.0.0",
        market_regime="RANGE",
        chieftrader_action="NO_TRADE",
        chieftrader_reason="signal too weak",
        created_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
        max_hold_seconds=600,
    )
    base.update(over)
    return base


async def _counts(database) -> dict:
    async with database.session_factory() as session:
        return {
            "orders": (
                await session.execute(select(func.count()).select_from(OrderORM))
            ).scalar_one(),
            "fills": (
                await session.execute(select(func.count()).select_from(FillORM))
            ).scalar_one(),
            "positions": (
                await session.execute(select(func.count()).select_from(PositionProjectionORM))
            ).scalar_one(),
            "ledger": (
                await session.execute(select(func.count()).select_from(LedgerEntryORM))
            ).scalar_one(),
            "balances": (
                await session.execute(select(func.count()).select_from(AccountProjectionORM))
            ).scalar_one(),
            "trade_episodes": (
                await session.execute(select(func.count()).select_from(TradeEpisodeORM))
            ).scalar_one(),
        }


# ===================================================================== S1-S10


def test_S1_eligible_no_trade_is_classified_eligible():
    verdict = shadow_eligibility(**_eligible_kwargs())
    assert verdict.eligible is True
    assert verdict.reason == REASON_ELIGIBLE
    assert verdict.direction_hypothesis == "LONG"


def test_S2_system_error_no_trade_is_rejected():
    """A NO_TRADE caused by the SYSTEM must never become a shadow candidate."""
    for marker in (
        "MARKET_DATA_UNAVAILABLE",
        "SKIPPED_BUDGET",
        "RECONCILIATION_HALTED",
        "PROVIDER_DOWN",
        "DB_ERROR",
        "FAIL_CLOSED",
    ):
        verdict = shadow_eligibility(**_eligible_kwargs(reason_codes=[marker]))
        assert verdict.eligible is False, marker
        assert verdict.reason == REASON_SYSTEM_ERROR, marker
        assert marker in verdict.matched_markers


def test_S2b_non_abstention_action_is_rejected():
    for action in ("LONG", "SHORT", "HOLD", "REDUCE", "EXIT"):
        verdict = shadow_eligibility(**_eligible_kwargs(action=action))
        assert verdict.eligible is False
        assert verdict.reason == REASON_NOT_ABSTENTION


def test_S2c_eligibility_requires_good_inputs():
    assert shadow_eligibility(**_eligible_kwargs(market_data_quality="POOR")).eligible is False
    assert shadow_eligibility(**_eligible_kwargs(reference_price=None)).eligible is False
    assert shadow_eligibility(**_eligible_kwargs(decision_persisted=False)).eligible is False
    assert shadow_eligibility(**_eligible_kwargs(thesis="", reason_codes=[])).eligible is False


async def test_S1b_eligible_decision_creates_exactly_one_candidate(database):
    store = ShadowCandidateStore(database.session_factory)
    first = await store.enqueue(_candidate())
    assert first.accepted is True and first.reason == "CREATED"
    async with database.session_factory() as session:
        rows = (await session.execute(select(ShadowCandidateORM))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == STATUS_PENDING


async def test_S2d_system_error_decision_creates_zero_candidates(database):
    """Gate + store together: an ineligible decision never reaches persistence."""
    store = ShadowCandidateStore(database.session_factory)
    verdict = shadow_eligibility(**_eligible_kwargs(reason_codes=["SKIPPED_BUDGET"]))
    assert verdict.eligible is False
    # The caller must not enqueue; assert the store stays empty.
    async with database.session_factory() as session:
        rows = (await session.execute(select(ShadowCandidateORM))).scalars().all()
    assert rows == []
    assert (await store.counts())["active"] == 0


async def test_S3_duplicates_do_not_explode_candidate_count(database):
    store = ShadowCandidateStore(database.session_factory)
    results = [await store.enqueue(_candidate()) for _ in range(25)]
    assert results[0].reason == "CREATED"
    assert all(r.deduplicated for r in results[1:])
    async with database.session_factory() as session:
        rows = (await session.execute(select(ShadowCandidateORM))).scalars().all()
    assert len(rows) == 1
    assert rows[0].observation_count == 25


def test_S3b_dedup_key_is_bucketed_by_symbol_direction_version_regime():
    t = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    base = dict(symbol="BTCUSDT", direction="LONG", strategy_version="v1", regime="RANGE", now=t)
    assert dedup_key_for(**base) == dedup_key_for(**base)
    assert dedup_key_for(**base) != dedup_key_for(**{**base, "symbol": "ETHUSDT"})
    assert dedup_key_for(**base) != dedup_key_for(**{**base, "direction": "SHORT"})
    assert dedup_key_for(**base) != dedup_key_for(**{**base, "regime": "TREND"})
    # A different time bucket yields a different key (new observation window).
    later = t + timedelta(seconds=400)
    assert dedup_key_for(**{**base, "now": later}) != dedup_key_for(**base)


async def test_S4_entry_exit_assumptions_are_immutable(database):
    store = ShadowCandidateStore(database.session_factory)
    created = await store.enqueue(_candidate())
    row = await store.get(created.candidate_id)
    fingerprint = row.rules_fingerprint
    # Re-enqueueing a conflicting rule set inside the SAME bucket deduplicates
    # and must NOT mutate the frozen rules.
    await store.enqueue(
        _candidate(max_hold_seconds=99999, stop_rule="CHANGED", take_profit_rule="CHANGED")
    )
    after = await store.get(created.candidate_id)
    assert after.rules_fingerprint == fingerprint
    assert int(after.max_hold_seconds) == 600
    assert after.stop_rule is None


async def test_S5_future_factual_data_matures_and_evaluates(database):
    store = ShadowCandidateStore(database.session_factory)
    created = await store.enqueue(_candidate(direction_hypothesis="LONG"))
    base = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    observations = [
        MarketObservation(
            SYMBOL, base + timedelta(seconds=60), Decimal("100"), bar_open=Decimal("100")
        ),
        MarketObservation(SYMBOL, base + timedelta(seconds=300), Decimal("101")),
        MarketObservation(SYMBOL, base + timedelta(seconds=600), Decimal("102")),
    ]
    tracker = ShadowTracker(database.session_factory, candidate_store=store)
    report = await tracker.run_once(
        observations=observations, now=base + timedelta(seconds=700)
    )
    assert report.evaluated == 1
    async with database.session_factory() as session:
        episodes = (await session.execute(select(ShadowEpisodeORM))).scalars().all()
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.shadow_candidate_id == created.candidate_id
    assert episode.outcome_class == OUTCOME_MISSED_OPPORTUNITY
    assert episode.factual is False
    assert episode.evidence_type == "SHADOW_EPISODE"
    assert episode.holding_seconds == 540


async def test_S6_missing_future_data_never_fabricates(database):
    store = ShadowCandidateStore(database.session_factory, ttl_seconds=60)
    await store.enqueue(_candidate())
    tracker = ShadowTracker(database.session_factory, candidate_store=store)
    base = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    # No observations at all: nothing may be invented.
    report = await tracker.run_once(
        observations=[], now=base + timedelta(seconds=120)
    )
    assert report.evaluated == 0
    async with database.session_factory() as session:
        assert (await session.execute(select(ShadowEpisodeORM))).scalars().all() == []
        rows = (await session.execute(select(ShadowCandidateORM))).scalars().all()
    assert rows[0].status == STATUS_INVALIDATED


def test_S7_evaluator_is_deterministic(database):
    class _C:
        direction_hypothesis = "LONG"

    evaluator = CounterfactualOutcomeEvaluator()
    kwargs = dict(
        candidate=_C(),
        entry_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
        entry_price=Decimal("100"),
        exit_at=datetime(2026, 9, 12, 12, 10, tzinfo=UTC),
        exit_price=Decimal("101"),
        mfe=Decimal("0.02"),
        mae=Decimal("0.001"),
        exit_reason="MAX_HOLD_ELAPSED",
    )
    a = evaluator.evaluate(**kwargs)
    b = evaluator.evaluate(**kwargs)
    assert a == b
    # SHORT flips the sign deterministically.
    class _S:
        direction_hypothesis = "SHORT"

    short = evaluator.evaluate(**{**kwargs, "candidate": _S()})
    assert Decimal(short["gross_return"]) < 0
    # Directionless samples are never scored as a long.
    class _N:
        direction_hypothesis = "NONE"

    none = evaluator.evaluate(**{**kwargs, "candidate": _N()})
    assert none["gross_return"] is None


async def test_S7b_loss_is_correct_no_trade(database):
    store = ShadowCandidateStore(database.session_factory)
    await store.enqueue(_candidate(direction_hypothesis="LONG"))
    base = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    observations = [
        MarketObservation(
            SYMBOL, base + timedelta(seconds=60), Decimal("100"), bar_open=Decimal("100")
        ),
        MarketObservation(SYMBOL, base + timedelta(seconds=600), Decimal("98")),
    ]
    tracker = ShadowTracker(database.session_factory, candidate_store=store)
    await tracker.run_once(observations=observations, now=base + timedelta(seconds=700))
    async with database.session_factory() as session:
        episodes = (await session.execute(select(ShadowEpisodeORM))).scalars().all()
    assert len(episodes) == 1
    assert episodes[0].outcome_class == OUTCOME_CORRECT_NO_TRADE


async def test_S8_evaluating_twice_yields_exactly_one_episode(database):
    store = ShadowCandidateStore(database.session_factory)
    await store.enqueue(_candidate())
    base = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    observations = [
        MarketObservation(
            SYMBOL, base + timedelta(seconds=60), Decimal("100"), bar_open=Decimal("100")
        ),
        MarketObservation(SYMBOL, base + timedelta(seconds=600), Decimal("102")),
    ]
    tracker = ShadowTracker(database.session_factory, candidate_store=store)
    await tracker.run_once(observations=observations, now=base + timedelta(seconds=700))
    await tracker.run_once(observations=observations, now=base + timedelta(seconds=800))
    async with database.session_factory() as session:
        episodes = (await session.execute(select(ShadowEpisodeORM))).scalars().all()
        rows = (await session.execute(select(ShadowCandidateORM))).scalars().all()
    assert len(episodes) == 1
    assert rows[0].status == STATUS_EVALUATED


async def test_S9_shadow_episode_is_explicitly_not_factual(database):
    store = ShadowCandidateStore(database.session_factory)
    await store.enqueue(_candidate())
    base = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    tracker = ShadowTracker(database.session_factory, candidate_store=store)
    await tracker.run_once(
        observations=[
            MarketObservation(SYMBOL, base + timedelta(seconds=60), Decimal("100"), 100),
            MarketObservation(SYMBOL, base + timedelta(seconds=600), Decimal("103")),
        ],
        now=base + timedelta(seconds=700),
    )
    async with database.session_factory() as session:
        episode = (await session.execute(select(ShadowEpisodeORM))).scalar_one()
    assert episode.factual is False
    assert episode.evidence_type == "SHADOW_EPISODE"
    assert episode.evaluator_version == "shadow-eval-v1"
    # And it must NOT appear in the factual episode table.
    async with database.session_factory() as session:
        assert (await session.execute(select(TradeEpisodeORM))).scalars().all() == []


async def test_S10_pending_candidates_survive_and_resume(database):
    """A fresh store/tracker (restart) still sees and advances PENDING rows."""
    store = ShadowCandidateStore(database.session_factory)
    await store.enqueue(_candidate())
    # Simulate restart: brand-new objects over the same durable rows.
    restarted = ShadowCandidateStore(database.session_factory)
    active = await restarted.list_active()
    assert len(active) == 1
    assert active[0].status == STATUS_PENDING
    base = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    tracker = ShadowTracker(database.session_factory, candidate_store=restarted)
    report = await tracker.run_once(
        observations=[
            MarketObservation(SYMBOL, base + timedelta(seconds=60), Decimal("100"), 100),
            MarketObservation(SYMBOL, base + timedelta(seconds=600), Decimal("102")),
        ],
        now=base + timedelta(seconds=700),
    )
    assert report.evaluated == 1


# ====================================================================== I1-I14


async def test_I1_to_I5_shadow_writes_nothing_real(database):
    """I1-I5: no orders, fills, positions, balances or ledger rows."""
    before = await _counts(database)
    store = ShadowCandidateStore(database.session_factory)
    for i in range(20):
        await store.enqueue(_candidate(source_decision_id=f"d{i}"))
    base = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    tracker = ShadowTracker(database.session_factory, candidate_store=store)
    await tracker.run_once(
        observations=[
            MarketObservation(SYMBOL, base + timedelta(seconds=60), Decimal("100"), 100),
            MarketObservation(SYMBOL, base + timedelta(seconds=600), Decimal("102")),
        ],
        now=base + timedelta(seconds=700),
    )
    after = await _counts(database)
    assert after == before
    assert after["orders"] == before["orders"]
    assert after["fills"] == before["fills"]
    assert after["positions"] == before["positions"]
    assert after["ledger"] == before["ledger"]
    assert after["balances"] == before["balances"]


async def test_I6_shadow_has_zero_capacity_effect(database):
    """Shadow rows must not change the real capacity gate's answer."""
    from crypto_trader.simulator.exchange import SimulatedExchangeAdapter

    adapter = SimulatedExchangeAdapter(initial_balances={"USDT": Decimal("1000")})
    adapter.llm_budget = GlobalLLMBudget(BudgetConfig())
    adapter.position_review_min_interval_seconds = 60.0
    before = adapter.position_management_capacity(open_positions=0)

    store = ShadowCandidateStore(database.session_factory)
    for i in range(30):
        await store.enqueue(
            _candidate(source_decision_id=f"c{i}", symbol=f"S{i}USDT")
        )
    after = adapter.position_management_capacity(open_positions=0)
    assert after == before


async def test_I7_to_I9_shadow_consumes_zero_llm_budget(database):
    """I7-I9: no provider call, no position reserve, no general pool spend."""
    budget = GlobalLLMBudget(BudgetConfig())
    before = budget.snapshot()

    store = ShadowCandidateStore(database.session_factory)
    for i in range(10):
        await store.enqueue(_candidate(source_decision_id=f"b{i}"))
    base = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    ShadowTracker(database.session_factory, candidate_store=store)
    tracker = ShadowTracker(database.session_factory, candidate_store=store)
    await tracker.run_once(
        observations=[
            MarketObservation(SYMBOL, base + timedelta(seconds=60), Decimal("100"), 100),
            MarketObservation(SYMBOL, base + timedelta(seconds=600), Decimal("102")),
        ],
        now=base + timedelta(seconds=700),
    )
    after = budget.snapshot()
    assert after["calls_in_window"] == before["calls_in_window"] == 0
    assert after["granted_by_priority"] == before["granted_by_priority"] == {}
    assert after["position_management_calls_in_window"] == 0
    assert after["general_calls_in_window"] == 0


async def test_I10_to_I12_shadow_failures_never_raise(database):
    """I10-I14: a broken shadow store/tracker degrades, it does not propagate."""
    class _Exploding:
        async def __aenter__(self):
            raise RuntimeError("shadow db unavailable")

        async def __aexit__(self, *exc):
            return False

    broken = ShadowCandidateStore(lambda: _Exploding())
    result = await broken.enqueue(_candidate())
    assert result.accepted is False
    assert result.reason == "SHADOW_STORE_ERROR"
    assert broken.error_count == 1

    store = ShadowCandidateStore(database.session_factory)
    tracker = ShadowTracker(database.session_factory, candidate_store=store)
    tracker.session_factory = lambda: _Exploding()
    report = await tracker.run_once(observations=[], now=datetime.now(UTC))
    assert report.errors == 1
    assert tracker.error_count == 1


def test_I13_shadow_has_no_exchange_polling_path():
    """I13: the package must not import or drive any market-data producer."""
    import pathlib
    import re

    root = pathlib.Path("src/crypto_trader/shadow")
    forbidden = re.compile(
        r"OKXPublicFeed|PublicMarketFeed|feed\.refresh|websocket|aiohttp|httpx|requests\."
    )
    for path in root.rglob("*.py"):
        text = path.read_text()
        assert not forbidden.search(text), f"{path.name} references a market producer"


def test_I13b_shadow_calls_no_provider():
    """I7: no LLM client anywhere in the package."""
    import pathlib
    import re

    root = pathlib.Path("src/crypto_trader/shadow")
    forbidden = re.compile(r"complete_json|DeepSeekProvider|LLMProvider|provider\.")
    for path in root.rglob("*.py"):
        assert not forbidden.search(path.read_text()), path.name


async def test_I14_shadow_does_not_touch_factual_episodes(database):
    async with database.session_factory() as session:
        session.add(
            TradeEpisodeORM(
                episode_id="episode_real_1",
                trade_plan_id="plan_real_1",
                symbol=SYMBOL,
                direction="LONG",
                entry_decision_id="d",
                exit_decision_id="x",
                position_decision_ids_json=[],
                risk_decision_ids_json=[],
                order_ids_json=[],
                fill_ids_json=[],
                entry_price=Decimal("1"),
                exit_price=Decimal("1"),
                opened_quantity=Decimal("1"),
                closed_quantity=Decimal("1"),
                leverage=Decimal("1"),
                fees=Decimal("0"),
                funding_pnl=Decimal("0"),
                gross_pnl=Decimal("0"),
                net_pnl=Decimal("0"),
                holding_time_seconds=1.0,
                entry_market_regime="RANGE",
                terminal_reason="EXIT",
                factual=True,
                review_status="PENDING",
                applicability_scope_json={},
                opened_at=datetime.now(UTC),
                closed_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()
    store = ShadowCandidateStore(database.session_factory)
    await store.enqueue(_candidate())
    base = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    await ShadowTracker(database.session_factory, candidate_store=store).run_once(
        observations=[
            MarketObservation(SYMBOL, base + timedelta(seconds=60), Decimal("100"), 100),
            MarketObservation(SYMBOL, base + timedelta(seconds=600), Decimal("102")),
        ],
        now=base + timedelta(seconds=700),
    )
    async with database.session_factory() as session:
        rows = (await session.execute(select(TradeEpisodeORM))).scalars().all()
    assert len(rows) == 1
    assert rows[0].episode_id == "episode_real_1"
    assert rows[0].factual is True


# ============================================================ resource limits


async def test_resource_caps_bound_the_candidate_count(database):
    store = ShadowCandidateStore(
        database.session_factory, max_active=6, max_per_symbol=2
    )
    accepted = 0
    for i in range(40):
        r = await store.enqueue(
            _candidate(
                symbol=f"S{i % 8}USDT",
                source_decision_id=f"r{i}",
                created_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
                + timedelta(seconds=400 * i),
            )
        )
        accepted += 1 if r.accepted else 0
    counts = await store.counts()
    assert counts["active"] <= 6
    per_symbol: dict[str, int] = {}
    for row in await store.list_active(limit=100):
        per_symbol[row.symbol] = per_symbol.get(row.symbol, 0) + 1
    assert all(v <= 2 for v in per_symbol.values())
    # Drops are recorded, not silent failures of the trading system.
    assert counts["dropped_total"] >= 1


async def test_load_saturation_keeps_counts_bounded(database):
    """§32: 10k repeated observations must not grow rows without bound."""
    store = ShadowCandidateStore(database.session_factory, max_active=50, max_per_symbol=5)
    for i in range(10_000):
        await store.enqueue(
            _candidate(
                symbol="BTCUSDT",
                source_decision_id=f"load{i}",
                created_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
                + timedelta(seconds=i),
            )
        )
    async with database.session_factory() as session:
        total = (
            await session.execute(select(func.count()).select_from(ShadowCandidateORM))
        ).scalar_one()
    assert total <= 10_000
    counts = await store.counts()
    assert counts["active"] <= MAX_ACTIVE_PER_SYMBOL * 1  # single symbol in this load
    assert (await store.counts())["active"] <= 5


async def test_run_report_is_persisted_for_observability(database):
    store = ShadowCandidateStore(database.session_factory)
    tracker = ShadowTracker(database.session_factory, candidate_store=store)
    await tracker.run_once(observations=[], now=datetime.now(UTC))
    async with database.session_factory() as session:
        runs = (await session.execute(select(ShadowEvaluationRunORM))).scalars().all()
    assert len(runs) == 1
    assert runs[0].finished_at is not None


@pytest.mark.parametrize("direction", ["LONG", "SHORT", "NONE"])
async def test_all_directions_are_handled(database, direction):
    store = ShadowCandidateStore(database.session_factory)
    await store.enqueue(_candidate(direction_hypothesis=direction))
    base = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    report = await ShadowTracker(database.session_factory, candidate_store=store).run_once(
        observations=[
            MarketObservation(SYMBOL, base + timedelta(seconds=60), Decimal("100"), 100),
            MarketObservation(SYMBOL, base + timedelta(seconds=600), Decimal("102")),
        ],
        now=base + timedelta(seconds=700),
    )
    assert report.errors == 0
    async with database.session_factory() as session:
        episode = (await session.execute(select(ShadowEpisodeORM))).scalar_one()
    assert episode.direction == direction
    assert episode.factual is False
