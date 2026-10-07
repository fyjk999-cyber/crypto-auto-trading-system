"""Acceptance diagnostics observe the real engine, never grant authority."""

import asyncio
import json
from copy import deepcopy
from dataclasses import replace

import httpx
import pytest
from sqlalchemy import event

from crypto_trader.api.app import create_app
from crypto_trader.runtime.lease import LeaseManager
from tests.conftest import make_paper_engine
from tests.integration.test_api import make_state


async def test_unstarted_diagnostics_expose_actual_failures_and_no_first_eligibility(database):
    engine = make_paper_engine(database)
    snapshot = engine.acceptance_snapshot()
    assert snapshot["runtime_running"] is False
    assert "RUNTIME_NOT_RUNNING" in snapshot["trading_safety_failures"]
    assert snapshot["first_eligibility"] is None
    assert snapshot["workers"]["engine-events"]["live_count"] == 0
    assert snapshot["lease"]["current"] is False
    assert engine.risk_engine.kill_switch.enabled is False


async def test_first_actual_eligibility_is_bound_once_and_survives_later_failure(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    assert engine.trading_safety_failures()
    await engine.start("diagnostic-first-eligibility")
    try:
        assert engine.acceptance_snapshot()["first_eligibility"] is None
        assert engine.trading_safety_failures() == ()
        actual_authority_read = deepcopy(engine.lease_manager.last_authority_observation)
        first = engine.acceptance_snapshot()["first_eligibility"]
        assert first["trading_safety_failures"] == []
        assert first["runtime_running"] is True
        assert first["lease"]["current"] is True
        assert actual_authority_read.pop("token") == engine.lease.token
        assert {k: v for k, v in first["lease"].items() if k != "token_id"} == (
            actual_authority_read
        )
        assert len(first["lease"]["token_id"]) == 64
        assert engine.lease.token not in json.dumps(first)
        assert first["lease"]["checked_epoch"] < first["lease"]["expires_at"]
        assert first["lease"]["owner_id"] == "engine_diagnostic-first-eligibility"
        assert all(worker["live_count"] == 1 for worker in first["workers"].values())
        assert first["reconciliation"] == "COHERENT_OK"
        assert first["settlement"]["state"] == "COHERENT"
        # Returned data cannot overwrite the original process-lifetime record.
        damaged = engine.acceptance_snapshot()
        damaged["first_eligibility"]["lease"]["current"] = False
        engine.health.set("event_processing", False, "isolated error")
        assert "EVENT_PROCESSING_NOT_HEALTHY" in engine.trading_safety_failures()
        assert engine.acceptance_snapshot()["trading_safety_failures"] == list(
            engine.trading_safety_failures()
        )
        assert engine.acceptance_snapshot()["first_eligibility"] == first
        engine.health.set("event_processing", True)
        async def evaluate():
            return engine.trading_safety_failures()

        assert await asyncio.gather(*(evaluate() for _ in range(20))) == [()] * 20
        assert engine.trading_safety_failures() == ()
        assert engine.acceptance_snapshot()["first_eligibility"] == first
    finally:
        await engine.stop()
    successor = make_paper_engine(database)
    assert successor.acceptance_snapshot()["first_eligibility"] is None


@pytest.mark.parametrize("worker_name", ["engine-events", "engine-recon", "engine-ticks"])
async def test_diagnostics_report_actual_cancelled_worker(database, worker_name):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("diagnostic-task-state")
    try:
        assert engine.trading_safety_failures() == ()
        first = engine.acceptance_snapshot()["first_eligibility"]
        worker = next(task for task in engine._tasks if task.get_name() == worker_name)
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
        snapshot = engine.acceptance_snapshot()
        assert snapshot["workers"][worker_name]["live_count"] == 0
        assert snapshot["workers"][worker_name]["done"] is True
        assert snapshot["workers"][worker_name]["cancelled"] is True
        assert snapshot["trading_safety_failures"]
        assert snapshot["first_eligibility"] == first
    finally:
        await engine.stop()


async def test_expired_diagnostic_is_non_mutating(database, monkeypatch):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("diagnostic-neutral")
    try:
        assert engine.trading_safety_failures() == ()
        status = await engine.lease_manager.status(engine.lease_key)
        health = deepcopy(engine.health.components)
        kill = engine.risk_engine.kill_switch.snapshot()
        tasks = list(engine._tasks)
        settlement = deepcopy(engine.settlement.faults)
        previous_authority_read = deepcopy(engine.lease_manager.last_authority_observation)
        statements = []

        def record_sql(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lstrip().split()[0].upper())

        event.listen(engine.lease_manager._authority_reader, "before_cursor_execute", record_sql)
        event.listen(database.engine.sync_engine, "before_cursor_execute", record_sql)
        with monkeypatch.context() as frozen:
            frozen.setattr("crypto_trader.runtime.lease._epoch", lambda: status["expires_at"] + 1)
            snapshot = engine.acceptance_snapshot()
            assert snapshot["lease"]["current"] is False
            # Actual guard evaluation would engage a kill switch. GET may
            # neither perform that mutation nor publish an approximate result.
            assert snapshot["trading_safety_failures"] is None
            assert snapshot["trading_safety_evaluation_error"] == (
                "CENTRAL_PREDICATE_REQUIRES_LEASE_LOSS_SIDE_EFFECT"
            )
            assert snapshot["first_eligibility"]["lease"]["current"] is True
        assert statements == ["SELECT"]
        event.remove(engine.lease_manager._authority_reader, "before_cursor_execute", record_sql)
        event.remove(database.engine.sync_engine, "before_cursor_execute", record_sql)
        assert engine.health.components == health
        assert engine.risk_engine.kill_switch.snapshot() == kill
        assert engine._tasks == tasks
        assert engine.settlement.faults == settlement
        assert engine.lease_manager.last_authority_observation == previous_authority_read
        assert engine._lease_valid is True
    finally:
        await engine.stop()


async def test_capture_failure_cannot_change_safety_or_restamp_later(database, monkeypatch):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("diagnostic-capture-error")
    try:
        def unavailable(*args):
            raise RuntimeError("isolated diagnostic collection failure")

        with monkeypatch.context() as failure:
            failure.setattr(engine, "_acceptance_facts", unavailable)
            assert engine.trading_safety_failures() == ()
        snapshot = engine.acceptance_snapshot()
        assert snapshot["first_eligibility"] is None
        assert snapshot["first_eligibility_error"] == "CAPTURE_UNAVAILABLE"
        assert engine.trading_safety_failures() == ()
        assert engine.acceptance_snapshot()["first_eligibility"] is None
        assert engine.risk_engine.kill_switch.enabled is False
    finally:
        await engine.stop()


async def test_read_only_api_exposes_facts_and_missing_engine_is_unavailable(database):
    state = make_state(database)
    app = create_app(state)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://isolated"
    ) as client:
        assert (await client.get("/runtime/acceptance")).status_code == 503
        state.engine = make_paper_engine(database)
        response = await client.get("/runtime/acceptance")
        assert response.status_code == 200
        assert response.json()["runtime_running"] is False
        assert response.json()["first_eligibility"] is None
        assert (await client.post("/runtime/acceptance")).status_code == 405


