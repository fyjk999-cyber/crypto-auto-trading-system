"""Durable factual coverage windows for funding settlement status."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.money import D
from crypto_trader.persistence.models import (
    FundingCoverageORM,
    FundingEventResolutionORM,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _same_instant(left: datetime, right: datetime) -> bool:
    return _utc(left) == _utc(right)


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
    # P3 audit split: what the exchange returned, what falls inside the
    # requested window, and whether a raw page proved the lower bound.
    fetched_count: int = 0
    window_event_count: int = 0
    boundary_proof: bool = False
    # Raw window events; persisted as events_json so completeness can be
    # proven event-by-event, not inferred from a single status.
    window_events: tuple[dict, ...] = ()


@dataclass(frozen=True)
class FundingEventResolution:
    account_id: str
    instrument_id: str
    settlement_timestamp: datetime
    currency: str
    status: str
    quantity: Decimal | None
    mark_price: Decimal | None
    funding_rate: Decimal | None
    trade_plan_id: str | None
    ledger_transaction_id: str | None
    reason: str | None

    @property
    def complete(self) -> bool:
        return self.status in {"SETTLED", "NO_OP"}


SETTLED_FUNDING_RESOLUTIONS = {"SETTLED", "NO_OP"}


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
        fetched_count: int = 0,
        window_event_count: int = 0,
        boundary_proof: bool = False,
        events: list[dict] | None = None,
    ) -> FundingCoverage:
        window_start = _utc(window_start)
        window_end = _utc(window_end)
        async with self.session_factory() as session:
            # SQLite stores naive UTC strings; compare instants in Python so a
            # repeated supervisor run updates the same coverage row instead of
            # hitting the unique window constraint.
            candidates = (
                await session.execute(
                    select(FundingCoverageORM).where(
                        FundingCoverageORM.instrument_id == instrument_id,
                        FundingCoverageORM.rule_version == rule_version,
                    )
                )
            ).scalars().all()
            existing = next(
                (
                    row
                    for row in candidates
                    if _same_instant(row.window_start, window_start)
                    and _same_instant(row.window_end, window_end)
                ),
                None,
            )
            if existing is None:
                existing = FundingCoverageORM(
                    coverage_id=new_id("fcov"),
                    instrument_id=instrument_id,
                    window_start=window_start,
                    window_end=window_end,
                )
                session.add(existing)
            existing.source = source
            existing.fetched_at = fetched_at or datetime.now(UTC)
            existing.pagination_complete = pagination_complete
            existing.event_manifest_hash = event_manifest_hash
            existing.gaps_json = gaps or []
            existing.coverage_status = coverage_status
            existing.fetched_count = fetched_count
            existing.window_event_count = window_event_count
            existing.boundary_proof = boundary_proof
            existing.events_json = list(events or [])
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
                fetched_count=fetched_count,
                window_event_count=window_event_count,
                boundary_proof=boundary_proof,
                window_events=tuple(events or ()),
            )

    async def coverage_for(
        self, *, instrument_id: str, start: datetime, end: datetime
    ) -> FundingCoverage | None:
        """Best durable proof window covering [start, end), or None."""
        start = _utc(start)
        end = _utc(end)
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(FundingCoverageORM).where(
                        FundingCoverageORM.instrument_id == instrument_id,
                    )
                )
            ).scalars().all()
        covering = [
            row
            for row in rows
            if row.pagination_complete
            and row.boundary_proof
            and _utc(row.window_start) <= start
            and _utc(row.window_end) >= end
        ]
        if not covering:
            return None
        # Prefer the tightest covering window so event filters stay precise.
        row = min(
            covering,
            key=lambda item: (
                _utc(item.window_end) - _utc(item.window_start),
                item.coverage_id,
            ),
        )
        events = list(row.events_json or [])
        return FundingCoverage(
            instrument_id=row.instrument_id,
            window_start=_utc(row.window_start),
            window_end=_utc(row.window_end),
            coverage_status=row.coverage_status,
            pagination_complete=row.pagination_complete,
            event_manifest_hash=row.event_manifest_hash,
            gaps=list(row.gaps_json or []),
            rule_version=row.rule_version,
            fetched_count=row.fetched_count,
            window_event_count=row.window_event_count,
            boundary_proof=row.boundary_proof,
            window_events=tuple(events),
        )

    async def record_event_resolution(
        self,
        *,
        account_id: str,
        instrument_id: str,
        settlement_timestamp: datetime,
        currency: str = "USDT",
        status: str,
        quantity: Decimal | None = None,
        mark_price: Decimal | None = None,
        funding_rate: Decimal | None = None,
        trade_plan_id: str | None = None,
        ledger_transaction_id: str | None = None,
        reason: str | None = None,
    ) -> FundingEventResolution:
        settlement_timestamp = _utc(settlement_timestamp)
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(FundingEventResolutionORM).where(
                        FundingEventResolutionORM.account_id == account_id,
                        FundingEventResolutionORM.instrument_id == instrument_id,
                    )
                )
            ).scalars().all()
            existing = next(
                (
                    row
                    for row in rows
                    if _same_instant(row.settlement_timestamp, settlement_timestamp)
                ),
                None,
            )
            if existing is None:
                existing = FundingEventResolutionORM(
                    resolution_id=new_id("fres"),
                    account_id=account_id,
                    instrument_id=instrument_id,
                    currency=currency,
                    settlement_timestamp=settlement_timestamp,
                    status=status,
                )
                session.add(existing)
            elif existing.status in SETTLED_FUNDING_RESOLUTIONS and status not in (
                SETTLED_FUNDING_RESOLUTIONS
            ):
                # Never downgrade a proven settlement/no-op on retry.
                return FundingEventResolution(
                    account_id=existing.account_id,
                    instrument_id=existing.instrument_id,
                    settlement_timestamp=_utc(existing.settlement_timestamp),
                    currency=existing.currency,
                    status=existing.status,
                    quantity=existing.quantity,
                    mark_price=existing.mark_price,
                    funding_rate=existing.funding_rate,
                    trade_plan_id=existing.trade_plan_id,
                    ledger_transaction_id=existing.ledger_transaction_id,
                    reason=existing.reason,
                )
            existing.currency = currency
            existing.status = status
            existing.quantity = quantity
            existing.mark_price = mark_price
            existing.funding_rate = funding_rate
            existing.trade_plan_id = trade_plan_id
            existing.ledger_transaction_id = ledger_transaction_id
            existing.reason = reason
            existing.updated_at = datetime.now(UTC)
            await session.commit()
            return FundingEventResolution(
                account_id=account_id,
                instrument_id=instrument_id,
                settlement_timestamp=settlement_timestamp,
                currency=currency,
                status=status,
                quantity=quantity,
                mark_price=mark_price,
                funding_rate=funding_rate,
                trade_plan_id=trade_plan_id,
                ledger_transaction_id=ledger_transaction_id,
                reason=reason,
            )

    async def event_resolutions(
        self,
        *,
        account_id: str,
        instrument_id: str,
        currency: str = "USDT",
    ) -> list[FundingEventResolution]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(FundingEventResolutionORM).where(
                        FundingEventResolutionORM.account_id == account_id,
                        FundingEventResolutionORM.instrument_id == instrument_id,
                        FundingEventResolutionORM.currency == currency,
                    )
                )
            ).scalars().all()
        return [
            FundingEventResolution(
                account_id=row.account_id,
                instrument_id=row.instrument_id,
                settlement_timestamp=_utc(row.settlement_timestamp),
                currency=row.currency,
                status=row.status,
                quantity=row.quantity,
                mark_price=row.mark_price,
                funding_rate=row.funding_rate,
                trade_plan_id=row.trade_plan_id,
                ledger_transaction_id=row.ledger_transaction_id,
                reason=row.reason,
            )
            for row in rows
        ]

    async def retryable_unresolved(self) -> list[FundingEventResolution]:
        """Durable recovery queue; SETTLED/NO_OP and permanent states excluded."""
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(FundingEventResolutionORM)
                    .where(
                        FundingEventResolutionORM.status.in_(
                            ("UNPROVEN", "MARK_UNAVAILABLE")
                        )
                    )
                    .order_by(
                        FundingEventResolutionORM.updated_at,
                        FundingEventResolutionORM.settlement_timestamp,
                    )
                )
            ).scalars().all()
        return [
            FundingEventResolution(
                account_id=row.account_id,
                instrument_id=row.instrument_id,
                settlement_timestamp=_utc(row.settlement_timestamp),
                currency=row.currency,
                status=row.status,
                quantity=row.quantity,
                mark_price=row.mark_price,
                funding_rate=row.funding_rate,
                trade_plan_id=row.trade_plan_id,
                ledger_transaction_id=row.ledger_transaction_id,
                reason=row.reason,
            )
            for row in rows
        ]

    async def status_for(
        self, *, instrument_id: str, start: datetime, end: datetime
    ) -> str:
        coverage = await self.coverage_for(
            instrument_id=instrument_id, start=start, end=end
        )
        return coverage.coverage_status if coverage is not None else "UNKNOWN"


class FundingHistoryIngestor:
    """Fetch factual funding history pages and persist coverage proof."""

    def __init__(self, coverage_service: FundingCoverageService) -> None:
        self.coverage_service = coverage_service

    async def ingest(
        self,
        adapter,
        *,
        instrument_id: str,
        window_start: datetime,
        window_end: datetime,
        max_pages: int = 20,
        include_events: bool = False,
    ) -> FundingCoverage:
        start_ms = int(window_start.timestamp() * 1000)
        end_ms = int(window_end.timestamp() * 1000)
        # Distinguish raw fetched history from the requested window and the
        # lower-bound proof, exactly as required by P3.
        fetched_history: list[dict] = []
        window_events: list[dict] = []
        complete = False
        boundary_proof = False
        cursor_ms = end_ms
        missing_rates = False
        malformed = False
        for _ in range(max_pages):
            # OKX `after` returns records older than the cursor; `before`
            # returns newer records and cannot page backwards safely.
            raw_page = list(
                await adapter.get_funding_rate_history(
                    instrument_id, after=str(cursor_ms), limit=100
                )
                or []
            )
            fetched_history.extend(raw_page)
            if not raw_page:
                # No older records at all. The lower bound is only considered
                # covered once the cursor has reached it; otherwise an empty
                # truncated page cannot be promoted to factual zero.
                complete = cursor_ms <= start_ms
                boundary_proof = complete
                break
            try:
                raw_times = [int(row.get("fundingTime", -1)) for row in raw_page]
            except (TypeError, ValueError):
                malformed = True
                break
            if any(timestamp < 0 for timestamp in raw_times):
                malformed = True
                break
            oldest_raw_ms = min(raw_times)
            page_window = [
                row
                for row in raw_page
                if start_ms <= int(row.get("fundingTime", -1)) < end_ms
            ]
            for row in page_window:
                if not row.get("realizedRate"):
                    missing_rates = True
            window_events.extend(page_window)
            # Boundary proof is evaluated on the RAW page BEFORE window
            # filtering. A page whose oldest record is at/below window_start
            # proves pagination crossed the lower bound even when that record
            # itself lies outside the requested window.
            if oldest_raw_ms <= start_ms:
                boundary_proof = True
                complete = True
                break
            cursor_ms = oldest_raw_ms
        else:
            # max_pages exhausted before reaching the lower bound.
            complete = False

        window_events.sort(key=lambda row: int(row["fundingTime"]))
        gaps = self._detect_gaps(window_events)
        manifest = hashlib.sha256(
            json.dumps(fetched_history, sort_keys=True, default=str).encode()
        ).hexdigest()
        if not complete or not boundary_proof or gaps or missing_rates or malformed:
            status = "UNKNOWN"
        elif window_events and any(
            D(row["realizedRate"]) != 0 for row in window_events
        ):
            status = "KNOWN_VALUE"
        else:
            status = "KNOWN_ZERO"
        coverage = await self.coverage_service.record(
            instrument_id=instrument_id,
            window_start=window_start,
            window_end=window_end,
            coverage_status=status,
            pagination_complete=complete,
            event_manifest_hash=f"sha256:{manifest}",
            gaps=gaps,
            fetched_count=len(fetched_history),
            window_event_count=len(window_events),
            boundary_proof=boundary_proof,
            events=window_events,
        )
        if include_events:
            return replace(coverage, window_events=tuple(window_events))
        return coverage

    @staticmethod
    def _detect_gaps(rows: list[dict]) -> list[str]:
        if len(rows) < 3:
            return []
        times = [int(row["fundingTime"]) for row in rows]
        deltas = [b - a for a, b in zip(times, times[1:], strict=False)]
        positive = sorted(delta for delta in deltas if delta > 0)
        if not positive:
            return []
        baseline = positive[0]
        gaps: list[str] = []
        for previous, current in zip(times, times[1:], strict=False):
            if current - previous > baseline * 3 // 2:
                gaps.append(
                    datetime.fromtimestamp(current / 1000, tz=UTC).isoformat()
                )
        return gaps
