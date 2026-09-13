"""Durable FILL SETTLEMENT: ``FillORM persisted`` != ``fill fully settled``.

The gap this closes
-------------------
``apply_fill`` committed the FillORM and then invoked the settlement callback.
If that callback failed, the engine's event loop logged a health flag and DROPPED
the event - and redelivering the same fill event short-circuited on "fill already
exists", so nothing could ever complete it. Result: a durable fill whose ledger
posting, portfolio projection and TradePlan promotion were all missing, with no
path to recovery. Measured with deterministic fault injection:

    FILL_ROW_COUNT = 1, ledger transactions for that fill = 0,
    PLAN_STATE = APPROVED, POSITION_QTY = None, and a replay changed nothing.

The invariant now
-----------------
A fill is settled only when the LEDGER is factual, the PORTFOLIO projection is
current and the PLAN lifecycle has converged. A durable marker records that
progress so recovery is possible after an event failure, a crash, a replay or a
restart - without duplicating ledger, fee, position or episodes.

Idempotency comes from the existing fill-id ledger guard plus the marker itself,
so replaying the same fill can only ever COMPLETE an interrupted settlement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from crypto_trader.persistence.models import (
    FillORM,
    FillSettlementORM,
    LedgerTransactionORM,
    OrderORM,
)

STATE_PENDING = "PENDING"
STATE_ACCOUNTED = "ACCOUNTED"
STATE_COMPLETE = "COMPLETE"

#: Bounded per-pass work; callers paginate rather than silently truncating.
DEFAULT_BATCH_SIZE = 200


@dataclass(frozen=True, slots=True)
class SettlementOutcome:
    fill_id: str
    state: str
    newly_accounted: bool
    recovered: bool
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "fill_id": self.fill_id,
            "state": self.state,
            "newly_accounted": self.newly_accounted,
            "recovered": self.recovered,
            "reason": self.reason,
        }


class SettlementPredecessorPending(Exception):
    """An older same-symbol fill is not COMPLETE yet.

    A later fill's position_quantity_before / average_entry_price / realized_pnl
    can depend on the earlier one, so settling out of order would corrupt the
    projection. Callers must stop and retry after the predecessor completes.
    """


class SettlementHistoryContradiction(Exception):
    """Non-prefix settlement history: an older fill lacks its ledger posting
    while a newer same-symbol fill already has one. The historical pre-fill state
    cannot be reconstructed, so this MUST fail closed rather than guess."""


async def ensure_fill_settlement_row(session, fill: FillORM) -> FillSettlementORM:
    """Get or create the durable marker for a factual fill."""
    row = (
        await session.execute(
            select(FillSettlementORM).where(FillSettlementORM.fill_id == fill.fill_id)
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    now = datetime.now(UTC)
    row = FillSettlementORM(
        fill_id=fill.fill_id,
        order_id=fill.order_id,
        symbol=fill.symbol,
        state=STATE_PENDING,
        attempt_count=0,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    return row


async def ledger_transaction_for_fill(session, fill_id: str):
    return (
        await session.execute(
            select(LedgerTransactionORM).where(LedgerTransactionORM.fill_id == fill_id)
        )
    ).scalar_one_or_none()


async def assert_prefix_settlement_history(session) -> None:
    """Fail closed on non-prefix history (older unsettled, newer settled).

    Scans per symbol in timestamp order: once a fill WITH a ledger posting has
    been seen, any later fill WITHOUT one is fine (it is merely unfinished), but
    a fill WITHOUT a posting appearing BEFORE one WITH a posting means the
    history is non-prefix and unreconstructable.
    """
    rows = (
        await session.execute(
            select(FillORM.fill_id, FillORM.symbol, FillORM.timestamp).order_by(
                FillORM.symbol, FillORM.timestamp, FillORM.fill_id
            )
        )
    ).all()
    settled_seen: dict[str, str] = {}
    for fill_id, symbol, _ts in rows:
        txn = await ledger_transaction_for_fill(session, fill_id)
        if txn is None:
            if symbol in settled_seen:
                raise SettlementHistoryContradiction(
                    f"non-prefix settlement history for {symbol}: "
                    f"{fill_id} unsettled but {settled_seen[symbol]} already settled"
                )
        else:
            settled_seen.setdefault(symbol, fill_id)


async def pending_settlements(session, *, limit: int = DEFAULT_BATCH_SIZE):
    """Durable fills whose settlement is not COMPLETE, oldest first.

    Historical fills with no marker are included: a missing marker is not proof
    of completion.
    """
    marker_rows = (
        await session.execute(
            select(FillSettlementORM.fill_id).where(FillSettlementORM.state != STATE_COMPLETE)
        )
    ).scalars().all()
    marked = set(marker_rows)
    fill_rows = (
        await session.execute(
            select(FillORM).order_by(FillORM.timestamp, FillORM.fill_id).limit(limit)
        )
    ).scalars().all()
    out = []
    for fill in fill_rows:
        if fill.fill_id in marked:
            out.append(fill)
            continue
        # No marker: include only when the ledger posting is genuinely absent.
        if await ledger_transaction_for_fill(session, fill.fill_id) is None:
            out.append(fill)
    return out[:limit]


async def ensure_fill_settled(
    session,
    *,
    fill_id: str,
    settle_ledger,
    settle_downstream,
) -> SettlementOutcome:
    """Drive ONE fill to COMPLETE, idempotently.

    ``settle_ledger(fill, order)`` must post the canonical ledger transaction via
    the existing fill-id idempotent path and return its id (or None if it already
    existed). ``settle_downstream(fill, order, ledger_transaction_id)`` refreshes
    the portfolio projection and converges the TradePlan.

    Never duplicates: the ledger guard is keyed on fill_id, the marker is unique
    per fill_id, and an already-COMPLETE settlement returns immediately.
    """
    fill = (
        await session.execute(select(FillORM).where(FillORM.fill_id == fill_id))
    ).scalar_one_or_none()
    if fill is None:
        return SettlementOutcome(fill_id, STATE_PENDING, False, False, "FILL_NOT_FOUND")

    order = (
        await session.execute(
            select(OrderORM).where(OrderORM.internal_order_id == fill.order_id)
        )
    ).scalar_one_or_none()

    marker = await ensure_fill_settlement_row(session, fill)
    if marker.state == STATE_COMPLETE:
        return SettlementOutcome(fill_id, STATE_COMPLETE, False, False, "ALREADY_COMPLETE")

    marker.attempt_count = (marker.attempt_count or 0) + 1
    marker.updated_at = datetime.now(UTC)

    # ------------------------------------------------ predecessor ordering
    older = (
        await session.execute(
            select(FillORM.fill_id)
            .where(FillORM.symbol == fill.symbol)
            .where(FillORM.timestamp < fill.timestamp)
            .order_by(FillORM.timestamp.desc())
            .limit(5)
        )
    ).scalars().all()
    for older_id in older:
        older_marker = (
            await session.execute(
                select(FillSettlementORM).where(FillSettlementORM.fill_id == older_id)
            )
        ).scalar_one_or_none()
        if older_marker is not None and older_marker.state != STATE_COMPLETE:
            raise SettlementPredecessorPending(
                f"{fill_id} cannot settle before {older_id} on {fill.symbol}"
            )

    # --------------------------------------------------------- ledger phase
    existing_txn = await ledger_transaction_for_fill(session, fill_id)
    newly_accounted = False
    txn_id = existing_txn.transaction_id if existing_txn is not None else None
    if existing_txn is None:
        txn_id = await settle_ledger(fill, order)
        newly_accounted = True
        # Re-read: a concurrent idempotent path may have won the race and created
        # it, in which case the guard means we still end with exactly one.
        existing_txn = await ledger_transaction_for_fill(session, fill_id)
        if existing_txn is not None:
            txn_id = existing_txn.transaction_id
            newly_accounted = newly_accounted and txn_id == txn_id

    marker.state = STATE_ACCOUNTED
    marker.ledger_transaction_id = txn_id
    marker.updated_at = datetime.now(UTC)
    await session.flush()

    # ----------------------------------------------------- downstream phase
    await settle_downstream(fill, order, txn_id)

    marker.state = STATE_COMPLETE
    marker.completed_at = datetime.now(UTC)
    marker.updated_at = marker.completed_at
    marker.last_error_type = None
    marker.last_error_message = None
    await session.flush()

    return SettlementOutcome(
        fill_id=fill_id,
        state=STATE_COMPLETE,
        newly_accounted=newly_accounted,
        recovered=existing_txn is not None and not newly_accounted,
    )


async def record_settlement_failure(session, *, fill_id: str, error: Exception) -> None:
    """Persist WHY a settlement failed so recovery has a durable trace."""
    marker = (
        await session.execute(
            select(FillSettlementORM).where(FillSettlementORM.fill_id == fill_id)
        )
    ).scalar_one_or_none()
    if marker is None:
        return
    marker.last_error_type = type(error).__name__
    marker.last_error_message = str(error)[:500]
    marker.updated_at = datetime.now(UTC)
    await session.flush()
