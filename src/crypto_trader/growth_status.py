# Read-only Growth status assembly (LEARNING_ONLY; no mutations).
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select

from crypto_trader.persistence.models import (
    AICoinProfileORM,
    AICompressedExperienceORM,
    AIMarketPatternORM,
    DailyOpportunityTop10ORM,
    GrowthEventReviewORM,
    GrowthMemorySpeedORM,
    OpportunityOutcomeMaturationORM,
    ScanSnapshotORM,
)

LLM_ADVISORY = "DISABLED_PENDING_CANONICAL_FLASH_MERGE"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


async def growth_status(session_factory, growth_dir) -> dict:
    directory = Path(growth_dir)
    heartbeat = _load(directory / "growth_heartbeat.json")
    state = _load(directory / "growth_state.json")
    async with session_factory() as session:
        ledger = await session.scalar(select(func.count()).select_from(ScanSnapshotORM)) or 0
        top10 = (
            await session.scalar(select(func.count()).select_from(DailyOpportunityTop10ORM)) or 0
        )
        mature = (
            await session.scalar(
                select(func.count())
                .select_from(OpportunityOutcomeMaturationORM)
                .where(OpportunityOutcomeMaturationORM.maturation_status == "MATURE_VALID")
            )
            or 0
        )
        pending = (
            await session.scalar(
                select(func.count())
                .select_from(OpportunityOutcomeMaturationORM)
                .where(
                    OpportunityOutcomeMaturationORM.maturation_status.in_(("UNKNOWN", "IMMATURE"))
                )
            )
            or 0
        )
        inconclusive = (
            await session.scalar(
                select(func.count())
                .select_from(OpportunityOutcomeMaturationORM)
                .where(OpportunityOutcomeMaturationORM.maturation_status.like("INCONCLUSIVE%"))
            )
            or 0
        )
        reviews_pending = (
            await session.scalar(
                select(func.count())
                .select_from(GrowthEventReviewORM)
                .where(GrowthEventReviewORM.status == "PENDING")
            )
            or 0
        )
        reviews_mature = (
            await session.scalar(
                select(func.count())
                .select_from(GrowthEventReviewORM)
                .where(GrowthEventReviewORM.status == "MATURE")
            )
            or 0
        )
        reviews_inconclusive = (
            await session.scalar(
                select(func.count())
                .select_from(GrowthEventReviewORM)
                .where(GrowthEventReviewORM.status == "INCONCLUSIVE")
            )
            or 0
        )
        fast = (
            await session.scalar(
                select(func.count())
                .select_from(GrowthMemorySpeedORM)
                .where(GrowthMemorySpeedORM.speed == "FAST_EXPERIENCE")
            )
            or 0
        )
        pattern = (
            await session.scalar(
                select(func.count())
                .select_from(GrowthMemorySpeedORM)
                .where(GrowthMemorySpeedORM.speed == "PATTERN")
            )
            or 0
        )
        validated = (
            await session.scalar(
                select(func.count())
                .select_from(GrowthMemorySpeedORM)
                .where(GrowthMemorySpeedORM.speed == "VALIDATED_KNOWLEDGE")
            )
            or 0
        )
        regime_patterns = (
            await session.scalar(select(func.count()).select_from(AIMarketPatternORM)) or 0
        )
        profiles = await session.scalar(select(func.count()).select_from(AICoinProfileORM)) or 0
        compressed = (
            await session.scalar(select(func.count()).select_from(AICompressedExperienceORM)) or 0
        )
    metrics = dict(state.get("metrics", heartbeat.get("metrics", {})))
    return {
        "service": {
            "state": heartbeat.get("state", state.get("state", "UNKNOWN")),
            "pid": heartbeat.get("pid"),
            "runtime_sha": heartbeat.get("runtime_sha", state.get("runtime_sha")),
            "stage": heartbeat.get("stage"),
            "cycles_started": heartbeat.get("cycles_started", state.get("cycles_started", 0)),
            "cycles_completed": heartbeat.get("cycles_completed", state.get("cycles_completed", 0)),
            "last_progress_at": heartbeat.get("last_progress_at"),
            "last_error": heartbeat.get("last_error", state.get("last_error")),
        },
        "configuration": {
            "scan_batch": heartbeat.get("effective_scan_batch"),
            "outcome_batch": heartbeat.get("effective_outcome_batch"),
            "memory_batch": heartbeat.get("effective_memory_batch"),
            "review_batch": heartbeat.get("effective_review_batch"),
        },
        "sources": {
            "scan_source": heartbeat.get("scan_source_path"),
            "source_ok": heartbeat.get("scan_source_ok"),
            "cursor": heartbeat.get("source_cursor", state.get("last_scan_source_id", 0)),
            "max_id": metrics.get("source_max_id"),
            "lag_rows": metrics.get("source_lag_rows"),
            "trading_source": state.get("trading_source_db"),
            "trading_source_active": bool(state.get("trading_source_active", False)),
        },
        "ledger": {"rows": int(ledger), "today": metrics.get("ledger_today")},
        "top10": {"count": int(top10), "latest_completed_day": state.get("latest_completed_day")},
        "outcomes": {
            "valid": int(mature),
            "pending": int(pending),
            "inconclusive": int(inconclusive),
            "by_horizon": metrics.get("outcomes_by_horizon", {}),
        },
        "reviews": {
            "pending": int(reviews_pending),
            "mature": int(reviews_mature),
            "inconclusive": int(reviews_inconclusive),
            "by_type": metrics.get("reviews_by_type", {}),
        },
        "memory": {
            "fast": int(fast),
            "pattern": int(pattern),
            "validated": int(validated),
            "quality_rejected": int(metrics.get("memory_rows_rejected_quality", 0)),
            "nondirectional_skipped": int(metrics.get("nondirectional_opportunities_skipped", 0)),
        },
        "knowledge": {
            "regime_patterns": int(regime_patterns),
            "generalized": 0,
            "validated": int(validated),
            "sample_tiers": metrics.get("sample_tiers", {}),
        },
        "profiles": {"count": int(profiles)},
        "compressed": {"candidate": int(compressed), "validated": 0},
        "retrieval": metrics.get(
            "retrieval", {"queries": 0, "hit_rate": 0.0, "zero_hit_rate": 0.0, "mean_score": 0.0}
        ),
        "cache": metrics.get(
            "cache", {"hits": 0, "misses": 0, "invalidations": 0, "hit_rate": 0.0}
        ),
        "authority": "LEARNING_ONLY",
        "llm_advisory": LLM_ADVISORY,
        "is_order": False,
        "can_modify_core": False,
    }
