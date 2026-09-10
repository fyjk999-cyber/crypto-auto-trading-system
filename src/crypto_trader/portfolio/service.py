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
from crypto_trader.valuation.domain import (
    VALUATION_QUALITY_HEALTHY,
    ValuationBatch,
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



    async def record_valuation_batch(
        self,
        *,
        valuation_id: str | None = None,
        account_id: str = "default",
        currency: str = "USDT",
        quality: str = VALUATION_QUALITY_HEALTHY,
        raw_mtm_equity: Decimal | None = None,
        fallback_equity: Decimal | None = None,
        source: str = "MARK_TO_MARKET_EQUITY",
        valuation_as_of: datetime | None = None,
        market_as_of: datetime | None = None,
        ledger_watermark: str | None = None,
        position_snapshot_ref: str | None = None,
        reason_codes: list[str] | None = None,
        missing_marks: list[str] | None = None,
        stale_marks: list[str] | None = None,
        components: list[dict] | None = None,
    ) -> ValuationBatch:
        """Persist the one canonical valuation batch for account/currency.

        The batch and its equity snapshot are written atomically. Peak and
        drawdown are updated only from HEALTHY batches; the first UNAVAILABLE
        batch can never seed a baseline.
        """
        as_of = valuation_as_of or datetime.now(UTC)
        healthy = quality == VALUATION_QUALITY_HEALTHY
        snapshot_equity = (
            raw_mtm_equity
            if raw_mtm_equity is not None
            else fallback_equity
            if fallback_equity is not None
            else Decimal("0")
        )
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
            flow_rows = (
                await session.execute(
                    select(LedgerTransactionORM).where(
                        LedgerTransactionORM.account_id == account_id,
                        LedgerTransactionORM.ownership_status == "VERIFIED",
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
            adjusted_equity = (
                snapshot_equity - cumulative_flow if healthy else None
            )
            prior_peak = (
                latest.peak_adjusted_equity
                if latest is not None and latest.peak_adjusted_equity is not None
                else None
            )
            if healthy:
                peak_adjusted = (
                    adjusted_equity
                    if prior_peak is None
                    else max(prior_peak, adjusted_equity)
                )
                drawdown = adjusted_equity - peak_adjusted
                drawdown_ratio = (
                    drawdown / peak_adjusted
                    if peak_adjusted is not None and peak_adjusted != 0
                    else None
                )
            else:
                peak_adjusted = prior_peak
                drawdown = None
                drawdown_ratio = None
            health = self.classify_equity_status(snapshot_equity)
            solvency = (
                {
                    "HEALTHY": "POSITIVE",
                    "ZERO_EQUITY": "ZERO_EQUITY",
                    "INSOLVENT": "INSOLVENT",
                }.get(health, "UNKNOWN")
                if healthy
                else None
            )
            valuation_id = valuation_id or new_id("val")
            session.add(
                ValuationBatchORM(
                    valuation_id=valuation_id,
                    account_id=account_id,
                    currency=currency,
                    valuation_as_of=as_of,
                    market_as_of=market_as_of,
                    ledger_watermark=ledger_watermark,
                    position_snapshot_ref=position_snapshot_ref,
                    raw_mtm_equity=raw_mtm_equity if healthy else None,
                    available_margin=(
                        account_row.available if account_row is not None else None
                    )
                    if healthy
                    else None,
                    adjusted_equity=adjusted_equity,
                    peak_adjusted_equity=peak_adjusted,
                    drawdown_amount=drawdown,
                    drawdown_ratio=drawdown_ratio,
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
                    current_equity=snapshot_equity,
                    raw_equity=(
                        raw_mtm_equity if raw_mtm_equity is not None else snapshot_equity
                    ),
                    external_cash_flow_adjustment=cumulative_flow,
                    period_external_cash_flow=cumulative_flow,
                    cumulative_external_cash_flow=cumulative_flow,
                    cash_flow_adjusted_equity=adjusted_equity,
                    peak_equity=peak_adjusted,
                    peak_adjusted_equity=peak_adjusted,
                    drawdown=drawdown,
                    # Valuation quality and solvency are independent facts.
                    valuation_status=quality,
                    valuation_source=source,
                    valuation_id=valuation_id,
                    valuation_as_of=as_of,
                )
            )
            await session.commit()
        return ValuationBatch(
            valuation_id=valuation_id,
            account_id=account_id,
            currency=currency,
            quality=quality,
            raw_mtm_equity=raw_mtm_equity if healthy else None,
            available_margin=(
                account_row.available if healthy and account_row is not None else None
            ),
            adjusted_equity=adjusted_equity,
            peak_adjusted_equity=peak_adjusted,
            drawdown_amount=drawdown,
            drawdown_ratio=drawdown_ratio,
            market_as_of=market_as_of,
            ledger_watermark=ledger_watermark,
            position_snapshot_ref=position_snapshot_ref,
            missing_marks=tuple(missing_marks or ()),
            stale_marks=tuple(stale_marks or ()),
            components=tuple(components or ()),
            solvency=solvency,
            reason_codes=tuple(reason_codes or ()),
            valuation_as_of=as_of,
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
        ledger_watermark: str | None = None,
        position_snapshot_ref: str | None = None,
    ) -> tuple[Decimal | None, Decimal | None, datetime, str]:
        """Backward-compatible wrapper returning canonical batch facts."""
        as_of = valuation_as_of or datetime.now(UTC)
        healthy = quality == VALUATION_QUALITY_HEALTHY
        batch = await self.record_valuation_batch(
            valuation_id=valuation_id,
            account_id=account_id,
            currency=currency,
            quality=quality,
            raw_mtm_equity=current_equity if healthy else None,
            fallback_equity=current_equity,
            source=source,
            valuation_as_of=as_of,
            market_as_of=None,
            ledger_watermark=ledger_watermark,
            position_snapshot_ref=position_snapshot_ref,
            reason_codes=reason_codes,
            missing_marks=missing_marks,
            stale_marks=stale_marks,
            components=components,
        )
        return batch.drawdown_amount, batch.peak_adjusted_equity, as_of, source

    @staticmethod
    def _batch_to_domain(row: ValuationBatchORM) -> ValuationBatch:
        return ValuationBatch(
            valuation_id=row.valuation_id,
            account_id=row.account_id,
            currency=row.currency,
            quality=row.quality,
            raw_mtm_equity=row.raw_mtm_equity,
            available_margin=row.available_margin,
            adjusted_equity=row.adjusted_equity,
            peak_adjusted_equity=row.peak_adjusted_equity,
            drawdown_amount=row.drawdown_amount,
            drawdown_ratio=row.drawdown_ratio,
            market_as_of=row.market_as_of,
            ledger_watermark=row.ledger_watermark,
            position_snapshot_ref=row.position_snapshot_ref,
            missing_marks=tuple(row.missing_marks_json or ()),
            stale_marks=tuple(row.stale_marks_json or ()),
            components=tuple(row.components_json or ()),
            solvency=row.solvency,
            reason_codes=tuple(row.reason_codes_json or ()),
            valuation_as_of=row.valuation_as_of,
        )

    async def get_valuation_batch(self, valuation_id: str) -> ValuationBatch | None:
        if not valuation_id:
            return None
        async with self.session_factory() as session:
            row = await session.get(ValuationBatchORM, valuation_id)
            return None if row is None else self._batch_to_domain(row)

    async def latest_valuation_batch(
        self, *, account_id: str = "default", currency: str = "USDT"
    ) -> ValuationBatch | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(ValuationBatchORM)
                    .where(
                        ValuationBatchORM.account_id == account_id,
                        ValuationBatchORM.currency == currency,
                    )
                    .order_by(
                        ValuationBatchORM.created_at.desc(),
                        ValuationBatchORM.valuation_id.desc(),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            return None if row is None else self._batch_to_domain(row)
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
