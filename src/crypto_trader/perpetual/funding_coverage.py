"""Durable factual coverage windows for funding settlement status."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from crypto_trader.domain.identifiers import new_id
from crypto_trader.persistence.models import FundingCoverageORM


@dataclass(frozen=True)
class FundingCoverage:
    instrument_id: str
    window_start: datetime
    window_end: datetime
    coverage_status: str
    pagination_complete: bool
    event_manifest_hash: str | None
    gaps: list[str]
    rule_version: str


class FundingCoverageService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def record(
        self,
        *,
        instrument_id: str,
        window_start: datetime,
        window_end: datetime,
        coverage_status: str,
        pagination_complete: bool,
        event_manifest_hash: str | None = None,
        gaps: list[str] | None = None,
        source: str = "OKX_PUBLIC",
        rule_version: str = "v1",
        fetched_at: datetime | None = None,
    ) -> FundingCoverage:
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(FundingCoverageORM).where(
                        FundingCoverageORM.instrument_id == instrument_id,
                        FundingCoverageORM.window_start == window_start,
                        FundingCoverageORM.window_end == window_end,
                        FundingCoverageORM.rule_version == rule_version,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                existing = FundingCoverageORM(
                    coverage_id=new_id("fcov"),
                    instrument_id=instrument_id,
                    window_start=window_start,
                    window_end=window_end,
                )
                session.add(existing)
            existing.source = source
            existing.fetched_at = fetched_at
            existing.pagination_complete = pagination_complete
            existing.event_manifest_hash = event_manifest_hash
            existing.gaps_json = gaps or []
            existing.coverage_status = coverage_status
            await session.commit()
            return FundingCoverage(
                instrument_id=instrument_id,
                window_start=window_start,
                window_end=window_end,
                coverage_status=coverage_status,
                pagination_complete=pagination_complete,
                event_manifest_hash=event_manifest_hash,
                gaps=list(gaps or []),
                rule_version=rule_version,
            )

    async def status_for(
        self, *, instrument_id: str, start: datetime, end: datetime
    ) -> str:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(FundingCoverageORM).where(
                        FundingCoverageORM.instrument_id == instrument_id,
                        FundingCoverageORM.window_start <= start,
                        FundingCoverageORM.window_end >= end,
                        FundingCoverageORM.pagination_complete.is_(True),
                    )
                )
            ).scalars().all()
        if not rows:
            return "UNKNOWN"
        if all(row.coverage_status == "KNOWN_ZERO" for row in rows):
            return "KNOWN_ZERO"
        if all(row.coverage_status in {"KNOWN_ZERO", "KNOWN_VALUE"} for row in rows):
            return "KNOWN_VALUE"
        return "UNKNOWN"
