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

from sqlalchemy import exists, select

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


class SettlementRecoveryStalled(Exception):
    """A recovery pass completed but unfinished settlements remain.

    Returning normally here would let the caller report success while the
    accounting is still incomplete, so this must raise. Bounded work per pass is
    fine; making no progress at all is a blocker, not a state to be tolerated.
    """


class SettlementStateContradiction(Exception):
    """A marker claims COMPLETE but the factual lifecycle disagrees.

    COMPLETE is not a higher truth than the ledger. If the marker says COMPLETE
    and the ledger posting is missing, the settlement state is corrupt and MUST
    fail closed rather than be skipped as already-settled. Nothing is guessed or
    rebuilt.
    """


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
    """Fail closed on a NON-PREFIX settlement history.

    Legal (settled first, unfinished after):

        SETTLED SETTLED SETTLED PENDING PENDING

    Illegal (an unfinished fill followed by a settled one):

        PENDING SETTLED

    The illegal shape means the newer fill was settled against a position state
    that includes a fill whose own accounting was never proven, so its
    quantity_before / average_entry_price / realized_pnl are unreconstructable.
    A newer fill may be unfinished; an OLDER one may not be skipped over.

    Note the direction: the first UNSETTLED fill is remembered per symbol, and a
    later SETTLED fill for that symbol is the contradiction. An earlier version
    tracked the first settled fill instead, which rejected the legal shape and
    accepted the illegal one.
    """
    rows = (
        await session.execute(
            select(FillORM.fill_id, FillORM.symbol, FillORM.timestamp).order_by(
                FillORM.symbol, FillORM.timestamp, FillORM.fill_id
            )
        )
    ).all()
    first_unsettled: dict[str, str] = {}
    for fill_id, symbol, _ts in rows:
        has_ledger = await ledger_transaction_for_fill(session, fill_id) is not None
        if not has_ledger:
            first_unsettled.setdefault(symbol, fill_id)
            continue
        if symbol in first_unsettled:
            raise SettlementHistoryContradiction(
                f"non-prefix settlement history for {symbol}: "
                f"{fill_id} is settled but the older {first_unsettled[symbol]} is not"
            )


async def assert_complete_settlements_consistent(session) -> None:
    """A COMPLETE marker must not contradict the factual lifecycle.

    COMPLETE asserts: the ledger is posted, the projection converged, the plan
    converged, and - when the plan CLOSED - its episode was materialised. If any
    of those is missing the state is corrupt and MUST fail closed rather than be
    skipped as already-settled. Nothing is guessed or rebuilt: inventing the
    missing row would hide exactly the contradiction this check exists to expose.

    This is a GLOBAL scan and must run before the pending-FILL scan, because
    ``pending_settlements`` deliberately excludes COMPLETE rows - without this,
    a bad COMPLETE would be skipped forever.
    """
    from crypto_trader.persistence.models import (
        OrderORM,
        TradeEpisodeORM,
        TradePlanORM,
    )

    rows = (
        await session.execute(
            select(FillSettlementORM).where(FillSettlementORM.state == STATE_COMPLETE)
        )
    ).scalars().all()
    for marker in rows:
        txn = await ledger_transaction_for_fill(session, marker.fill_id)
        if txn is None:
            raise SettlementStateContradiction(
                f"{marker.fill_id} is marked COMPLETE but has no ledger transaction"
            )
        if (
            marker.ledger_transaction_id
            and txn.transaction_id != marker.ledger_transaction_id
        ):
            raise SettlementStateContradiction(
                f"{marker.fill_id} COMPLETE references {marker.ledger_transaction_id} "
                f"but the factual transaction is {txn.transaction_id}"
            )

        # ---- closed-lifecycle half of the invariant
        fill = (
            await session.execute(select(FillORM).where(FillORM.fill_id == marker.fill_id))
        ).scalar_one_or_none()
        if fill is None:
            continue
        order = (
            await session.execute(
                select(OrderORM).where(OrderORM.internal_order_id == fill.order_id)
            )
        ).scalar_one_or_none()
        if order is None:
            continue
        trade_plan_id = str((order.metadata_json or {}).get("trade_plan_id") or "")
        if not trade_plan_id:
            continue
        plan = (
            await session.execute(
                select(TradePlanORM).where(TradePlanORM.trade_plan_id == trade_plan_id)
            )
        ).scalar_one_or_none()
        if plan is None or plan.state != "CLOSED":
            continue
        episodes = (
            await session.execute(
                select(TradeEpisodeORM).where(
                    TradeEpisodeORM.trade_plan_id == trade_plan_id
                )
            )
        ).scalars().all()
        if len(episodes) != 1:
            raise SettlementStateContradiction(
                f"{marker.fill_id} is marked COMPLETE and plan {trade_plan_id} is "
                f"CLOSED but has {len(episodes)} TradeEpisode(s); exactly one is "
                "required"
            )


async def pending_settlements(session, *, limit: int = DEFAULT_BATCH_SIZE):
    """The OLDEST unfinished settlements, at most ``limit`` of them.

    Queries incomplete settlements directly instead of taking the first N fills
    and filtering in Python: the earlier shape truncated the fill history first,
    so once the oldest 200 fills were COMPLETE it returned nothing and recovery
    stopped early while unfinished fills remained.

    Two independent sources, merged chronologically:
      * fills whose marker says they are not COMPLETE - an explicit durable
        statement of incompleteness that no ledger state can contradict;
      * fills with NO marker whose ledger posting is genuinely absent, because a
        missing marker is not proof of completion.
    A fill with no marker AND a ledger posting is treated as settled history; a
    fill marked COMPLETE is settled even if a posting is somehow missing, because
    the marker is the authority on settlement completeness.
    """
    marked_rows = (
        await session.execute(
            select(FillORM)
            .where(
                FillORM.fill_id.in_(
                    select(FillSettlementORM.fill_id).where(
                        FillSettlementORM.state != STATE_COMPLETE
                    )
                )
            )
            .order_by(FillORM.timestamp.asc(), FillORM.fill_id.asc())
            .limit(limit)
        )
    ).scalars().all()

    unmarked_rows = (
        await session.execute(
            select(FillORM)
            .where(
                ~exists().where(FillSettlementORM.fill_id == FillORM.fill_id),
                ~exists().where(LedgerTransactionORM.fill_id == FillORM.fill_id),
            )
            .order_by(FillORM.timestamp.asc(), FillORM.fill_id.asc())
            .limit(limit)
        )
    ).scalars().all()

    merged = {f.fill_id: f for f in marked_rows}
    for f in unmarked_rows:
        merged.setdefault(f.fill_id, f)
    ordered = sorted(merged.values(), key=lambda f: (f.timestamp, f.fill_id))
    return ordered[:limit]


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
