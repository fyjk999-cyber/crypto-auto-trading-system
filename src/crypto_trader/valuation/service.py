"""Canonical valuation computation and durable batch persistence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal

from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import Account, Instrument, Position
from crypto_trader.ledger.service import LedgerService
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.valuation.domain import (
    VALUATION_QUALITY_HEALTHY,
    VALUATION_QUALITY_UNAVAILABLE,
    ValuationBatch,
)

MARKET_PRICE_SOURCE = "ORDERBOOK_MID"


class ValuationService:
    def __init__(
        self,
        *,
        portfolio: PortfolioService,
        ledger: LedgerService,
    ) -> None:
        self.portfolio = portfolio
        self.ledger = ledger

    async def build(
        self,
        *,
        account: Account,
        positions: Mapping[str, Position],
        market_prices: Mapping[str, Decimal],
        instruments: Mapping[str, Instrument] | None = None,
        is_fresh: Callable[[str], bool] | None = None,
        market_as_of: datetime | None = None,
        currency: str = "USDT",
        reason_codes: list[str] | None = None,
    ) -> ValuationBatch:
        """Compute one immutable candidate batch without writing anything."""
        instruments = instruments or {}
        missing_marks: list[str] = []
        stale_marks: list[str] = []
        components: list[dict] = []
        raw_mtm_equity = Decimal(account.equity)
        for symbol, position in positions.items():
            if position.quantity == 0:
                continue
            mark = market_prices.get(symbol)
            if mark is None or mark <= 0:
                missing_marks.append(symbol)
                continue
            if is_fresh is not None and not is_fresh(symbol):
                stale_marks.append(symbol)
                continue
            instrument = instruments.get(symbol)
            contract_size = (
                instrument.contract_size if instrument is not None else position.contract_size
            )
            contract_multiplier = (
                instrument.contract_multiplier
                if instrument is not None
                else position.contract_multiplier
            )
            instrument_type = (
                instrument.instrument_type
                if instrument is not None
                else position.instrument_type
            )
            entry_price = position.avg_entry_price or Decimal("0")
            if instrument_type == "LINEAR_PERP":
                unrealized = (
                    (mark - entry_price)
                    * position.quantity
                    * Decimal(contract_size)
                    * Decimal(contract_multiplier)
                )
            else:
                unrealized = (mark - entry_price) * position.quantity
            raw_mtm_equity += unrealized
            components.append(
                {
                    "instrument_id": symbol,
                    "quantity": str(position.quantity),
                    "entry_price": str(entry_price),
                    "mark_price": str(mark),
                    "instrument_type": instrument_type,
                    "contract_size": str(contract_size),
                    "contract_multiplier": str(contract_multiplier),
                    "unrealized_pnl": str(unrealized),
                    "price_source": MARKET_PRICE_SOURCE,
                }
            )

        quality = (
            VALUATION_QUALITY_HEALTHY
            if not missing_marks and not stale_marks
            else VALUATION_QUALITY_UNAVAILABLE
        )
        if quality != VALUATION_QUALITY_HEALTHY:
            raw_mtm_equity = None
        ledger_watermark = await self.ledger.watermark(
            account_id=account.account_id, currency=currency
        )
        position_snapshot_ref = self.position_snapshot_ref(positions)
        reasons = list(reason_codes or [])
        if missing_marks:
            reasons.append("MISSING_MARKS")
        if stale_marks:
            reasons.append("STALE_MARKS")
        return ValuationBatch(
            valuation_id=new_id("val"),
            account_id=account.account_id,
            currency=currency,
            quality=quality,
            raw_mtm_equity=raw_mtm_equity,
            available_margin=None,
            market_as_of=market_as_of,
            ledger_watermark=ledger_watermark,
            position_snapshot_ref=position_snapshot_ref,
            missing_marks=tuple(missing_marks),
            stale_marks=tuple(stale_marks),
            components=tuple(components),
            reason_codes=tuple(reasons),
        )

    async def persist(
        self, batch: ValuationBatch, *, fallback_equity: Decimal | None = None
    ) -> ValuationBatch:
        """Atomically persist the batch (idempotent by valuation_id)."""
        existing = await self.portfolio.get_valuation_batch(batch.valuation_id)
        if existing is not None:
            return existing
        return await self.portfolio.record_valuation_batch(
            valuation_id=batch.valuation_id,
            account_id=batch.account_id,
            currency=batch.currency,
            quality=batch.quality,
            raw_mtm_equity=batch.raw_mtm_equity,
            fallback_equity=fallback_equity,
            market_as_of=batch.market_as_of,
            ledger_watermark=batch.ledger_watermark,
            position_snapshot_ref=batch.position_snapshot_ref,
            reason_codes=list(batch.reason_codes),
            missing_marks=list(batch.missing_marks),
            stale_marks=list(batch.stale_marks),
            components=list(batch.components),
        )

    async def get(self, valuation_id: str) -> ValuationBatch | None:
        return await self.portfolio.get_valuation_batch(valuation_id)

    async def latest(
        self, *, account_id: str = "default", currency: str = "USDT"
    ) -> ValuationBatch | None:
        return await self.portfolio.latest_valuation_batch(
            account_id=account_id, currency=currency
        )

    @staticmethod
    def position_snapshot_ref(positions: Mapping[str, Position]) -> str:
        payload = [
            [
                symbol,
                str(position.quantity),
                str(position.avg_entry_price or ""),
                position.instrument_type,
            ]
            for symbol, position in sorted(positions.items())
        ]
        digest = hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        return f"posnap-{digest[:32]}"
