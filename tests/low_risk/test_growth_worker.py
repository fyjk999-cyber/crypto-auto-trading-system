import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from crypto_trader.learning.growth_worker import GrowthWorker
from crypto_trader.persistence.models import ScanSnapshotORM

FIXED_NOW = datetime(2026, 9, 16, 4, 0, tzinfo=UTC)
CAPTURED = datetime(2026, 9, 15, 4, 0, tzinfo=UTC)


class FakeClient:
    def __init__(self, rows=None, fail=False):
        self.rows = rows or []
        self.fail = fail

    async def get_candles(self, inst_id, bar, limit=300, **kwargs):
        if self.fail:
            raise RuntimeError("okx_down")
        return self.rows


def _rows(start, minutes, price=100.0, step=0.01):
    out = []
    for i in range(minutes):
        ts = int((start + timedelta(minutes=i)).timestamp() * 1000)
        value = price + i * step
        out.append(
            [
                str(ts),
                str(value),
                str(value + 0.05),
                str(value - 0.05),
                str(value),
                "1",
                "1",
                "1",
                "1",
            ]
        )
    return out


def _observation():
    return ScanSnapshotORM(
        snapshot_id="obs-w1",
        captured_at=CAPTURED,
        cycle_id="c",
        trading_day="2026-09-15",
        snapshot_version="scan-snapshot-v1",
        snapshot_hash="h1",
        symbol="BTCUSDT",
        candidate=True,
        control=False,
        scanner_score=7.5,
        selection_reason="FACTOR_SCANNER",
        features_json={"price": 100.0, "costs": {"total_cost_bps": 22.0}},
    )


async def test_worker_cycle_idempotent_and_heartbeat(database, tmp_path):
    async with database.session_factory() as session:
        session.add(_observation())
        await session.commit()
    client = FakeClient(_rows(CAPTURED - timedelta(minutes=5), 1460))
    worker = GrowthWorker(database.session_factory, tmp_path, client, code_sha="sha-worker")
    first = await worker.run_once(now=FIXED_NOW)
    assert first["top10"] == "FROZEN"
    assert first["outcomes_written"] == 8
    assert first["memory_updates"] == 0  # direction_source=NONE is not a factual directional win
    assert worker.metrics["nondirectional_opportunities_skipped"] == first["outcomes_written"]
    assert (tmp_path / "growth_state.json").exists()
    assert (tmp_path / "growth_heartbeat.json").exists()
    heartbeat = json.loads((tmp_path / "growth_heartbeat.json").read_text())
    assert heartbeat["state"] == "DEGRADED_SOURCE_MISSING" and heartbeat["cycles"] == 1
    assert heartbeat["scan_source_ok"] is False
    assert heartbeat["stage"] == "CYCLE_COMPLETE"
    assert heartbeat["runtime_sha"] == "sha-worker"
    second = await worker.run_once(now=FIXED_NOW)
    assert second["top10"] == "ALREADY_FROZEN"
    assert second["outcomes_written"] == 0 and second["memory_updates"] == 0
    heartbeat2 = json.loads((tmp_path / "growth_heartbeat.json").read_text())
    assert heartbeat2["cycles"] == 2


async def test_worker_records_degraded_without_trading_impact(database, tmp_path, monkeypatch):
    from crypto_trader.learning import growth_worker as worker_module

    async def boom(*args, **kwargs):
        raise RuntimeError("db_down")

    monkeypatch.setattr(worker_module.ledger_freeze, "freeze_completed_day", boom)
    worker = GrowthWorker(
        database.session_factory, tmp_path, FakeClient(fail=True), code_sha="sha-worker"
    )
    result = await worker.run_once(now=FIXED_NOW)
    assert result["errors"] and any(e.startswith("top10:") for e in result["errors"])
    state = json.loads((tmp_path / "growth_state.json").read_text())
    assert state["state"] == "DEGRADED_SOURCE_MISSING" and state["last_error"]
    assert worker.is_order is False and worker.can_modify_core is False


