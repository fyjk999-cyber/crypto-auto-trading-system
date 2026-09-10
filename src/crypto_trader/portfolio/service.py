"""Portfolio read model. Account and Position are projections of the ledger."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.domain.enums import TradingMode
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import Account, Balance, Position
from crypto_trader.domain.money import D
from crypto_trader.ledger.projections import rebuild_projections, replay_projections
from crypto_trader.persistence.models import (
    AccountProjectionORM,
    EquitySnapshotORM,
    LedgerTransactionORM,
    PositionProjectionORM,
    ValuationBatchORM,
)


class PortfolioService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    @staticmethod
    def classify_equity_status(equity: Decimal) -> str:
        if equity > 0:
            return "HEALTHY"
        if equity == 0:
            return "ZERO_EQUITY"
        return "INSOLVENT"

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
        account_id: str = "default",
        currency: str = "USDT",
        source: str = "LEDGER_PROJECTION",
        valuation_as_of: datetime | None = None,
        valuation_id: str | None = None,
        quality: str = "HEALTHY",
        reason_codes: list[str] | None = None,
        missing_marks: list[str] | None = None,
        stale_marks: list[str] | None = None,
        components: list[dict] | None = None,
    ) -> tuple[Decimal, Decimal, datetime, str]:
        """Persist a factual equity point and return canonical drawdown.

        Convention: drawdown <= 0, where drawdown = current_equity - peak_equity.
        Peak is durably retained across restarts.
        """
        as_of = valuation_as_of or datetime.now(UTC)
        async with self.session_factory() as session:
            latest = (
                await session.execute(
                    select(EquitySnapshotORM)
                    .where(
                        EquitySnapshotORM.account_id == account_id,
                        EquitySnapshotORM.currency == currency,
                    )
                    .order_by(EquitySnapshotORM.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            # Cumulative economic external flow from unique transactions, not
            # individual double-entry postings. This is idempotent across
            # restarts/same-timestamp replays and does not depend on a cursor.
            flow_rows = (
                await session.execute(
                    select(LedgerTransactionORM).where(
                        LedgerTransactionORM.account_id == account_id,
                        LedgerTransactionORM.entry_type.in_(("DEPOSIT", "WITHDRAWAL")),
                    )
                )
            ).scalars().all()
            cumulative_flow = Decimal("0")
            for txn in flow_rows:
                metadata = txn.metadata_json or {}
                raw_amount = (
                    metadata.get("amount")
                    or metadata.get("quantity")
                    or metadata.get("total")
                    or "0"
                )
                row_currency = (
                    metadata.get("currency")
                    or metadata.get("settleCcy")
                    or metadata.get("quote_currency")
                    or currency
                )
                if row_currency != currency:
                    continue
                amount = abs(D(raw_amount))
                cumulative_flow += amount if txn.entry_type == "DEPOSIT" else -amount
            account_row = (
                await session.execute(
                    select(AccountProjectionORM).where(
                        AccountProjectionORM.account_id == account_id,
                        AccountProjectionORM.currency == currency,
                    )
                )
            ).scalar_one_or_none()
            prior_cumulative = (
                latest.cumulative_external_cash_flow if latest is not None else Decimal("0")
            )
            period_flow = cumulative_flow - prior_cumulative
            cash_flow_adjusted = current_equity - cumulative_flow
            prior_peak = (
                latest.peak_adjusted_equity
                if latest is not None and latest.peak_adjusted_equity > 0
                else latest.peak_equity
                if latest is not None
                else cash_flow_adjusted
            )
            if quality == "HEALTHY":
                peak_adjusted = max(prior_peak, cash_flow_adjusted)
            else:
                # Unavailable/incomplete marks must not create a new peak or
                # pollute historical drawdown performance.
                peak_adjusted = prior_peak
            drawdown = cash_flow_adjusted - peak_adjusted
            valuation_id = valuation_id or new_id("val")
            health = self.classify_equity_status(current_equity)
            solvency = (
                {
                    "HEALTHY": "POSITIVE",
                    "ZERO_EQUITY": "ZERO_EQUITY",
                    "INSOLVENT": "INSOLVENT",
                }.get(health, "UNKNOWN")
                if quality == "HEALTHY"
                else None
            )
            session.add(
                ValuationBatchORM(
                    valuation_id=valuation_id,
                    account_id=account_id,
                    currency=currency,
                    valuation_as_of=as_of,
                    ledger_watermark=None,
                    position_snapshot_ref=None,
                    raw_mtm_equity=current_equity if quality == "HEALTHY" else None,
                    available_margin=(
                        account_row.available if account_row is not None else None
                    )
                    if quality == "HEALTHY"
                    else None,
                    adjusted_equity=cash_flow_adjusted,
                    peak_adjusted_equity=peak_adjusted,
                    drawdown_amount=drawdown,
                    quality=quality,
                    reason_codes_json=reason_codes or [],
                    solvency=solvency,
                    missing_marks_json=missing_marks or [],
                    stale_marks_json=stale_marks or [],
                    components_json=components or [],
                )
            )
            session.add(
                EquitySnapshotORM(
                    account_id=account_id,
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
                    valuation_status=health,
                    valuation_id=valuation_id,
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
