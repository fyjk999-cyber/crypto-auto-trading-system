"""Portfolio read model. Account and Position are projections of the ledger."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.domain.enums import TradingMode
from crypto_trader.domain.models import Account, Balance, Position
from crypto_trader.domain.money import D
from crypto_trader.ledger.projections import rebuild_projections, replay_projections
from crypto_trader.persistence.models import (
    AccountProjectionORM,
    EquitySnapshotORM,
    LedgerTransactionORM,
    PositionProjectionORM,
)


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



    async def record_equity_drawdown(
        self,
        current_equity: Decimal,
        *,
        currency: str = "USDT",
        source: str = "LEDGER_PROJECTION",
    ) -> tuple[Decimal, Decimal, datetime, str]:
        """Persist a factual equity point and return canonical drawdown.

        Convention: drawdown <= 0, where drawdown = current_equity - peak_equity.
        Peak is durably retained across restarts.
        """
        as_of = datetime.now(UTC)
        async with self.session_factory() as session:
            latest = (
                await session.execute(
                    select(EquitySnapshotORM)
                    .order_by(EquitySnapshotORM.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            period_flow = Decimal("0")
            if latest is not None:
                flow_rows = (
                    await session.execute(
                        select(LedgerTransactionORM).where(
                            LedgerTransactionORM.created_at > latest.valuation_as_of,
                            LedgerTransactionORM.entry_type.in_(("DEPOSIT", "WITHDRAWAL")),
                        )
                    )
                ).scalars().all()
                for txn in flow_rows:
                    metadata = txn.metadata_json or {}
                    raw_amount = (
                        metadata.get("amount")
                        or metadata.get("quantity")
                        or metadata.get("total")
                        or "0"
                    )
                    amount = abs(D(raw_amount))
                    period_flow += amount if txn.entry_type == "DEPOSIT" else -amount
            cumulative_flow = (
                latest.cumulative_external_cash_flow + period_flow
                if latest is not None
                else Decimal("0")
            )
            cash_flow_adjusted = current_equity - cumulative_flow
            prior_peak = (
                latest.peak_adjusted_equity
                if latest is not None and latest.peak_adjusted_equity > 0
                else latest.peak_equity
                if latest is not None
                else cash_flow_adjusted
            )
            peak_adjusted = max(prior_peak, cash_flow_adjusted)
            drawdown = cash_flow_adjusted - peak_adjusted
            session.add(
                EquitySnapshotORM(
                    account_id="default",
                    currency=currency,
                    current_equity=current_equity,
                    raw_equity=current_equity,
                    external_cash_flow_adjustment=period_flow,
                    period_external_cash_flow=period_flow,
                    cumulative_external_cash_flow=cumulative_flow,
                    cash_flow_adjusted_equity=cash_flow_adjusted,
                    peak_equity=peak_adjusted,
                    peak_adjusted_equity=peak_adjusted,
                    drawdown=drawdown,
                    valuation_source=source,
                    valuation_status="HEALTHY",
                    valuation_as_of=as_of,
                )
            )
            await session.commit()
        return drawdown, peak_adjusted, as_of, source

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
                    instrument_type=row.instrument_type,
                    contract_size=row.contract_size,
                    contract_multiplier=row.contract_multiplier,
                    leverage=row.leverage,
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
                instrument_type=row.instrument_type,
                contract_size=row.contract_size,
                contract_multiplier=row.contract_multiplier,
                leverage=row.leverage,
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