async def test_direction_and_regime_semantics_without_hindsight(database, tmp_path):
    from crypto_trader.learning.memory_speed_store import MemorySpeedStore
    from crypto_trader.persistence.models import OpportunityOutcomeMaturationORM

    async with database.session_factory() as session:
        session.add(
            ScanSnapshotORM(
                snapshot_id="obs-dir",
                captured_at=CAPTURED,
                cycle_id="c",
                trading_day="2026-09-15",
                snapshot_version="scan-snapshot-v1",
                symbol="BTCUSDT",
                candidate=True,
                control=False,
                scanner_score=1.0,
                market_regime="TREND_UP",
                features_json={"price": 100.0, "decision_id": "d1", "expected_direction": "LONG"},
            )
        )
        session.add(
            OpportunityOutcomeMaturationORM(
                observation_id="obs-dir",
                trading_day="2026-09-15",
                symbol="BTCUSDT",
                horizon="1h",
                outcome_version="outcome-v1",
                direction_source="CORE_LLM",
                expected_direction="LONG",
                long_net_bps=-50.0,
                short_net_bps=200.0,
                long_gross_bps=-28.0,
                short_gross_bps=178.0,
                all_in_cost_bps=22.0,
                maturation_status="MATURE_VALID",
                usable_for_learning=True,
                alignment_ok=True,
                data_gap=False,
            )
        )
        session.add(
            OpportunityOutcomeMaturationORM(
                observation_id="obs-nodir",
                trading_day="2026-09-15",
                symbol="ETHUSDT",
                horizon="1h",
                outcome_version="outcome-v1",
                direction_source="NONE",
                long_net_bps=500.0,
                short_net_bps=-500.0,
            )
        )
        await session.commit()

    worker = GrowthWorker(database.session_factory, tmp_path, FakeClient(), code_sha="sha")
    updated = await worker._update_memory()
    assert updated == 1  # only the factual-direction row may update memory
    record = await MemorySpeedStore(database.session_factory).load("BTCUSDT|1h|outcome-v1")
    assert record.net_bps_total == -50.0  # LONG decision used, not hindsight best side
    assert record.regimes == ["TREND_UP"]  # not the direction_source string
    assert record.win_rate == 0.0
    assert worker.metrics["nondirectional_opportunities_skipped"] == 1


