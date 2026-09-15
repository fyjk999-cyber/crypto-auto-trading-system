"""Append-only execution evidence store (Phase E0).

Design constraints taken directly from the phase's own safety rules:

* **Never break trading.** Every write is best-effort: a persistence failure is
  recorded as OBSERVABILITY_DEGRADED and swallowed, because research telemetry
  must not be able to block position protection.
* **Never fabricate.** A value that could not be obtained is stored as UNKNOWN
  (or NULL), never as a plausible-looking number.
* **Never overwrite history.** Rows are inserted, or upserted by event identity
  on the (evidence_id, offset_seconds) unique key. Historical market facts are
  immutable.
* **Never read on a decision path.** Nothing here is imported by sizing, Risk,
  the Sizer, the ChiefTrader or the order manager, so recording evidence cannot
  move the behavioural trading diff off zero.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from crypto_trader.execution_observability.orderbook_metrics import (
    OrderbookMetrics,
    compute_orderbook_metrics,
)
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.persistence.models import (
    EntryExecutionEvidenceORM,
    EntryOrderbookSampleORM,
    MarketSnapshotORM,
    OrderORM,
)

logger = logging.getLogger(__name__)

#: Sampling schedule for a resting ENTRY order (§15). The whole entry TTL is 60s,
#: so the schedule stays inside the order's own lifetime - it never implies that
#: the order should outlive its TTL.
SAMPLE_OFFSETS_SECONDS: tuple[int, ...] = (0, 1, 2, 5, 15, 30, 60)

QUALITY_OK = "OK"
QUALITY_UNKNOWN = "UNKNOWN"
QUALITY_DEGRADED = "OBSERVABILITY_DEGRADED"

#: Marker for "we could not measure this". Distinct from a real value.
NOT_MEASURED = "NOT_MEASURED"


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _dec(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _s(value: object) -> str | None:
    return None if value is None else str(value)


def ratio(numerator: object, denominator: object) -> str | None:
    """numerator/denominator as an exact decimal string, or None when undefined.

    Returns None - not zero - when the denominator is missing or zero, because
    "we cannot express a realization ratio" is not the same fact as "nothing was
    realised".
    """
    num, den = _dec(numerator), _dec(denominator)
    if num is None or den is None or den == 0:
        return None
    return str(num / den)


@dataclass(slots=True)
class EntryIntentEvidence:
    """What the system WANTED versus what Risk allowed (§13)."""

    symbol: str
    side: str | None = None
    chief_direction: str | None = None
    decision_id: str | None = None
    trade_plan_id: str | None = None
    order_id: str | None = None
    run_id: str | None = None
    target_quantity: object | None = None
    target_notional: object | None = None
    risk_approved_max_quantity: object | None = None
    risk_approved_max_notional: object | None = None
    requested_order_quantity: object | None = None
    requested_order_notional: object | None = None
    actual_opened_quantity: object | None = None
    actual_opened_notional: object | None = None
    leverage: object | None = None
    limit_price: object | None = None
    reason_codes: list[str] | None = None


class EntryEvidenceStore:
    """Persists ENTRY execution evidence. Best-effort, append-only."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory
        #: Set when a write failed. Read-only diagnostic surface.
        self.last_error: str | None = None
        self.degraded_writes = 0

    # -- entry intent ------------------------------------------------------
    async def record_entry_intent(
        self,
        intent: EntryIntentEvidence,
        *,
        book: OrderBook | None = None,
        consume_side: str | None = None,
        now: datetime | None = None,
    ) -> str | None:
        """Persist one ENTRY intent plus its pre-submit book snapshot.

        Returns the evidence_id, or None when the write degraded. Never raises:
        the caller is on the trading path and must not fail because telemetry did.
        """
        moment = now or datetime.now(UTC)
        evidence_id = _new_id("eev")
        metrics: OrderbookMetrics | None = None
        snapshot_id: int | None = None

        if book is not None:
            try:
                metrics = compute_orderbook_metrics(book, consume_side=consume_side)
                snapshot_id = await self._persist_snapshot(book, metrics, moment)
            except Exception as exc:  # noqa: BLE001
                self._degrade("orderbook_metrics", exc)

        try:
            async with self._session_factory() as session:
                row = EntryExecutionEvidenceORM(
                    evidence_id=evidence_id,
                    decision_id=intent.decision_id,
                    trade_plan_id=intent.trade_plan_id,
                    order_id=intent.order_id,
                    run_id=intent.run_id,
                    symbol=intent.symbol,
                    side=intent.side,
                    chief_direction=intent.chief_direction,
                    target_quantity=_s(intent.target_quantity),
                    target_notional=_s(intent.target_notional),
                    risk_approved_max_quantity=_s(intent.risk_approved_max_quantity),
                    risk_approved_max_notional=_s(intent.risk_approved_max_notional),
                    requested_order_quantity=_s(intent.requested_order_quantity),
                    requested_order_notional=_s(intent.requested_order_notional),
                    actual_opened_quantity=_s(intent.actual_opened_quantity),
                    actual_opened_notional=_s(intent.actual_opened_notional),
                    exposure_realization_ratio=ratio(
                        intent.actual_opened_notional, intent.target_notional
                    ),
                    leverage=_s(intent.leverage),
                    limit_price=_s(intent.limit_price),
                    pre_submit_snapshot_id=snapshot_id,
                    pre_submit_metrics_json=metrics.as_dict() if metrics else None,
                    executable_side=metrics.executable_side if metrics else None,
                    executable_depth_l1=metrics.executable_depth_l1 if metrics else None,
                    executable_depth_l5=metrics.executable_depth_l5 if metrics else None,
                    executable_depth_l10=metrics.executable_depth_l10 if metrics else None,
                    quality=metrics.quality if metrics else QUALITY_UNKNOWN,
                    reason_codes_json=list(intent.reason_codes or []),
                    created_at=moment,
                )
                session.add(row)
                await session.commit()
            return evidence_id
        except Exception as exc:  # noqa: BLE001
            self._degrade("record_entry_intent", exc)
            return None

    # -- post-submit sampling ---------------------------------------------
    async def record_sample(
        self,
        *,
        evidence_id: str,
        symbol: str,
        offset_seconds: int,
        book: OrderBook | None = None,
        consume_side: str | None = None,
        our_limit_price: object | None = None,
        our_remaining_quantity: object | None = None,
        cumulative_fill_quantity: object | None = None,
        market_traded_volume: object | None = None,
        queue_ahead: object | None = None,
        queue_ahead_quality: str | None = None,
        source: str = "PAPER_SIMULATOR",
        source_timestamp: datetime | None = None,
        now: datetime | None = None,
    ) -> str | None:
        """Persist one scheduled post-submit observation.

        Idempotent on (evidence_id, offset_seconds): re-recording the same offset
        updates that sample instead of appending a duplicate.
        """
        moment = now or datetime.now(UTC)
        metrics: OrderbookMetrics | None = None
        if book is not None:
            try:
                metrics = compute_orderbook_metrics(book, consume_side=consume_side)
            except Exception as exc:  # noqa: BLE001
                self._degrade("sample_metrics", exc)

        payload = dict(
            symbol=symbol,
            offset_seconds=offset_seconds,
            observed_at=moment,
            source=source,
            source_timestamp=source_timestamp,
            quality=metrics.quality if metrics else QUALITY_UNKNOWN,
            best_bid=metrics.best_bid if metrics else None,
            best_ask=metrics.best_ask if metrics else None,
            mid=metrics.mid if metrics else None,
            spread_bps=metrics.spread_bps if metrics else None,
            bids_json=metrics.bids if metrics else None,
            asks_json=metrics.asks if metrics else None,
            bid_depth_l1=metrics.bid_depth_l1 if metrics else None,
            ask_depth_l1=metrics.ask_depth_l1 if metrics else None,
            bid_depth_l5=metrics.bid_depth_l5 if metrics else None,
            ask_depth_l5=metrics.ask_depth_l5 if metrics else None,
            bid_depth_l10=metrics.bid_depth_l10 if metrics else None,
            ask_depth_l10=metrics.ask_depth_l10 if metrics else None,
            microprice=metrics.microprice if metrics else None,
            orderbook_imbalance=metrics.orderbook_imbalance if metrics else None,
            executable_side=metrics.executable_side if metrics else None,
            executable_depth_l1=metrics.executable_depth_l1 if metrics else None,
            executable_depth_l5=metrics.executable_depth_l5 if metrics else None,
            executable_depth_l10=metrics.executable_depth_l10 if metrics else None,
            our_limit_price=_s(our_limit_price),
            our_remaining_quantity=_s(our_remaining_quantity),
            cumulative_fill_quantity=_s(cumulative_fill_quantity),
            market_traded_volume=_s(market_traded_volume),
            # Queue position is recorded as NOT_MEASURED unless a caller can
            # actually support the number - a fabricated queue priority would be
            # worse than no queue priority.
            queue_ahead=_s(queue_ahead) if queue_ahead is not None else NOT_MEASURED,
            queue_ahead_quality=queue_ahead_quality or (
                QUALITY_OK if queue_ahead is not None else NOT_MEASURED
            ),
        )

        try:
            async with self._session_factory() as session:
                existing = (
                    await session.execute(
                        select(EntryOrderbookSampleORM).where(
                            EntryOrderbookSampleORM.evidence_id == evidence_id,
                            EntryOrderbookSampleORM.offset_seconds == offset_seconds,
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    for key, value in payload.items():
                        setattr(existing, key, value)
                    await session.commit()
                    return existing.sample_id
                row = EntryOrderbookSampleORM(
                    sample_id=_new_id("eos"), evidence_id=evidence_id, **payload
                )
                session.add(row)
                await session.commit()
                return row.sample_id
        except IntegrityError:
            # A concurrent writer won the unique key; the evidence already
            # exists, which is the desired end state. Not a degradation.
            return None
        except Exception as exc:  # noqa: BLE001
            self._degrade("record_sample", exc)
            return None

    async def evidence_id_for_order(self, order_id: str) -> str | None:
        """The evidence row recorded for this order, or None when there is none.

        Read-only lookup. Returns None rather than raising so a caller sampling a
        post-submit observation cannot be broken by a missing evidence row.
        """
        if not order_id:
            return None
        try:
            async with self._session_factory() as session:
                row = (
                    await session.execute(
                        select(EntryExecutionEvidenceORM.evidence_id)
                        .where(EntryExecutionEvidenceORM.order_id == order_id)
                        .order_by(EntryExecutionEvidenceORM.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
            return str(row) if row else None
        except Exception as exc:  # noqa: BLE001
            self._degrade("evidence_id_for_order", exc)
            return None

    async def order_progress(self, order_id: str) -> dict:
        """Factual fill progress for one order. Read-only.

        Used to label each post-submit sample with what our own order was doing
        at that instant. Missing values stay None - a sample taken while progress
        cannot be read is not evidence that nothing filled.
        """
        out = {"order_price": None, "remaining_quantity": None,
               "cumulative_fill_quantity": None, "status": None}
        if not order_id:
            return out
        try:
            async with self._session_factory() as session:
                row = await session.get(OrderORM, order_id)
            if row is None:
                return out
            filled = _dec(getattr(row, "filled_quantity", None))
            total = _dec(getattr(row, "quantity", None))
            out["order_price"] = _s(getattr(row, "price", None))
            out["cumulative_fill_quantity"] = _s(filled)
            out["remaining_quantity"] = (
                _s(total - filled) if (total is not None and filled is not None) else None
            )
            out["status"] = _s(getattr(row, "status", None))
        except Exception as exc:  # noqa: BLE001
            self._degrade("order_progress", exc)
        return out

    # -- internals ---------------------------------------------------------
    async def _persist_snapshot(
        self, book: OrderBook, metrics: OrderbookMetrics, moment: datetime
    ) -> int | None:
        """Reuse the existing market_snapshots table rather than duplicating it."""
        sequence = getattr(book, "sequence", None)
        try:
            async with self._session_factory() as session:
                row = MarketSnapshotORM(
                    symbol=str(book.symbol),
                    # The table's uniqueness is (symbol, sequence). A venue
                    # sequence is used verbatim when present; otherwise a
                    # microsecond timestamp PLUS a random suffix keeps captures
                    # distinct - two snapshots inside the same microsecond would
                    # otherwise collide and one would be silently lost.
                    sequence=(
                        int(sequence)
                        if sequence is not None
                        else int(moment.timestamp() * 1_000_000)
                        + (uuid.uuid4().int % 1000)
                    ),
                    # The existing column is a String(8000), so levels are
                    # serialised; the computed metrics live in metrics_json.
                    bids_json=_json_levels(metrics.bids),
                    asks_json=_json_levels(metrics.asks),
                    status=str(getattr(book, "status", QUALITY_UNKNOWN)),
                    captured_at=moment,
                    exchange=str(getattr(book, "exchange", "UNKNOWN")),
                    metrics_json=metrics.as_dict(),
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return int(row.id)
        except IntegrityError as exc:
            # A collision here means the (symbol, sequence) identity was taken.
            # That loses evidence, so it is recorded as a degradation rather
            # than swallowed as if it were a benign duplicate.
            self._degrade("persist_snapshot_collision", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            self._degrade("persist_snapshot", exc)
            return None

    def _degrade(self, where: str, exc: Exception) -> None:
        self.degraded_writes += 1
        self.last_error = f"{where}: {type(exc).__name__}"
        # Warning, not exception: telemetry must never stop trading.
        logger.warning("%s degraded: %s", where, type(exc).__name__)


def _json_levels(levels: list[list[str]]) -> str:
    import json

    return json.dumps(levels)
