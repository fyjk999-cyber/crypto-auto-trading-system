"""Perpetual paper engine: true LONG/SHORT with margin, funding, liquidation.

This engine is a service on top of the existing LedgerService; it never
executes exchange orders. It exists to close the gap for paper perpetual
positions and tests. Live execution remains through ExchangeAdapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D
from crypto_trader.ledger.service import LedgerService
from crypto_trader.perpetual.domain import (
    MarginPosition,
    PerpetualContract,
    PositionSide,
)
from crypto_trader.perpetual.funding import FundingCalculator
from crypto_trader.perpetual.ledger import FuturesLedger, rebuild_futures_projection
from crypto_trader.perpetual.liquidation import LiquidationCalculator
from crypto_trader.perpetual.margin import MarginCalculator


@dataclass
class PerpetualAccountState:
    positions: dict[str, MarginPosition]
    cash: Decimal
    margin_balance: Decimal
    realized_pnl: Decimal
    funding_paid: Decimal
    funding_received: Decimal
    fees_paid: Decimal


class PerpetualPaperEngine:
    def __init__(self, session_factory, contract: PerpetualContract) -> None:
        self.session_factory = session_factory
        self.contract = contract
        self.ledger = LedgerService(session_factory)
        self.futures_ledger = FuturesLedger(self.ledger)
        self.margin = MarginCalculator()
        self.funding = FundingCalculator()
        self.liquidation = LiquidationCalculator()
        self._cache: PerpetualAccountState | None = None

    async def load_state(self) -> PerpetualAccountState:
        async with self.session_factory() as session:
            snap = await rebuild_futures_projection(session)
        self._cache = PerpetualAccountState(
            positions=snap.positions,
            cash=Decimal("0"),  # cash is held in the existing account projection
            margin_balance=snap.margin_balance,
            realized_pnl=snap.realized_pnl,
            funding_paid=snap.funding_paid,
            funding_received=snap.funding_received,
            fees_paid=snap.fees_paid,
        )
        return self._cache

    async def open_position(
        self,
        side: PositionSide,
        quantity: Decimal,
        price: Decimal,
        leverage: Decimal,
        order_id: str | None = None,
    ) -> MarginPosition:
        if side == PositionSide.FLAT:
            raise ValueError("cannot open FLAT position")
        qty = abs(D(quantity))
        price = D(price)
        contract = self.contract
        lev = self.margin.effective_leverage(leverage, contract.max_leverage)
        initial_margin = self.margin.initial_margin(contract, qty, price, lev)
        maintenance = self.margin.maintenance_margin(contract, qty, price)
        fee = qty * price * contract.contract_size * contract.taker_fee_rate
        await self.futures_ledger.record_open(
            contract, side, qty, price, lev, initial_margin, fee, order_id=order_id
        )
        await self.load_state()
        pos = self._cache.positions[contract.symbol]
        pos.maintenance_margin = maintenance
        pos.liquidation_price = self.liquidation.liquidation_price(pos, contract).value
        return pos

    async def close_position(
        self,
        side: PositionSide,
        quantity: Decimal,
        exit_price: Decimal,
        order_id: str | None = None,
    ) -> MarginPosition | None:
        state = await self.load_state()
        pos = state.positions.get(self.contract.symbol)
        if pos is None or pos.side != side:
            return None
        qty = min(abs(D(quantity)), abs(pos.quantity))
        entry = pos.avg_entry_price
        exit_px = D(exit_price)
        if pos.side == PositionSide.LONG:
            realized = (exit_px - entry) * qty * self.contract.contract_size
        else:
            realized = (entry - exit_px) * qty * self.contract.contract_size
        margin_release = (
            pos.initial_margin * qty / abs(pos.quantity) if pos.quantity else Decimal("0")
        )
        fee = qty * exit_px * self.contract.contract_size * self.contract.taker_fee_rate
        await self.futures_ledger.record_close(
            self.contract,
            side,
            qty,
            entry,
            exit_px,
            realized,
            fee,
            margin_release,
            order_id=order_id,
        )
        await self.load_state()
        return self._cache.positions.get(self.contract.symbol)

    async def apply_funding(self, rate: Decimal, mark_price: Decimal) -> Decimal:
        state = await self.load_state()
        pos = state.positions.get(self.contract.symbol)
        if pos is None or pos.is_flat:
            return Decimal("0")
        payment = self.funding.payment(pos, D(rate), D(mark_price), self.contract.contract_size)
        if payment.amount != 0:
            await self.futures_ledger.record_funding(
                self.contract, pos.side, payment.amount, payment.rate, payment.notional
            )
            await self.load_state()
        return payment.amount

    async def mark_to_market(self, mark_price: Decimal) -> MarginPosition | None:
        state = await self.load_state()
        pos = state.positions.get(self.contract.symbol)
        if pos is None:
            return None
        if pos.side == PositionSide.LONG:
            pos.unrealized_pnl = (
                (D(mark_price) - pos.avg_entry_price)
                * abs(pos.quantity)
                * self.contract.contract_size
            )
        elif pos.side == PositionSide.SHORT:
            pos.unrealized_pnl = (
                (pos.avg_entry_price - D(mark_price))
                * abs(pos.quantity)
                * self.contract.contract_size
            )
        else:
            pos.unrealized_pnl = Decimal("0")
        pos.mark_price = D(mark_price)
        return pos

    async def liquidate(self, mark_price: Decimal) -> bool:
        state = await self.load_state()
        pos = state.positions.get(self.contract.symbol)
        if pos is None:
            return False
        await self.mark_to_market(mark_price)
        result = self.liquidation.evaluate(pos, self.contract, D(mark_price))
        if not result.liquidated:
            return False
        # close with zero realized? liquidation closes at mark with fee
        await self.futures_ledger.record_close(
            self.contract,
            pos.side,
            abs(pos.quantity),
            pos.avg_entry_price,
            D(mark_price),
            pos.unrealized_pnl,
            result.fee,
            pos.initial_margin,
            order_id=None,
        )
        await self.load_state()
        return True
