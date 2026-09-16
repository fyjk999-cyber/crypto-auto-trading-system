# ruff: noqa: E501
from __future__ import annotations

from datetime import UTC, datetime

from crypto_trader.news.models import MaterialityTier, ReassessmentStatus
from crypto_trader.news.reassessment import (
    NewsReassessmentRuntime,
    NewsReassessmentService,
)
from crypto_trader.news.repository import NewsRepository


class FakePlan:
    trade_plan_id = "plan_1"


class FakePosition:
    symbol = "BTCUSDT"
    quantity = 1


class FakePortfolio:
    def __init__(self, positions):
        self.positions = positions

    async def get_positions(self):
        return dict(self.positions)


class FakeTradePlans:
    async def get_active_for_symbol(self, symbol):
        return FakePlan() if symbol == "BTCUSDT" else None


class FakePositionManager:
    def __init__(self):
        self.calls = 0
        self.signal = None
        self.on_review = None
        self.force_flags = []

    async def review(self, ctx, position, *, force=False):
        self.calls += 1
        self.force_flags.append(force)
        if self.on_review is not None:
            self.on_review()
        return self.signal


class FakeEngine:
    def __init__(self, *, positions=None, state_version="state_1"):
        self.portfolio = FakePortfolio(positions if positions is not None else {"BTCUSDT": FakePosition()})
        self.trade_plans = FakeTradePlans()
        self.position_manager = FakePositionManager()
        self.state_version = state_version
        self.processed = []
        self.strategy_context_calls = 0

    def _position_state_version(self, position, plan):
        return self.state_version

    async def _strategy_context(self, symbol):
        self.strategy_context_calls += 1
        return object()

    async def process_signal(self, signal):
        self.processed.append(signal)
        return None


async def _request(repository, *, dedup_key="evt_1:1:BTCUSDT:ANY", tier=MaterialityTier.HIGH):
    return await repository.request_reassessment(
        event_id="evt_1",
        event_version=1,
        news_evidence_id="newsev_1",
        symbol="BTCUSDT",
        dedup_key=dedup_key,
        priority="HIGH",
        materiality_tier=tier,
        reason="NEWS:TEST",
        requested_at=datetime.now(UTC),
    )


async def test_news_wake_dispatches_through_canonical_review_only(database):
    repository = NewsRepository(database.session_factory)
    service = NewsReassessmentService(database.session_factory, repository=repository)
    runtime = NewsReassessmentRuntime(service)
    request = await _request(repository)
    assert request is not None
    engine = FakeEngine()
    metrics = await runtime.dispatch_due(engine)
    assert metrics["dispatched"] == 1
    assert engine.position_manager.calls == 1
    assert engine.position_manager.force_flags == [True]
    stored = await repository.get_reassessment(request.request_id)
    assert stored["status"] == ReassessmentStatus.COMPLETED.value


async def test_duplicate_event_version_state_is_suppressed(database):
    repository = NewsRepository(database.session_factory)
    service = NewsReassessmentService(database.session_factory, repository=repository)
    runtime = NewsReassessmentRuntime(service)
    first = await _request(repository, dedup_key="evt_1:1:BTCUSDT:ANY")
    second = await _request(repository, dedup_key="evt_1:1:BTCUSDT:ALT")
    engine = FakeEngine()
    await runtime.dispatch_due(engine)
    await runtime.dispatch_due(engine)
    assert engine.position_manager.calls == 1
    first_row = await repository.get_reassessment(first.request_id)
    second_row = await repository.get_reassessment(second.request_id)
    assert first_row["status"] == ReassessmentStatus.COMPLETED.value
    assert second_row["status"] == ReassessmentStatus.SUPPRESSED.value


async def test_flat_runtime_is_safe_and_never_opens(database):
    repository = NewsRepository(database.session_factory)
    service = NewsReassessmentService(database.session_factory, repository=repository)
    runtime = NewsReassessmentRuntime(service)
    request = await _request(repository)
    engine = FakeEngine(positions={})
    metrics = await runtime.dispatch_due(engine)
    assert metrics["flat_skipped"] == 1
    assert engine.position_manager.calls == 0
    assert engine.processed == []
    stored = await repository.get_reassessment(request.request_id)
    assert stored["status"] == ReassessmentStatus.SKIPPED_FLAT.value


async def test_state_version_change_during_news_review_marks_stale(database):
    repository = NewsRepository(database.session_factory)
    service = NewsReassessmentService(database.session_factory, repository=repository)
    runtime = NewsReassessmentRuntime(service)
    request = await _request(repository)
    engine = FakeEngine()

    def change_state():
        engine.state_version = "state_2"

    engine.position_manager.on_review = change_state
    metrics = await runtime.dispatch_due(engine)
    assert metrics["stale"] == 1
    stored = await repository.get_reassessment(request.request_id)
    assert stored["status"] == ReassessmentStatus.STALE.value


async def test_materiality_priority_order_for_runtime_queue(database):
    repository = NewsRepository(database.session_factory)
    await _request(repository, dedup_key="critical", tier=MaterialityTier.CRITICAL)
    await _request(repository, dedup_key="high", tier=MaterialityTier.HIGH)
    await _request(repository, dedup_key="medium", tier=MaterialityTier.MEDIUM)
    pending = await repository.list_pending_reassessments(limit=10, symbol="BTCUSDT")
    assert [row["materiality_tier"] for row in pending] == ["CRITICAL", "HIGH", "MEDIUM"]