def _make_source_db(path, rows):
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE scan_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_id TEXT,
        captured_at TEXT, cycle_id TEXT, symbol TEXT, candidate INTEGER,
        control INTEGER, scanner_score REAL, selection_reason TEXT,
        market_regime TEXT, features_json TEXT, outcome_status TEXT)""")
    for row in rows:
        conn.execute(
            "INSERT INTO scan_snapshots (snapshot_id, captured_at, cycle_id, symbol,"
            " candidate, control, scanner_score, selection_reason, market_regime,"
            " features_json, outcome_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            row,
        )
    conn.commit()
    conn.close()


async def test_scan_source_backfill_and_continuous_ingest(database, tmp_path):
    import sqlite3

    source = tmp_path / "source.db"
    features = '{"price": 100.0, "costs": {"total_cost_bps": 22.0}}'
    _make_source_db(
        source,
        [
            (
                "obs-src-1",
                CAPTURED.isoformat(),
                "c1",
                "BTCUSDT",
                1,
                0,
                5.0,
                "FACTOR_SCANNER",
                "TREND_UP",
                features,
                "PENDING",
            ),
            (
                "obs-src-2",
                CAPTURED.isoformat(),
                "c1",
                "ETHUSDT",
                0,
                1,
                0.0,
                "CONTROL_SAMPLE",
                "RANGE",
                features,
                "PENDING",
            ),
        ],
    )
    worker = GrowthWorker(
        database.session_factory,
        tmp_path / "derived",
        FakeClient(_rows(CAPTURED - timedelta(minutes=5), 1460)),
        code_sha="sha",
        scan_source_db=str(source),
    )
    first = await worker.run_once(now=FIXED_NOW)
    assert first["scan_status"] == "OK" and first["scan_ingested"] == 2
    assert first["top10"] == "FROZEN"
    async with database.session_factory() as session:
        from crypto_trader.persistence.models import ScanSnapshotORM

        count = await session.scalar(select(func.count()).select_from(ScanSnapshotORM))
    assert count == 2
    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    assert conn.execute("SELECT COUNT(*) FROM scan_snapshots").fetchone()[0] == 2
    conn.close()

    conn = sqlite3.connect(source)
    conn.execute(
        "INSERT INTO scan_snapshots (snapshot_id, captured_at, cycle_id, symbol,"
        " candidate, control, scanner_score, selection_reason, market_regime,"
        " features_json, outcome_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "obs-src-3",
            (CAPTURED + timedelta(hours=1)).isoformat(),
            "c2",
            "SOLUSDT",
            1,
            0,
            3.0,
            "FACTOR_SCANNER",
            "TREND_UP",
            features,
            "PENDING",
        ),
    )
    conn.commit()
    conn.close()
    second = await worker.run_once(now=FIXED_NOW)
    assert second["scan_ingested"] == 1
    async with database.session_factory() as session:
        from crypto_trader.persistence.models import ScanSnapshotORM

        count2 = await session.scalar(select(func.count()).select_from(ScanSnapshotORM))
    assert count2 == 3  # no duplicates


async def test_data_gap_outcome_cannot_update_memory(database, tmp_path):
    from crypto_trader.learning.memory_speed_store import MemorySpeedStore
    from crypto_trader.persistence.models import OpportunityOutcomeMaturationORM

    async with database.session_factory() as session:
        session.add(
            OpportunityOutcomeMaturationORM(
                observation_id="obs-gap",
                symbol="BTCUSDT",
                horizon="1h",
                outcome_version="outcome-v1",
                direction_source="CORE_LLM",
                expected_direction="LONG",
                long_net_bps=500.0,
                short_net_bps=-500.0,
                maturation_status="INCONCLUSIVE_DATA_GAP",
                usable_for_learning=False,
                alignment_ok=False,
                data_gap=True,
            )
        )
        await session.commit()
    worker = GrowthWorker(database.session_factory, tmp_path, FakeClient(), code_sha="sha")
    updated = await worker._update_memory()
    assert updated == 0
    assert worker.metrics["memory_rows_rejected_quality"] == 1
    assert await MemorySpeedStore(database.session_factory).load("BTCUSDT|1h|outcome-v1") is None


async def test_effective_batches_defaults_and_override(database, tmp_path, monkeypatch):
    monkeypatch.delenv("GROWTH_OUTCOME_BATCH", raising=False)
    default = GrowthWorker(database.session_factory, tmp_path / "d1", FakeClient())
    assert default.outcome_batch == 25
    monkeypatch.setenv("GROWTH_OUTCOME_BATCH", "7")
    override = GrowthWorker(database.session_factory, tmp_path / "d2", FakeClient())
    assert override.outcome_batch == 7


async def test_run_once_wires_outcome_batch_and_stage_truth(database, tmp_path, monkeypatch):
    from crypto_trader.learning import growth_worker as worker_module

    stages = []
    internal = []
    original_stage = GrowthWorker._heartbeat_stage
    original_ingest = GrowthWorker._ingest_scan_source

    def spy_stage(self, name):
        stages.append(name)
        return original_stage(self, name)

    async def spy_ingest(self, *args, **kwargs):
        heartbeat = json.loads((tmp_path / "growth_heartbeat.json").read_text())
        internal.append(
            (heartbeat["stage"], heartbeat["cycles_started"], heartbeat["cycles_completed"])
        )
        return await original_ingest(self, *args, **kwargs)

    monkeypatch.setattr(GrowthWorker, "_heartbeat_stage", spy_stage)
    monkeypatch.setattr(GrowthWorker, "_ingest_scan_source", spy_ingest)
    calls = {}
    original_mature = worker_module.outcome_maturer.mature_due

    async def spy_mature(*args, **kwargs):
        heartbeat = json.loads((tmp_path / "growth_heartbeat.json").read_text())
        calls["stage"] = heartbeat["stage"]
        calls["max_work_items"] = kwargs.get("max_work_items")
        return await original_mature(*args, **kwargs)

    monkeypatch.setattr(worker_module.outcome_maturer, "mature_due", spy_mature)
    monkeypatch.setenv("GROWTH_OUTCOME_BATCH", "7")
    worker = GrowthWorker(database.session_factory, tmp_path, FakeClient(), code_sha="sha")
    result = await worker.run_once(now=FIXED_NOW)
    assert calls["stage"] == "OUTCOME_MATURATION"
    assert calls["max_work_items"] == 7
    assert result["due_work_items"] <= 7
    assert stages[:2] == ["CYCLE_START", "SCAN_INGEST"]
    assert "OUTCOME_MATURATION" in stages and stages[-1] == "CYCLE_COMPLETE"
    assert internal[0][0] == "SCAN_INGEST"
    assert internal[0][1] == 1 and internal[0][2] == 0
    heartbeat = json.loads((tmp_path / "growth_heartbeat.json").read_text())
    assert heartbeat["cycles_started"] == 1 and heartbeat["cycles_completed"] == 1
    assert heartbeat["effective_outcome_batch"] == 7
    assert heartbeat["stage"] == "CYCLE_COMPLETE"


async def test_maturer_exception_truth(database, tmp_path, monkeypatch):
    from crypto_trader.learning import growth_worker as worker_module

    async def boom(*args, **kwargs):
        raise RuntimeError("okx_down")

    monkeypatch.setattr(worker_module.outcome_maturer, "mature_due", boom)
    source = tmp_path / "empty-source.db"
    _make_source_db(source, [])
    worker = GrowthWorker(
        database.session_factory, tmp_path, FakeClient(), code_sha="sha", scan_source_db=str(source)
    )
    result = await worker.run_once(now=FIXED_NOW)
    assert any(e.startswith("outcomes:") for e in result["errors"])
    heartbeat = json.loads((tmp_path / "growth_heartbeat.json").read_text())
    assert heartbeat["cycles_started"] == 1 and heartbeat["cycles_completed"] == 1
    assert heartbeat["state"] == "DEGRADED_PROCESSING_ERROR"