async def test_unavailable_authority_is_explicit_not_cached_pass(database, monkeypatch):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("diagnostic-unavailable")
    try:
        assert engine.trading_safety_failures() == ()
        first = engine.acceptance_snapshot()["first_eligibility"]
        health = deepcopy(engine.health.components)

        def unavailable():
            raise RuntimeError("not for publication")

        with monkeypatch.context() as outage:
            outage.setattr(engine.lease_manager._authority_reader, "connect", unavailable)
            snapshot = engine.acceptance_snapshot()
        assert snapshot["lease"]["current"] is False
        assert snapshot["lease"]["error"] == {"type": "RuntimeError", "database_error": None}
        assert snapshot["lease"]["checked_epoch"] is None
        assert snapshot["trading_safety_failures"] is None
        assert snapshot["trading_safety_evaluation_error"] == (
            "CENTRAL_PREDICATE_REQUIRES_LEASE_LOSS_SIDE_EFFECT"
        )
        assert snapshot["first_eligibility"] == first
        assert engine.health.components == health
        assert engine.risk_engine.kill_switch.enabled is False
    finally:
        await engine.stop()


async def test_duplicate_actual_task_is_not_configured_single_worker(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("diagnostic-duplicate")
    duplicate = asyncio.create_task(asyncio.sleep(3600), name="engine-events")
    engine._tasks.append(duplicate)
    try:
        snapshot = engine.acceptance_snapshot()
        assert snapshot["workers"]["engine-events"]["live_count"] == 2
        assert "EVENT_WORKER_NOT_RUNNING" in snapshot["trading_safety_failures"]
        assert snapshot["first_eligibility"] is None
    finally:
        await engine.stop()


async def test_concurrent_first_evaluations_have_one_immutable_record(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("diagnostic-concurrent-first")
    try:
        assert engine.acceptance_snapshot()["first_eligibility"] is None

        async def evaluate():
            assert engine.trading_safety_failures() == ()
            return engine.acceptance_snapshot()["first_eligibility"]

        records = await asyncio.gather(*(evaluate() for _ in range(20)))
        assert records[0] is not None
        assert all(record == records[0] for record in records)
    finally:
        await engine.stop()


async def test_optional_token_serialization_cannot_change_committed_authority(database):
    manager = LeaseManager(database.session_factory)
    grant = await manager.acquire("diagnostic-format-boundary", "isolated-owner", 30)

    class DiagnosticEncodingUnavailable(str):
        def encode(self, *args, **kwargs):
            raise RuntimeError("isolated optional diagnostic encoding unavailable")

    identical_grant = replace(grant, token=DiagnosticEncodingUnavailable(grant.token))
    assert manager.is_current_now(identical_grant) is True


async def test_token_hash_failure_remains_diagnostic_only(database, monkeypatch):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("diagnostic-hash-error")
    try:
        def unavailable(*args):
            raise RuntimeError("isolated optional diagnostic hash failure")

        with monkeypatch.context() as failure:
            failure.setattr("crypto_trader.runtime.engine.sha256", unavailable)
            assert engine.trading_safety_failures() == ()
            assert engine.execution_lease_current() is True
            with pytest.raises(RuntimeError, match="optional diagnostic hash"):
                engine.acceptance_snapshot()
        snapshot = engine.acceptance_snapshot()
        assert snapshot["first_eligibility"] is None
        assert snapshot["first_eligibility_error"] == "CAPTURE_UNAVAILABLE"
        assert engine.risk_engine.kill_switch.enabled is False
    finally:
        await engine.stop()
