"""Build and persist one factual episode after a canonical position is fully closed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.domain.money import D
from crypto_trader.persistence.models import (
    FillORM,
    LLMDecisionORM,
    OrderORM,
    PositionProjectionORM,
    TradeEpisodeORM,
    TradePlanORM,
)


@dataclass(frozen=True)
class FactualTradeEpisode:
    episode_id: str
    trade_plan_id: str
    symbol: str
    direction: str
    entry_decision_id: str
    exit_decision_id: str | None
    position_decision_ids: list[str]
    risk_decision_ids: list[str]
    order_ids: list[str]
    fill_ids: list[str]
    entry_price: Decimal
    exit_price: Decimal
    opened_quantity: Decimal
    closed_quantity: Decimal
    leverage: Decimal
    fees: Decimal
    funding_pnl: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    holding_time_seconds: float
    entry_market_regime: str
    terminal_reason: str
    opened_at: datetime
    closed_at: datetime


class TradeEpisodeStore:
    """Canonical episode truth store; never creates episodes from incomplete lifecycles."""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def build_for_closed_plan(self, trade_plan_id: str) -> FactualTradeEpisode | None:
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(TradeEpisodeORM).where(
                        TradeEpisodeORM.trade_plan_id == trade_plan_id
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return _to_domain(existing)

            plan = await session.get(TradePlanORM, trade_plan_id)
            if (
                plan is None
                or plan.state != "CLOSED"
                or plan.opened_at is None
                or plan.closed_at is None
                or plan.order_id is None
                or plan.exit_decision_id is None
            ):
                return None

            projected = (
                await session.execute(
                    select(PositionProjectionORM).where(
                        PositionProjectionORM.symbol == plan.symbol
                    )
                )
            ).scalar_one_or_none()
            if projected is not None and projected.quantity != 0:
                return None

            orders = (
                await session.execute(
                    select(OrderORM)
                    .where(OrderORM.symbol == plan.symbol)
                    .order_by(OrderORM.created_at, OrderORM.internal_order_id)
                )
            ).scalars().all()
            lifecycle_orders = [
                order
                for order in orders
                if order.internal_order_id == plan.order_id
                or (order.metadata_json or {}).get("trade_plan_id") == plan.trade_plan_id
            ]
            entry_orders = [
                order for order in lifecycle_orders if order.internal_order_id == plan.order_id
            ]
            close_orders = [
                order
                for order in lifecycle_orders
                if order.internal_order_id != plan.order_id
                and (order.metadata_json or {}).get("reduce_only") is True
            ]
            if len(entry_orders) != 1 or not close_orders:
                return None
            if not any(
                (order.metadata_json or {}).get("decision_id") == plan.exit_decision_id
                for order in close_orders
            ):
                return None

            order_ids = [order.internal_order_id for order in lifecycle_orders]
            risk_decision_ids = list(
                dict.fromkeys(
                    str(risk_id)
                    for order in lifecycle_orders
                    if (risk_id := (order.metadata_json or {}).get("risk_decision_id"))
                )
            )
            if not risk_decision_ids or risk_decision_ids[0] != plan.risk_decision_id:
                return None
            fills = (
                await session.execute(
                    select(FillORM)
                    .where(FillORM.order_id.in_(order_ids))
                    .order_by(FillORM.timestamp, FillORM.id)
                )
            ).scalars().all()
            entry_fills = [fill for fill in fills if fill.order_id == plan.order_id]
            close_ids = {order.internal_order_id for order in close_orders}
            close_fills = [fill for fill in fills if fill.order_id in close_ids]
            if not entry_fills or not close_fills:
                return None

            opened_quantity = sum((fill.quantity for fill in entry_fills), Decimal("0"))
            closed_quantity = sum((fill.quantity for fill in close_fills), Decimal("0"))
            if opened_quantity <= 0 or closed_quantity != opened_quantity:
                return None

            entry_price = _weighted_price(entry_fills, opened_quantity)
            exit_price = _weighted_price(close_fills, closed_quantity)
            entry_order = entry_orders[0]
            metadata = entry_order.metadata_json or {}
            instrument_type = str(metadata.get("instrument_type") or "SPOT")
            if instrument_type not in {"SPOT", "LINEAR_PERP"}:
                return None
            contract_size = D(metadata.get("contract_size", "1"))
            multiplier = D(metadata.get("contract_multiplier", "1"))
            pnl_factor = opened_quantity * contract_size * multiplier
            price_delta = exit_price - entry_price
            gross_pnl = price_delta * pnl_factor * (1 if plan.direction == "LONG" else -1)
            fees = sum((fill.fee for fill in fills), Decimal("0"))
            funding_pnl = Decimal("0")
            net_pnl = gross_pnl - fees + funding_pnl

            decisions = (
                await session.execute(
                    select(LLMDecisionORM)
                    .where(LLMDecisionORM.original_trade_plan_id == plan.trade_plan_id)
                    .order_by(LLMDecisionORM.created_at)
                )
            ).scalars().all()
            entry_decision = await session.get(LLMDecisionORM, plan.decision_id)
            if entry_decision is None:
                return None

            opened_at = _as_utc(plan.opened_at)
            closed_at = _as_utc(plan.closed_at)
            row = TradeEpisodeORM(
                episode_id=f"episode_{plan.trade_plan_id}",
                trade_plan_id=plan.trade_plan_id,
                symbol=plan.symbol,
                direction=plan.direction,
                entry_decision_id=plan.decision_id,
                exit_decision_id=plan.exit_decision_id,
                position_decision_ids_json=[decision.decision_id for decision in decisions],
                risk_decision_ids_json=risk_decision_ids,
                order_ids_json=order_ids,
                fill_ids_json=[fill.fill_id for fill in fills],
                entry_price=entry_price,
                exit_price=exit_price,
                opened_quantity=opened_quantity,
                closed_quantity=closed_quantity,
                leverage=D(metadata.get("approved_leverage") or plan.requested_leverage or "1"),
                fees=fees,
                funding_pnl=funding_pnl,
                gross_pnl=gross_pnl,
                net_pnl=net_pnl,
                holding_time_seconds=max(0.0, (closed_at - opened_at).total_seconds()),
                entry_market_regime=entry_decision.market_regime,
                terminal_reason=plan.terminal_reason or "POSITION_CLOSED",
                factual=True,
                review_status="PENDING",
                opened_at=opened_at,
                closed_at=closed_at,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            await session.commit()
            return _to_domain(row)

    async def load_closed_on(
        self,
        date: str,
        *,
        limit: int = 1000,
        timezone: tzinfo = UTC,
    ) -> list[FactualTradeEpisode]:
        """Return factual episodes closed in [start, next_day) in timezone.

        SQL date filtering is applied before the page limit so >1000 rows on
        other dates cannot crowd out the requested review day.
        """
        parsed = datetime.strptime(date, "%Y-%m-%d").date()
        start = datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone)
        end = start + timedelta(days=1)
        start_utc = start.astimezone(UTC)
        end_utc = end.astimezone(UTC)
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(TradeEpisodeORM)
                    .where(
                        TradeEpisodeORM.factual.is_(True),
                        TradeEpisodeORM.closed_at >= start_utc,
                        TradeEpisodeORM.closed_at < end_utc,
                    )
                    .order_by(TradeEpisodeORM.closed_at.desc())
                    .limit(max(1, min(limit, 5000)))
                )
            ).scalars().all()
            return [_to_domain(row) for row in rows]



    async def load_all_closed_on(
        self,
        date: str,
        *,
        timezone: tzinfo = UTC,
        page_size: int = 1000,
    ) -> list[FactualTradeEpisode]:
        """Return every factual episode closed in the full UTC day.

        Keyset pagination avoids the old silent 1000-row truncation.
        """
        parsed = datetime.strptime(date, "%Y-%m-%d").date()
        start = datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone)
        end = start + timedelta(days=1)
        start_utc = start.astimezone(UTC)
        end_utc = end.astimezone(UTC)
        cursor_time: datetime | None = None
        cursor_id: str | None = None
        out: list[FactualTradeEpisode] = []
        while True:
            async with self.session_factory() as session:
                query = select(TradeEpisodeORM).where(
                    TradeEpisodeORM.factual.is_(True),
                    TradeEpisodeORM.closed_at >= start_utc,
                    TradeEpisodeORM.closed_at < end_utc,
                )
                if cursor_time is not None and cursor_id is not None:
                    from sqlalchemy import tuple_
                    query = query.where(
                        tuple_(TradeEpisodeORM.closed_at, TradeEpisodeORM.episode_id)
                        > (cursor_time, cursor_id)
                    )
                rows = (
                    await session.execute(
                        query.order_by(
                            TradeEpisodeORM.closed_at.asc(),
                            TradeEpisodeORM.episode_id.asc(),
                        ).limit(max(1, min(page_size, 5000)))
                    )
                ).scalars().all()
            if not rows:
                break
            out.extend(_to_domain(row) for row in rows)
            last = rows[-1]
            cursor_time = last.closed_at
            cursor_id = last.episode_id
            if len(rows) < page_size:
                break
        return out



    async def earliest_factual_closed_date(self) -> str | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(TradeEpisodeORM)
                    .where(TradeEpisodeORM.factual.is_(True))
                    .order_by(TradeEpisodeORM.closed_at.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        return row.closed_at.date().isoformat() if row is not None else None

    async def mark_reviewed(self, episode_ids: list[str]) -> None:
        if not episode_ids:
            return
        chunk_size = 500
        async with self.session_factory() as session:
            rows = []
            for start in range(0, len(episode_ids), chunk_size):
                chunk = episode_ids[start : start + chunk_size]
                rows.extend(
                    (
                        await session.execute(
                            select(TradeEpisodeORM).where(
                                TradeEpisodeORM.episode_id.in_(chunk)
                            )
                        )
                    ).scalars().all()
                )
            for row in rows:
                row.review_status = "REVIEWED"
            await session.commit()


def _weighted_price(fills: list[FillORM], quantity: Decimal) -> Decimal:
    return sum((fill.price * fill.quantity for fill in fills), Decimal("0")) / quantity


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _to_domain(row: TradeEpisodeORM) -> FactualTradeEpisode:
    return FactualTradeEpisode(
        episode_id=row.episode_id,
        trade_plan_id=row.trade_plan_id,
        symbol=row.symbol,
        direction=row.direction,
        entry_decision_id=row.entry_decision_id,
        exit_decision_id=row.exit_decision_id,
        position_decision_ids=list(row.position_decision_ids_json or []),
        risk_decision_ids=list(row.risk_decision_ids_json or []),
        order_ids=list(row.order_ids_json or []),
        fill_ids=list(row.fill_ids_json or []),
        entry_price=row.entry_price,
        exit_price=row.exit_price,
        opened_quantity=row.opened_quantity,
        closed_quantity=row.closed_quantity,
        leverage=row.leverage,
        fees=row.fees,
        funding_pnl=row.funding_pnl,
        gross_pnl=row.gross_pnl,
        net_pnl=row.net_pnl,
        holding_time_seconds=row.holding_time_seconds,
        entry_market_regime=row.entry_market_regime,
        terminal_reason=row.terminal_reason,
        opened_at=_as_utc(row.opened_at),
        closed_at=_as_utc(row.closed_at),
    )
