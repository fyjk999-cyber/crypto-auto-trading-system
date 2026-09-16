# ruff: noqa: ASYNC240
# Autonomous Growth worker orchestration (LEARNING_ONLY; restart-safe).
from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from crypto_trader.learning.memory_speed_store import MemorySpeedStore
from crypto_trader.learning.memory_speeds import MemoryRecord, apply_observation
from crypto_trader.market_data.opportunity import ledger_freeze, outcome_maturer
from crypto_trader.persistence.models import (
    OpportunityOutcomeMaturationORM,
    ScanSnapshotORM,
)

STATE_FILE = "growth_state.json"
HEARTBEAT_FILE = "growth_heartbeat.json"
METRICS_FILE = "growth_metrics.json"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, default=str))
    temp.replace(path)


class GrowthWorker:
    authority = "LEARNING_ONLY"
    is_order = False
    can_modify_core = False

    def __init__(
        self,
        session_factory,
        base_dir,
        client,
        *,
        code_sha: str = "",
        scan_source_db: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.base_dir = Path(base_dir)
        self.client = client
        self.code_sha = code_sha
        self.scan_source_db = scan_source_db
        self.state_path = self.base_dir / STATE_FILE
        self.heartbeat_path = self.base_dir / HEARTBEAT_FILE
        self.metrics_path = self.base_dir / METRICS_FILE
        self.state = self._load_state()
        self.metrics = self.state.get("metrics", {})

    def _load_state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        return {
            "state": "WAITING_FOR_DATA",
            "last_memory_maturation_id": 0,
            "cycles": 0,
            "last_error": None,
            "metrics": {},
        }

    def _save(self, *, state: str, last_error: str | None = None) -> None:
        self.state.update(
            {
                "state": state,
                "last_error": last_error,
                "runtime_sha": self.code_sha,
                "updated_at": datetime.now(UTC).isoformat(),
                "metrics": self.metrics,
            }
        )
        _write_json(self.state_path, self.state)
        _write_json(self.metrics_path, self.metrics)
        _write_json(
            self.heartbeat_path,
            {
                "pid": os.getpid(),
                "at": datetime.now(UTC).isoformat(),
                "state": state,
                "cycles": self.state.get("cycles", 0),
                "runtime_sha": self.code_sha,
                "scan_source_path": self.scan_source_db,
                "scan_source_ok": bool(self.scan_source_db and Path(self.scan_source_db).exists()),
                "scan_source_latest_id": self.state.get("last_scan_source_id", 0),
                "derived_db_path": str(self.base_dir),
                "last_error": last_error,
                "metrics": self.metrics,
            },
        )

    def _heartbeat_stage(self, stage: str) -> None:
        now = datetime.now(UTC).isoformat()
        self.state["stage"] = stage
        self.state["stage_started_at"] = now
        self.state["last_progress_at"] = now
        _write_json(
            self.heartbeat_path,
            {
                "pid": os.getpid(),
                "at": now,
                "state": self.state.get("state", "STARTING"),
                "stage": stage,
                "cycles": self.state.get("cycles", 0),
                "runtime_sha": self.code_sha,
                "cycle_started_at": self.state.get("cycle_started_at"),
                "stage_started_at": now,
                "last_progress_at": now,
                "source_cursor": self.state.get("last_scan_source_id", 0),
                "scan_source_path": self.scan_source_db,
                "scan_source_ok": bool(self.scan_source_db and Path(self.scan_source_db).exists()),
                "derived_db_path": str(self.base_dir),
                "last_error": self.state.get("last_error"),
                "metrics": self.metrics,
            },
        )

    async def _ingest_scan_source(self, batch: int = 500) -> dict:
        if not self.scan_source_db or not Path(self.scan_source_db).exists():
            return {"status": "SOURCE_MISSING", "ingested": 0, "seen": 0}
        cursor = int(self.state.get("last_scan_source_id", 0))
        conn = sqlite3.connect(f"file:{self.scan_source_db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            info = {row[1] for row in conn.execute("PRAGMA table_info(scan_snapshots)")}
            if not info:
                return {"status": "SOURCE_TABLE_MISSING", "ingested": 0, "seen": 0}
            rows = conn.execute(
                "SELECT * FROM scan_snapshots WHERE id > ? ORDER BY id LIMIT ?",
                (cursor, batch),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return {"status": "OK", "ingested": 0, "seen": 0, "latest_id": cursor}
        ingested = 0
        async with self._session_factory() as session:
            for raw in rows:
                row = dict(raw)
                snapshot_id = row["snapshot_id"]
                existing = await session.scalar(
                    select(ScanSnapshotORM.id).where(ScanSnapshotORM.snapshot_id == snapshot_id)
                )
                if existing is None:
                    captured = row.get("captured_at")
                    captured = (
                        datetime.fromisoformat(str(captured)) if captured else datetime.now(UTC)
                    )
                    if captured.tzinfo is None:
                        captured = captured.replace(tzinfo=UTC)
                    trading_day = row.get("trading_day") or (
                        captured.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
                    )
                    features = row.get("features_json")
                    if isinstance(features, str):
                        features = json.loads(features)
                    session.add(
                        ScanSnapshotORM(
                            snapshot_id=snapshot_id,
                            captured_at=captured,
                            cycle_id=row.get("cycle_id") or "source-ingest",
                            trading_day=trading_day,
                            snapshot_version=row.get("snapshot_version") or "scan-snapshot-v1",
                            snapshot_hash=row.get("snapshot_hash"),
                            symbol=row["symbol"],
                            candidate=bool(row.get("candidate")),
                            control=bool(row.get("control")),
                            scanner_rank=row.get("scanner_rank"),
                            scanner_score=row.get("scanner_score"),
                            selection_reason=row.get("selection_reason") or "",
                            sampling_method=row.get("sampling_method") or "",
                            selection_probability=row.get("selection_probability"),
                            market_regime=row.get("market_regime"),
                            features_json=features,
                            outcome_status=row.get("outcome_status") or "PENDING",
                        )
                    )
                    ingested += 1
                cursor = max(cursor, int(row["id"]))
            await session.commit()
        self.state["last_scan_source_id"] = cursor
        return {"status": "OK", "ingested": ingested, "seen": len(rows), "latest_id": cursor}

    async def _update_memory(self) -> int:
        cursor = int(self.state.get("last_memory_maturation_id", 0))
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(OpportunityOutcomeMaturationORM)
                        .where(OpportunityOutcomeMaturationORM.id > cursor)
                        .order_by(OpportunityOutcomeMaturationORM.id)
                        .limit(200)
                    )
                )
                .scalars()
                .all()
            )
        if not rows:
            return 0
        observation_ids = [row.observation_id for row in rows]
        async with self._session_factory() as session:
            regime_rows = (
                await session.execute(
                    select(ScanSnapshotORM.snapshot_id, ScanSnapshotORM.market_regime).where(
                        ScanSnapshotORM.snapshot_id.in_(observation_ids)
                    )
                )
            ).all()
        regimes = {row[0]: (row[1] or "UNKNOWN") for row in regime_rows}
        store = MemorySpeedStore(self._session_factory)
        updated = 0
        skipped = 0
        for row in rows:
            direction_source = str(row.direction_source or "NONE")
            direction = str(row.expected_direction or "").upper()
            if direction_source not in ("CORE_LLM", "EVIDENCE_REFERENCE") or direction not in (
                "LONG",
                "SHORT",
            ):
                skipped += 1
                cursor = max(cursor, int(row.id))
                continue
            net = float(row.long_net_bps if direction == "LONG" else row.short_net_bps)
            key = f"{row.symbol}|{row.horizon}|{row.outcome_version}"
            record = await store.load(key) or MemoryRecord(
                key=key, signature=f"{row.symbol}|{row.horizon}"
            )
            apply_observation(
                record,
                net_bps=net,
                regime=regimes.get(row.observation_id, "UNKNOWN"),
                win=net > 0,
                post_cost_bps=net,
                chronological_stable=True,
                contradiction=net < 0 and record.observations >= 100,
            )
            await store.save(record)
            updated += 1
            cursor = max(cursor, int(row.id))
        self.state["last_memory_maturation_id"] = cursor
        self.metrics["nondirectional_opportunities_skipped"] = (
            int(self.metrics.get("nondirectional_opportunities_skipped", 0)) + skipped
        )
        return updated

    async def run_once(self, *, now: datetime | None = None) -> dict:
        moment = now or datetime.now(UTC)
        self.state["cycles"] = int(self.state.get("cycles", 0)) + 1
        summary = {
            "scan_status": None,
            "scan_ingested": 0,
            "top10": None,
            "outcomes_written": 0,
            "memory_updates": 0,
            "errors": [],
        }
        self._heartbeat_stage("SCAN_INGEST")
        try:
            scan = await self._ingest_scan_source()
            summary["scan_status"] = scan.get("status")
            summary["scan_ingested"] = int(scan.get("ingested", 0))
        except Exception as exc:
            summary["errors"].append(f"scan:{type(exc).__name__}")
        self._heartbeat_stage("TOP10")
        try:
            day = ledger_freeze.latest_completed_trading_day(moment)
            frozen = await ledger_freeze.freeze_completed_day(self._session_factory, day)
            summary["top10"] = frozen.get("status")
        except Exception as exc:
            summary["errors"].append(f"top10:{type(exc).__name__}")
        try:
            matured = await outcome_maturer.mature_due(
                self._session_factory, self.client, now=moment
            )
            summary["outcomes_written"] = int(matured.get("written", 0))
        except Exception as exc:
            summary["errors"].append(f"outcomes:{type(exc).__name__}")
        self._heartbeat_stage("MEMORY_UPDATE")
        try:
            summary["memory_updates"] = await self._update_memory()
        except Exception as exc:
            summary["errors"].append(f"memory:{type(exc).__name__}")
        self.metrics["top10_frozen"] = int(self.metrics.get("top10_frozen", 0)) + (
            1 if summary["top10"] == "FROZEN" else 0
        )
        self.metrics["outcomes_written"] = (
            int(self.metrics.get("outcomes_written", 0)) + summary["outcomes_written"]
        )
        self.metrics["memory_updates"] = (
            int(self.metrics.get("memory_updates", 0)) + summary["memory_updates"]
        )
        self.metrics["source_scan_rows_ingested"] = (
            int(self.metrics.get("source_scan_rows_ingested", 0)) + summary["scan_ingested"]
        )
        self.metrics["errors"] = int(self.metrics.get("errors", 0)) + len(summary["errors"])
        if summary["scan_status"] in ("SOURCE_MISSING", "SOURCE_TABLE_MISSING"):
            state = "DEGRADED_SOURCE_MISSING"
        elif summary["errors"]:
            state = "DEGRADED_PROCESSING_ERROR"
        else:
            state = "ACCUMULATING"
        self._save(state=state, last_error=";".join(summary["errors"]) or None)
        self._heartbeat_stage("CYCLE_COMPLETE")
        return summary
