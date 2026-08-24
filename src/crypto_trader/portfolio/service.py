"""Portfolio read model. Account and Position are projections of the ledger."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.domain.enums import TradingMode
from crypto_trader.domain.models import Account, Balance, Position
from crypto_trader.ledger.projections import rebuild_projections, replay_projections
from crypto_trader.persistence.models import AccountProjectionORM, PositionProjectionORM


class PortfolioService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def refresh(self, initial_balances: dict[str, Decimal] | None = None) -> None:
        async with self.session_factory() as session:
            await rebuild_projections(session, initial_balances=initial_balances)

    async def get_account(self, mode: TradingMode = TradingMode.PAPER) -> Account:
        async with self.session_factory() as session:
            snap = await replay_projections(session)
            return Account(
                account_id=snap.account_id,
                mode=mode,
                balances={
                    currency: Balance(
                        currency=currency,
                        total=row["total"],
                        available=row["available"],
                        frozen=row["frozen"],
                    )
                    for currency, row in snap.balances.items()
                },
                equity=snap.equity,
                updated_at=datetime.now(UTC),
            )

    async def get_positions(self) -> dict[str, Position]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(PositionProjectionORM))).scalars().all()
            return {
                row.symbol: Position(
                    symbol=row.symbol,
                    base_asset=row.base_asset,
                    quote_asset=row.quote_asset,
                    quantity=row.quantity,
                    avg_entry_price=row.avg_entry_price,
                    cost_basis=row.cost_basis,
                    realized_pnl=row.realized_pnl,
                    updated_at=row.updated_at,
                )
                for row in rows
            }

    async def get_position(self, symbol: str) -> Position | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(PositionProjectionORM).where(PositionProjectionORM.symbol == symbol)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return Position(
                symbol=row.symbol,
                base_asset=row.base_asset,
                quote_asset=row.quote_asset,
                quantity=row.quantity,
                avg_entry_price=row.avg_entry_price,
                cost_basis=row.cost_basis,
                realized_pnl=row.realized_pnl,
                updated_at=row.updated_at,
            )

    async def get_balance(self, currency: str) -> Decimal:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(AccountProjectionORM).where(
                        AccountProjectionORM.currency == currency,
                        AccountProjectionORM.account_id == "default",
                    )
                )
            ).scalar_one_or_none()
            return row.total if row is not None else Decimal("0")
