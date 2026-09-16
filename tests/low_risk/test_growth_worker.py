import json
from datetime import UTC, datetime, timedelta

from crypto_trader.learning.growth_worker import GrowthWorker
from crypto_trader.persistence.models import ScanSnapshotORM

FIXED_NOW = datetime(2026, 9, 16, 4, 0, tzinfo=UTC)
CAPTURED = datetime(2026, 9, 15, 4, 0, tzinfo=UTC)


class FakeClient:
    def __init__(self, rows=None, fail=False):
        self.rows = rows or []
        self.fail = fail

    async def get_candles(self, inst_id, bar, limit=300):
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
    assert first["memory_updates"] == first["outcomes_written"]
    assert (tmp_path / "growth_state.json").exists()
    assert (tmp_path / "growth_heartbeat.json").exists()
    heartbeat = json.loads((tmp_path / "growth_heartbeat.json").read_text())
    assert heartbeat["state"] == "ACCUMULATING" and heartbeat["cycles"] == 1
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
    assert state["state"] == "DEGRADED" and state["last_error"]
    assert worker.is_order is False and worker.can_modify_core is False
