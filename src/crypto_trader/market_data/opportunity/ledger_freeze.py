# Completed-day Top10 freeze from the immutable opportunity ledger (LEARNING_ONLY).
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from crypto_trader.persistence.models import (
    DailyOpportunityTop10ORM,
    ScanSnapshotORM,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
LEDGER_SOURCE = "OPPORTUNITY_LEDGER"


def latest_completed_trading_day(now: datetime | None = None) -> str:
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (moment.astimezone(SHANGHAI) - timedelta(days=1)).date().isoformat()


async def freeze_completed_day(
    session_factory, trading_day: str, *, max_rank: int = 10, frozen_at: datetime | None = None
) -> dict:
    """First freeze wins; reruns are idempotent and never use hindsight."""
    async with session_factory() as session:
        existing = (
            (
                await session.execute(
                    select(DailyOpportunityTop10ORM)
                    .where(DailyOpportunityTop10ORM.trading_day == trading_day)
                    .order_by(DailyOpportunityTop10ORM.rank)
                )
            )
            .scalars()
            .all()
        )
        if existing:
            return {
                "status": "ALREADY_FROZEN",
                "trading_day": trading_day,
                "count": len(existing),
                "observation_ids": [row.observation_id for row in existing],
            }
        observations = (
            (
                await session.execute(
                    select(ScanSnapshotORM)
                    .where(ScanSnapshotORM.candidate.is_(True))
                    .where(ScanSnapshotORM.trading_day == trading_day)
                    .order_by(
                        ScanSnapshotORM.scanner_score.desc(),
                        ScanSnapshotORM.captured_at.asc(),
                        ScanSnapshotORM.snapshot_id.asc(),
                    )
                    .limit(max_rank)
                )
            )
            .scalars()
            .all()
        )
        now = frozen_at or datetime.now(UTC)
        for rank, observation in enumerate(observations, start=1):
            session.add(
                DailyOpportunityTop10ORM(
                    trading_day=trading_day,
                    rank=rank,
                    observation_id=observation.snapshot_id,
                    snapshot_hash=observation.snapshot_hash,
                    snapshot_version=observation.snapshot_version or "scan-snapshot-v1",
                    symbol=observation.symbol,
                    score=float(observation.scanner_score or 0.0),
                    candidate_source=observation.selection_reason or LEDGER_SOURCE,
                    evidence_package_json={
                        "snapshot_id": observation.snapshot_id,
                        "snapshot_hash": observation.snapshot_hash,
                        "snapshot_version": observation.snapshot_version,
                        "captured_at": observation.captured_at.isoformat(),
                        "selection_reason": observation.selection_reason,
                        "features": observation.features_json,
                    },
                    frozen_at=now,
                )
            )
        await session.commit()
        return {
            "status": "FROZEN",
            "trading_day": trading_day,
            "count": len(observations),
            "observation_ids": [row.snapshot_id for row in observations],
            "ranks": list(range(1, len(observations) + 1)),
        }
