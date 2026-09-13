"""Durable MarketSelection store (§12).

Selection records are research-attention lineage: they prove WHICH markets the
ChiefTrader chose to research and WHY, and they never carry direction. Hidden
chain-of-thought is never stored — only the bounded public fields.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from crypto_trader.market_data.opportunity.selection import (
    ST_NO_RESEARCH,
    ST_SUCCESS,
    MarketSelectionRecord,
)
from crypto_trader.persistence.models import MarketSelectionORM


class MarketSelectionStore:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory
        self._cache: dict[str, MarketSelectionRecord] = {}
        self._recent: list[MarketSelectionRecord] = []

    # ------------------------------------------------------------------ write
    async def save(self, record: MarketSelectionRecord) -> MarketSelectionRecord:
        orm = MarketSelectionORM(
            selection_id=record.selection_id,
            scan_id=record.scan_id,
            provider=record.provider,
            model=record.model,
            prompt_version=record.prompt_version,
            requested_at=record.requested_at,
            completed_at=record.completed_at,
            candidate_set_ref=record.candidate_set_ref,
            directory_query_refs_json=list(record.directory_query_refs),
            selected_symbols_json=[dict(s) for s in record.selected_symbols],
            selection_source=record.selection_source,
            selection_state=record.selection_state or "",
            status=record.status,
            error_code=record.error_code,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            latency_ms=record.latency_ms,
            snapshot_age_seconds=record.snapshot_age_seconds,
            exploration_rounds=record.exploration_rounds,
            directory_query_json=dict(record.directory_query),
        )
        async with self.session_factory() as session:
            session.add(orm)
            await session.commit()
        self._remember(record)
        return record

    def _remember(self, record: MarketSelectionRecord) -> None:
        self._cache[record.scan_id] = record
        self._recent.append(record)
        if len(self._recent) > 50:
            del self._recent[:-50]
        while len(self._cache) > 50:
            oldest = next(iter(self._cache))
            if oldest == record.scan_id and len(self._cache) > 1:
                keys = list(self._cache)
                oldest = keys[1] if keys[0] == record.scan_id else keys[0]
            self._cache.pop(oldest, None)

    # ------------------------------------------------------------------- read
    def cached_for_scan(self, scan_id: str) -> MarketSelectionRecord | None:
        """In-process fast path used by the duplicate-selection guard."""
        return self._cache.get(scan_id)

    def recent(self, limit: int = 10) -> list[MarketSelectionRecord]:
        return list(self._recent[-limit:])[::-1]

    def latest(self) -> MarketSelectionRecord | None:
        return self._recent[-1] if self._recent else None

    async def load_for_scan(self, scan_id: str) -> MarketSelectionRecord | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(MarketSelectionORM)
                .where(MarketSelectionORM.scan_id == scan_id)
                .order_by(MarketSelectionORM.requested_at.desc())
            )
        if row is None:
            return None
        return self._to_record(row)

    async def load_latest(self) -> MarketSelectionRecord | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(MarketSelectionORM).order_by(MarketSelectionORM.requested_at.desc())
            )
        if row is None:
            return None
        return self._to_record(row)

    async def load_recent(self, limit: int = 10) -> list[MarketSelectionRecord]:
        async with self.session_factory() as session:
            rows = (
                await session.scalars(
                    select(MarketSelectionORM)
                    .order_by(MarketSelectionORM.requested_at.desc())
                    .limit(limit)
                )
            ).all()
        return [self._to_record(row) for row in rows]

    async def restore_duplicate_guard(self) -> int:
        """Rehydrate the in-process duplicate guard after a restart."""
        records = await self.load_recent(limit=25)
        for record in reversed(records):
            self._remember(record)
        return len(records)

    @staticmethod
    def _to_record(row: MarketSelectionORM) -> MarketSelectionRecord:
        return MarketSelectionRecord(
            selection_id=row.selection_id,
            scan_id=row.scan_id or "none",
            status=row.status,
            selection_state=row.selection_state or "",
            provider=row.provider,
            model=row.model,
            prompt_version=row.prompt_version,
            requested_at=_aware(row.requested_at),
            completed_at=_aware(row.completed_at) if row.completed_at else None,
            candidate_set_ref=row.candidate_set_ref,
            directory_query_refs=list(row.directory_query_refs_json or []),
            selected_symbols=[dict(s) for s in (row.selected_symbols_json or [])],
            selection_source=row.selection_source or "DEEPSEEK_SELECTION",
            error_code=row.error_code,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            latency_ms=row.latency_ms,
            snapshot_age_seconds=row.snapshot_age_seconds,
            exploration_rounds=int(getattr(row, "exploration_rounds", 0) or 0),
            directory_query=dict(getattr(row, "directory_query_json", None) or {}),
        )

    def is_successful_pair(self, scan_id: str) -> bool:
        record = self._cache.get(scan_id)
        return bool(record and record.status in (ST_SUCCESS, ST_NO_RESEARCH))


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    return value if value.tzinfo else value.replace(tzinfo=UTC)
