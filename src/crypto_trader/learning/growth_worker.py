# ruff: noqa: ASYNC240
# Autonomous Growth worker orchestration (LEARNING_ONLY; restart-safe).
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from crypto_trader.learning.lifecycle_reviews import LifecycleReviewEngine
from crypto_trader.learning.memory_speed_store import MemorySpeedStore
from crypto_trader.learning.memory_speeds import MemoryRecord, apply_observation
from crypto_trader.learning.pattern_profile import GrowthMemoryPipeline
from crypto_trader.learning.trading_source import GrowthTradingSource
from crypto_trader.market_data.opportunity import ledger_freeze, outcome_maturer
from crypto_trader.persistence.models import (
    AIMarketPatternORM,
    GrowthEventReviewORM,
    GrowthMemoryVersionORM,
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


def _source_identity(source_path: str | None) -> str | None:
    if not source_path:
        return None
    path = Path(source_path)
    try:
        stat = path.stat()
        return f"{path.resolve()}:{stat.st_dev}:{stat.st_ino}"
    except OSError:
        return str(path.resolve())


def _resume_plan_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
        trading_source_db: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.base_dir = Path(base_dir)
        self.client = client
        self.code_sha = code_sha
        self.scan_source_db = scan_source_db
        self.trading_source_db = trading_source_db
        self.scan_batch = self._int_env("GROWTH_SCAN_BATCH", 500, 1, 5000)
        self.outcome_batch = self._int_env("GROWTH_OUTCOME_BATCH", 25, 1, 1000)
        self.memory_batch = self._int_env("GROWTH_MEMORY_BATCH", 200, 1, 5000)
        self.review_batch = self._int_env("GROWTH_REVIEW_BATCH", 100, 1, 1000)
        self.resume_source_identity = _source_identity(scan_source_db or trading_source_db)
        self.resume_plan_hash = _resume_plan_hash(
            {
                "code_sha": code_sha,
                "scan_source_db": scan_source_db,
                "trading_source_db": trading_source_db,
                "GROWTH_SCAN_BATCH": self.scan_batch,
                "GROWTH_OUTCOME_BATCH": self.outcome_batch,
                "GROWTH_MEMORY_BATCH": self.memory_batch,
                "GROWTH_REVIEW_BATCH": self.review_batch,
            }
        )
        self.state_path = self.base_dir / STATE_FILE
        self.heartbeat_path = self.base_dir / HEARTBEAT_FILE
        self.metrics_path = self.base_dir / METRICS_FILE
        self.state = self._load_state()
        self.metrics = self.state.get("metrics", {})

    @staticmethod
    def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
        raw = os.environ.get(name)
        if raw in (None, ""):
            return default
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, value))

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
                "resume_source_identity": self.resume_source_identity,
                "resume_plan_hash": self.resume_plan_hash,
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
                "cycles_started": self.state.get("cycles_started", 0),
                "cycles_completed": self.state.get("cycles_completed", 0),
                "runtime_sha": self.code_sha,
                "scan_source_path": self.scan_source_db,
                "scan_source_ok": bool(self.scan_source_db and Path(self.scan_source_db).exists()),
                "scan_source_latest_id": self.state.get("last_scan_source_id", 0),
                "derived_db_path": str(self.base_dir),
                "last_error": last_error,
                "metrics": self.metrics,
                "resume_source_identity": self.resume_source_identity,
                "resume_plan_hash": self.resume_plan_hash,
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
                "cycles_started": self.state.get("cycles_started", 0),
                "cycles_completed": self.state.get("cycles_completed", 0),
                "effective_scan_batch": self.scan_batch,
                "effective_outcome_batch": self.outcome_batch,
                "effective_memory_batch": self.memory_batch,
                "effective_review_batch": self.review_batch,
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

    async def _update_memory(self, limit: int = 200) -> int:
        cursor = int(self.state.get("last_memory_maturation_id", 0))
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(OpportunityOutcomeMaturationORM)
                        .where(OpportunityOutcomeMaturationORM.id > cursor)
                        .order_by(OpportunityOutcomeMaturationORM.id)
                        .limit(limit)
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
        rejected = 0
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
            if (
                row.maturation_status != "MATURE_VALID"
                or not row.usable_for_learning
                or not row.alignment_ok
                or row.data_gap
            ):
                rejected += 1
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
        self.metrics["memory_rows_rejected_quality"] = (
            int(self.metrics.get("memory_rows_rejected_quality", 0)) + rejected
        )
        return updated

    async def _ingest_trading_lifecycle(self, batch: int = 100) -> dict:
        source = GrowthTradingSource(self.trading_source_db)
        if not source.available():
            return {"status": "SOURCE_MISSING", "seen": 0, "created": 0}
        if not source.has_contract():
            return {"status": "NO_SOURCE_CONTRACT", "seen": 0, "created": 0}
        cursor = int(self.state.get("last_trading_event_id", 0))
        rows = source.events_after(cursor, batch)
        engine = LifecycleReviewEngine(self._session_factory)
        created = 0
        by_episode: dict[str, list[dict]] = {}
        for row in rows:
            episode_id = str(row.get("episode_id") or "")
            if not episode_id:
                continue
            payload = row.get("payload_json")
            if isinstance(payload, str):
                import json as _json

                try:
                    payload = _json.loads(payload)
                except ValueError:
                    payload = {}
            event = dict(payload or {})
            event.setdefault("event_id", f"src-{row.get('id')}")
            event.setdefault("kind", row.get("kind") or row.get("action") or "")
            by_episode.setdefault(episode_id, []).append(event)
        for episode_id, events in by_episode.items():
            created += await engine.ingest_events(episode_id, events)
            cursor_id = max(
                int(row.get("id") or 0) for row in rows if str(row.get("episode_id")) == episode_id
            )
            cursor = max(cursor, cursor_id)
        self.state["last_trading_event_id"] = cursor
        metrics = self.metrics
        metrics["trade_events_seen"] = int(metrics.get("trade_events_seen", 0)) + len(rows)
        metrics["reviews_created"] = int(metrics.get("reviews_created", 0)) + created
        return {"status": "OK", "seen": len(rows), "created": created}

    async def _mature_due_reviews(self, limit: int = 100) -> dict:
        engine = LifecycleReviewEngine(self._session_factory)
        pending = await engine.pending(limit=limit)
        matured = inconclusive = 0
        for review in pending:
            event = (review.get("actual_json") or {}).get("event") or {}
            facts = event.get("maturity_facts")
            if not isinstance(facts, dict) or not facts:
                continue  # remains PENDING until factual inputs exist
            result = await engine.resolve_maturity(review["review_id"], facts)
            if result and result.get("status") == "MATURE":
                matured += 1
            elif result and result.get("status") == "INCONCLUSIVE":
                inconclusive += 1
        self.metrics["reviews_matured"] = int(self.metrics.get("reviews_matured", 0)) + matured
        self.metrics["reviews_inconclusive"] = (
            int(self.metrics.get("reviews_inconclusive", 0)) + inconclusive
        )
        return {"matured": matured, "inconclusive": inconclusive}

    async def _apply_reviewed_patterns(self, limit: int = 100) -> dict:
        cursor = int(self.state.get("last_applied_review_id", 0))
        async with self._session_factory() as session:
            reviews = (
                (
                    await session.execute(
                        select(GrowthEventReviewORM)
                        .where(GrowthEventReviewORM.id > cursor)
                        .where(GrowthEventReviewORM.status == "MATURE")
                        .order_by(GrowthEventReviewORM.id)
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        pipeline = GrowthMemoryPipeline(self._session_factory)
        updated = profiles = compressed = rejected = generalized_updates = 0
        validated_compressed = 0
        for review in reviews:
            actual = (review.actual_json or {}).get("event") or {}
            net = float(review.actual_net_bps or 0.0)
            episode = {
                "episode_id": review.episode_id,
                "symbol": actual.get("symbol") or "UNKNOWN",
                "regime": actual.get("regime") or "UNKNOWN",
                "strategy": actual.get("strategy"),
                "horizon": actual.get("horizon") or review.maturity_horizon,
                "setup_signature": actual.get("setup_signature") or actual.get("setup"),
                "direction": actual.get("direction"),
                "post_cost_net_bps": net,
                "win": net > 0,
                "mfe_bps": review.mfe_bps or 0.0,
                "mae_bps": review.mae_bps or 0.0,
                "contradiction": str(review.verdict or "") in ("HARMFUL", "CONTRADICTION"),
            }
            result = await pipeline.update_from_episode(episode, reviewed=True)
            if result.get("status") == "UPDATED":
                updated += 1
                profiles += 1
                async with self._session_factory() as session:
                    pattern = (
                        await session.execute(
                            select(AIMarketPatternORM).where(
                                AIMarketPatternORM.pattern_key == result["pattern_key"]
                            )
                        )
                    ).scalar_one_or_none()
                if pattern is not None:
                    generalized = await pipeline.evaluate_generalized(
                        asset=pattern.asset or "UNKNOWN",
                        strategy=pattern.strategy or "UNKNOWN",
                        horizon=pattern.horizon or "UNKNOWN",
                        setup_signature=pattern.setup_signature or "UNKNOWN",
                    )
                    if generalized.get("status") in ("VALIDATED", "NOT_VALIDATED"):
                        generalized_updates += 1
                    if generalized.get("status") == "VALIDATED":
                        validated = await pipeline.compress_validated(generalized["generalized_id"])
                        if validated.get("status") == "CREATED":
                            validated_compressed += 1
                compression = await pipeline.compress(result["pattern_key"])
                if compression.get("status") == "CREATED":
                    compressed += 1
                elif compression.get("status") == "NOT_ELIGIBLE":
                    rejected += 1
            cursor = max(cursor, int(review.id))
        self.state["last_applied_review_id"] = cursor
        metrics = self.metrics
        metrics["pattern_updates"] = int(metrics.get("pattern_updates", 0)) + updated
        metrics["profile_updates"] = int(metrics.get("profile_updates", 0)) + profiles
        metrics["compressed_created"] = int(metrics.get("compressed_created", 0)) + compressed
        metrics["compressed_rejected"] = int(metrics.get("compressed_rejected", 0)) + rejected
        metrics["generalized_updates"] = (
            int(metrics.get("generalized_updates", 0)) + generalized_updates
        )
        metrics["validated_compressed_created"] = (
            int(metrics.get("validated_compressed_created", 0)) + validated_compressed
        )
        return {
            "patterns": updated,
            "profiles": profiles,
            "compressed": compressed,
            "generalized": generalized_updates,
            "validated_compressed": validated_compressed,
        }

    async def run_once(self, *, now: datetime | None = None) -> dict:
        moment = now or datetime.now(UTC)
        self.state["cycles"] = int(self.state.get("cycles", 0)) + 1
        self.state["cycles_started"] = int(self.state.get("cycles_started", 0)) + 1
        self.state["cycle_started_at"] = moment.isoformat()
        self._heartbeat_stage("CYCLE_START")
        summary = {
            "scan_status": None,
            "scan_ingested": 0,
            "top10": None,
            "outcomes_written": 0,
            "due_work_items": 0,
            "memory_updates": 0,
            "pattern_profile": {},
            "retrieval_versions": 0,
            "lifecycle": {},
            "errors": [],
        }
        self._heartbeat_stage("SCAN_INGEST")
        try:
            scan = await self._ingest_scan_source(batch=self.scan_batch)
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
        self._heartbeat_stage("OUTCOME_MATURATION")
        try:
            matured = await outcome_maturer.mature_due(
                self._session_factory, self.client, now=moment, max_work_items=self.outcome_batch
            )
            summary["outcomes_written"] = int(matured.get("written", 0))
            summary["due_work_items"] = int(matured.get("due_work_items", 0))
        except Exception as exc:
            summary["errors"].append(f"outcomes:{type(exc).__name__}")
        self._heartbeat_stage("LIFECYCLE_REVIEW")
        try:
            summary["lifecycle"] = await self._ingest_trading_lifecycle(batch=self.review_batch)
            summary["review_maturity"] = await self._mature_due_reviews(limit=self.review_batch)
        except Exception as exc:
            summary["errors"].append(f"lifecycle:{type(exc).__name__}")
        self._heartbeat_stage("MEMORY_UPDATE")
        try:
            summary["memory_updates"] = await self._update_memory(limit=self.memory_batch)
        except Exception as exc:
            summary["errors"].append(f"memory:{type(exc).__name__}")
        self._heartbeat_stage("PATTERN_PROFILE")
        try:
            summary["pattern_profile"] = await self._apply_reviewed_patterns(
                limit=self.review_batch
            )
        except Exception as exc:
            summary["errors"].append(f"pattern_profile:{type(exc).__name__}")
        self._heartbeat_stage("RETRIEVAL_REFRESH")
        try:
            async with self._session_factory() as session:
                summary["retrieval_versions"] = int(
                    await session.scalar(select(func.count()).select_from(GrowthMemoryVersionORM))
                    or 0
                )
            self.metrics["retrieval_versions"] = summary["retrieval_versions"]
        except Exception as exc:
            summary["errors"].append(f"retrieval_refresh:{type(exc).__name__}")
        self.metrics["top10_frozen"] = int(self.metrics.get("top10_frozen", 0)) + (
            1 if summary["top10"] == "FROZEN" else 0
        )
        self.metrics["outcomes_written"] = (
            int(self.metrics.get("outcomes_written", 0)) + summary["outcomes_written"]
        )
        self.metrics["due_work_items"] = (
            int(self.metrics.get("due_work_items", 0)) + summary["due_work_items"]
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
        # A cycle that finishes with recorded errors is still a completed
        # (degraded) cycle; cycles_completed is never incremented mid-cycle.
        self.state["cycles_completed"] = int(self.state.get("cycles_completed", 0)) + 1
        self._save(state=state, last_error=";".join(summary["errors"]) or None)
        self._heartbeat_stage("CYCLE_COMPLETE")
        return summary
