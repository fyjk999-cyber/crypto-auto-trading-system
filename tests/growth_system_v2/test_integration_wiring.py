"""I03/I04/I05 integration wiring and failure-path tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.governance.scheduler import DailyReviewScheduler
from crypto_trader.learning.growth_attribution import DailyCardLearner
from crypto_trader.learning.growth_card_retrieval import (
    CardDecisionTraceStore,
    ExperienceCardRetriever,
    register_experience_card_tool,
)
from crypto_trader.learning.growth_contracts import (
    ObservationFact,
    StructuredReview,
)
from crypto_trader.learning.growth_contracts import (
    TestableLesson as LessonSpec,
)
from crypto_trader.learning.growth_experience import (
    AdaptiveCardStore,
    ClaimLostError,
)
from crypto_trader.learning.growth_models import (
    GrowthCardDecisionTraceORM,
    GrowthReviewAttemptORM,
)
from crypto_trader.llm.tools.registry import LLMToolRegistry
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.provider import LLMResponse
from crypto_trader.llm_chief.tool_orchestrator import ToolDrivenChiefTrader
from crypto_trader.persistence.models import TradeEpisodeORM
from tests.growth_system_v2.conftest import AS_OF, market_context, seed_card

DAY = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)


class ScriptedProvider:
    name = "deepseek-test-double"
    model = "deepseek-test-model"

    def __init__(self, selected_tools: list[str]):
        self.selected_tools = selected_tools
        self.calls: list[dict] = []

    def healthy(self) -> bool:
        return True

    async def complete_json(self, **kwargs) -> LLMResponse:
        self.calls.append(kwargs)
        payload = (
            {"tools": self.selected_tools}
            if kwargs.get("operation") == "tool_selection"
            else {
                "action": "NO_TRADE",
                "market_regime": "BULL",
                "thesis": "No current edge.",
                "reason_codes": ["NO_TRADE"],
                "position_size_request": 0,
                "leverage_request": 0,
                "raw_llm_confidence": 0.0,
            }
        )
        return LLMResponse(
            text=json.dumps(payload),
            provider=self.name,
            model=self.model,
            latency_ms=1.0,
            parsed_json=payload,
            ok=True,
        )


def _chief_context() -> ChiefTraderContext:
    return ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={"last": "100"},
        regime="BULL",
        quant_evidence=[],
        portfolio_state={"equity": "100000"},
        risk_summary={"max_leverage": "3"},
        prepared_at=AS_OF.isoformat(),
    )


def _tool_context() -> dict:
    return {
        "as_of": AS_OF,
        "chief_context": _chief_context(),
        "factor_states": [
            {
                "factor_id": "funding_rate",
                "state": "EXTREME_HIGH",
                "definition_version": "funding-def-v1",
            },
            {
                "factor_id": "open_interest",
                "state": "RISING",
                "definition_version": "oi-def-v1",
            },
        ],
        "market_state": market_context().to_json(),
        "account_id": "default",
        "mode": "PAPER",
    }


async def test_trace_persisted_before_card_evidence_exposed(v2_db):
    await seed_card(v2_db, rule_id="card_trace_first", status="ACTIVE")
    store = CardDecisionTraceStore(v2_db.session_factory)
    registry = LLMToolRegistry()
    register_experience_card_tool(
        registry, ExperienceCardRetriever(v2_db.session_factory), trace_store=store
    )
    evidence = await registry.call("experience_cards", "BTCUSDT", _tool_context())
    trace_id = evidence.features["card_trace_id"]
    assert evidence.features["card_evidence_available"] is True
    assert evidence.source_refs == ["card:card_trace_first:v1"]
    async with v2_db.session_factory() as session:
        trace = (
            await session.execute(
                select(GrowthCardDecisionTraceORM).where(
                    GrowthCardDecisionTraceORM.trace_id == trace_id
                )
            )
        ).scalar_one()
    assert trace.selected_card_refs_json == ["card:card_trace_first:v1"]
    assert trace.decision_id is None  # attached only after the decision


async def test_trace_failure_hides_card_evidence_and_decision_continues(v2_db, monkeypatch):
    await seed_card(v2_db, rule_id="card_trace_fail", status="ACTIVE")
    store = CardDecisionTraceStore(v2_db.session_factory)

    async def broken_record(*_args, **_kwargs):
        raise RuntimeError("simulated trace persistence failure")

    monkeypatch.setattr(store, "record", broken_record)
    registry = LLMToolRegistry()
    register_experience_card_tool(
        registry, ExperienceCardRetriever(v2_db.session_factory), trace_store=store
    )
    evidence = await registry.call("experience_cards", "BTCUSDT", _tool_context())
    assert evidence.data_quality == "TRACE_UNAVAILABLE"
    assert evidence.source_refs == []
    assert evidence.features["card_evidence_available"] is False
    assert evidence.features["cards"] == []

    # The same Chief still makes the final decision without card evidence.
    provider = ScriptedProvider(["experience_cards"])
    chief = ToolDrivenChiefTrader(ChiefTraderEngine(provider=provider), registry)
    decision, package = await chief.decide(
        _chief_context(), tool_context=_tool_context(), now=AS_OF
    )
    assert decision.action == "NO_TRADE"
    assert package is not None
    assert package.source_refs == []  # no card evidence without durable trace


async def _seed_daily_card_scenario(database):
    await seed_card(
        database,
        rule_id="card_daily_wire",
        status="WATCH",
        source_ids=["ep_wire"],
        support_ids=["ep_wire"],
    )
    lesson = LessonSpec(
        statement="Support evidence for the daily wiring",
        testable_prediction="Same association repeats.",
        evidence_refs=["episode:ep_wire"],
        contrary_refs=[],
        uncertainty="candidate",
        confidence="LOW",
    )
    review = StructuredReview(
        episode_id="ep_wire",
        observation_facts=[
            ObservationFact(
                statement="Factual close.", evidence_refs=["episode:ep_wire"]
            )
        ],
        testable_lessons=[lesson],
        applicability_scope={"scope": "SYMBOL_REGIME"},
    )
    episode = TradeEpisodeORM(
        episode_id="ep_wire",
        trade_plan_id="plan_ep_wire",
        symbol="BTCUSDT",
        direction="LONG",
        entry_decision_id="decision_ep_wire",
        exit_decision_id="exit_ep_wire",
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        opened_quantity=Decimal("1"),
        closed_quantity=Decimal("1"),
        leverage=Decimal("1"),
        fees=Decimal("0"),
        funding_pnl=Decimal("0"),
        gross_pnl=Decimal("1"),
        net_pnl=Decimal("1"),
        holding_time_seconds=60,
        entry_market_regime="BULL",
        terminal_reason="EXIT",
        factual=True,
        review_status="PENDING",
        opened_at=DAY - timedelta(hours=1),
        closed_at=DAY,
    )
    attempt = GrowthReviewAttemptORM(
        attempt_id="attempt_ep_wire",
        review_date="2026-09-10",
        episode_id="ep_wire",
        account_id="default",
        mode="PAPER",
        symbol="BTCUSDT",
        direction="LONG",
        profile_version="p1",
        prompt_version="v1",
        schema_version="v1",
        provider="test-double",
        input_hash="input_ep_wire",
        prompt_hash="ph",
        schema_hash="sh",
        status="SUCCEEDED",
        attempt_no=1,
        result_json=review.model_dump(mode="json"),
    )
    trace = GrowthCardDecisionTraceORM(
        trace_id="trace_ep_wire",
        decision_id="decision_ep_wire",
        account_id="default",
        mode="PAPER",
        symbol="BTCUSDT",
        as_of=DAY,
        selected_card_refs_json=["card:card_daily_wire:v1"],
        candidate_card_refs_json=[],
        excluded_card_refs_json=[],
        excluded_reasons_json={},
    )
    async with database.session_factory() as session:
        session.add_all([episode, attempt, trace])
        await session.commit()


async def test_scheduler_card_learning_updates_once_and_replay_is_idempotent(v2_db):
    await _seed_daily_card_scenario(v2_db)
    store = AdaptiveCardStore(v2_db.session_factory)
    before = await store.get_card("card_daily_wire")
    scheduler = DailyReviewScheduler(
        v2_db.session_factory,
        canonical_only=True,
        card_learner=DailyCardLearner(v2_db.session_factory),
        account_id="default",
        mode="PAPER",
        profile_version="p1",
    )
    first = await scheduler.run_once("2026-09-10")
    assert first["status"] == "SUCCEEDED"
    assert first["card_learning"]["status"] == "SUCCEEDED"
    assert first["card_learning"]["mutations"] >= 1
    after = await store.get_card("card_daily_wire")
    assert after.version > before.version

    second = await scheduler.run_once("2026-09-10")
    assert second.get("idempotent") is True
    replay = await store.get_card("card_daily_wire")
    assert replay.version == after.version


async def test_scheduler_claim_loss_blocks_card_mutation(v2_db, monkeypatch):
    await _seed_daily_card_scenario(v2_db)
    learner = DailyCardLearner(v2_db.session_factory)

    async def claim_lost(**_kwargs):
        raise ClaimLostError("simulated fence loss")

    monkeypatch.setattr(learner, "learn_day", claim_lost)
    scheduler = DailyReviewScheduler(
        v2_db.session_factory,
        canonical_only=True,
        card_learner=learner,
        account_id="default",
        mode="PAPER",
        profile_version="p1",
    )
    result = await scheduler.run_once("2026-09-10")
    assert result["status"] == "SUCCEEDED"
    assert result["card_learning"]["status"] == "CLAIM_LOST"
    card = await AdaptiveCardStore(v2_db.session_factory).get_card("card_daily_wire")
    assert card.version == 1


async def test_scheduler_card_failure_is_reported_but_does_not_block_review(v2_db, monkeypatch):
    await _seed_daily_card_scenario(v2_db)
    learner = DailyCardLearner(v2_db.session_factory)

    async def broken(**_kwargs):
        raise RuntimeError("simulated card learner failure")

    monkeypatch.setattr(learner, "learn_day", broken)
    scheduler = DailyReviewScheduler(
        v2_db.session_factory,
        canonical_only=True,
        card_learner=learner,
        account_id="default",
        mode="PAPER",
        profile_version="p1",
    )
    result = await scheduler.run_once("2026-09-10")
    assert result["status"] == "SUCCEEDED"
    assert result["card_learning"]["status"] == "FAILED"
    card = await AdaptiveCardStore(v2_db.session_factory).get_card("card_daily_wire")
    assert card.version == 1


async def test_build_system_canonical_composition_root(tmp_path, monkeypatch):
    from crypto_trader.config import Settings
    from crypto_trader.runtime import bootstrap as bootstrap_module

    provider = ScriptedProvider(["experience_cards"])
    monkeypatch.setattr(bootstrap_module, "DeepSeekProvider", lambda **kwargs: provider)
    settings = Settings(
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        auto_start_runtime=True,
        paper_mode="PAPER_SYNTHETIC",
        scanner_enabled=False,
        opportunity_scan_enabled=False,
        database_url=f"sqlite+aiosqlite:///{tmp_path}/canonical_wiring.db",
        run_lease_ttl_seconds=30,
        run_lease_renew_interval_seconds=60,
    )
    bundle = await bootstrap_module.build_system(settings)
    try:
        strategy = bundle.engine.strategies[0]
        assert "experience_cards" in strategy.tool_chief.tools.available()
        assert strategy.card_trace_store is not None
        assert strategy.card_mode == "PAPER"
        scheduler = bundle.engine.daily_review_scheduler
        assert scheduler is not None
        assert scheduler.card_learner is not None
        assert scheduler.account_id == "default"
        assert scheduler.mode == "PAPER"
    finally:
        await bundle.database.close()


async def test_strategy_attaches_trace_to_decision_after_evidence(v2_db):
    from types import SimpleNamespace

    await seed_card(v2_db, rule_id="card_attach", status="ACTIVE")
    store = CardDecisionTraceStore(v2_db.session_factory)
    registry = LLMToolRegistry()
    register_experience_card_tool(
        registry, ExperienceCardRetriever(v2_db.session_factory), trace_store=store
    )
    evidence = await registry.call("experience_cards", "BTCUSDT", _tool_context())
    trace_id = evidence.features["card_trace_id"]

    class Audit:
        def __init__(self):
            self.events = []

        async def log(self, action, **kwargs):
            self.events.append((action, kwargs))

    from crypto_trader.llm_chief.runtime_strategy import LiveLLMDecisionStrategy

    strategy = object.__new__(LiveLLMDecisionStrategy)
    strategy.card_trace_store = store
    strategy.audit = Audit()
    package = SimpleNamespace(
        items=[SimpleNamespace(finding={"card_trace_id": trace_id})]
    )
    decision = SimpleNamespace(decision_id="decision_attach_1")
    await strategy._attach_card_decision_trace(
        decision, package, SimpleNamespace(run_id="run_attach")
    )
    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(GrowthCardDecisionTraceORM).where(
                    GrowthCardDecisionTraceORM.trace_id == trace_id
                )
            )
        ).scalar_one()
    assert row.decision_id == "decision_attach_1"
    assert strategy.audit.events == []


class _FakeStructuredRunner:
    def __init__(self, status: str = "SUCCEEDED"):
        self.status = status
        self.calls = []

    async def run_day(self, episodes, **kwargs):
        self.calls.append([episode.episode_id for episode in episodes])
        reviewed = (
            [episode.episode_id for episode in episodes]
            if self.status == "SUCCEEDED"
            else []
        )
        return {
            "status": self.status,
            "reviewed_episode_ids": reviewed,
            "attempts_total": len(episodes),
            "attempts_succeeded": len(reviewed),
            "attempts_failed": 0 if reviewed else len(episodes),
        }


async def test_scheduler_marks_only_llm_reviewed_episodes(v2_db):
    await _seed_daily_card_scenario(v2_db)
    runner = _FakeStructuredRunner("SUCCEEDED")
    scheduler = DailyReviewScheduler(
        v2_db.session_factory,
        canonical_only=True,
        structured_review_runner=runner,
        account_id="default",
        mode="PAPER",
    )
    result = await scheduler.run_once("2026-09-10")
    assert result["status"] == "SUCCEEDED"
    assert result["structured_review"]["status"] == "SUCCEEDED"
    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(TradeEpisodeORM).where(TradeEpisodeORM.episode_id == "ep_wire")
            )
        ).scalar_one()
    assert row.review_status == "REVIEWED"
    assert runner.calls == [["ep_wire"]]


async def test_scheduler_keeps_episode_pending_when_llm_review_fails(v2_db):
    await _seed_daily_card_scenario(v2_db)
    runner = _FakeStructuredRunner("FAILED")
    scheduler = DailyReviewScheduler(
        v2_db.session_factory,
        canonical_only=True,
        structured_review_runner=runner,
        account_id="default",
        mode="PAPER",
    )
    result = await scheduler.run_once("2026-09-10")
    assert result["status"] == "SUCCEEDED"
    assert result["structured_review"]["status"] == "FAILED"
    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(TradeEpisodeORM).where(TradeEpisodeORM.episode_id == "ep_wire")
            )
        ).scalar_one()
    assert row.review_status == "PENDING"


def test_reference_aliases_accept_prefix_stripped_ids():
    from datetime import UTC, datetime
    from decimal import Decimal

    from crypto_trader.learning.growth_contracts import EpisodeReviewInput

    moment = datetime(2026, 9, 10, tzinfo=UTC)
    review_input = EpisodeReviewInput(
        episode_id="episode_plan_abc",
        account_id="default",
        mode="PAPER",
        symbol="BTCUSDT",
        direction="LONG",
        order_refs=["ord_deadbeef"],
        fill_refs=["fill_feedface"],
        entry_price=Decimal("1"),
        exit_price=Decimal("2"),
        quantity=Decimal("1"),
        leverage=Decimal("1"),
        fees=Decimal("0"),
        funding_pnl=Decimal("0"),
        gross_pnl=Decimal("1"),
        net_pnl=Decimal("1"),
        opened_at=moment,
        closed_at=moment,
        entry_market_regime="BULL",
        terminal_reason="EXIT",
        risk_adjustments=[{"risk_decision_id": "risk_cafebabe"}],
        trade_plan={"trade_plan_id": "plan_deadbeef"},
    )
    refs = review_input.derived_refs()
    assert "order:ord_deadbeef" in refs and "order:deadbeef" in refs
    assert "fill:fill_feedface" in refs and "fill:feedface" in refs
    assert "risk:risk_cafebabe" in refs and "risk:cafebabe" in refs
    assert "trade_plan:plan_deadbeef" in refs and "trade_plan:deadbeef" in refs
    assert "episode:plan_abc" in refs
