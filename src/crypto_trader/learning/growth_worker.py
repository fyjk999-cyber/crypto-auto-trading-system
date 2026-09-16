# Autonomous Growth worker orchestration (LEARNING_ONLY; restart-safe).
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from crypto_trader.learning.memory_speed_store import MemorySpeedStore
from crypto_trader.learning.memory_speeds import MemoryRecord, apply_observation
from crypto_trader.market_data.opportunity import ledger_freeze, outcome_maturer
from crypto_trader.persistence.models import OpportunityOutcomeMaturationORM

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

    def __init__(self, session_factory, base_dir, client, *, code_sha: str = "") -> None:
        self._session_factory = session_factory
        self.base_dir = Path(base_dir)
        self.client = client
        self.code_sha = code_sha
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
                "last_error": last_error,
                "metrics": self.metrics,
            },
        )

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
        store = MemorySpeedStore(self._session_factory)
        for row in rows:
            key = f"{row.symbol}|{row.horizon}|{row.outcome_version}"
            net = max(float(row.long_net_bps or 0.0), float(row.short_net_bps or 0.0))
            record = await store.load(key) or MemoryRecord(
                key=key, signature=f"{row.symbol}|{row.horizon}"
            )
            apply_observation(
                record,
                net_bps=net,
                regime=str(row.direction_source or "NONE"),
                win=net > 0,
                post_cost_bps=net,
                chronological_stable=True,
                contradiction=net < 0 and record.observations >= 100,
            )
            await store.save(record)
            cursor = max(cursor, int(row.id))
        self.state["last_memory_maturation_id"] = cursor
        return len(rows)

    async def run_once(self, *, now: datetime | None = None) -> dict:
        moment = now or datetime.now(UTC)
        self.state["cycles"] = int(self.state.get("cycles", 0)) + 1
        summary = {"top10": None, "outcomes_written": 0, "memory_updates": 0, "errors": []}
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
        self.metrics["errors"] = int(self.metrics.get("errors", 0)) + len(summary["errors"])
        state = "DEGRADED" if summary["errors"] else "ACCUMULATING"
        self._save(state=state, last_error=";".join(summary["errors"]) or None)
        return summary
