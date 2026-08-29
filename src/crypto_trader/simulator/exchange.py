"""SimulatedExchangeAdapter.

Implements the exact same ExchangeAdapter contract as Binance. Paper, shadow,
and tests run through this adapter; the core never branches on simulation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.enums import (
    ExchangeEventType,
    OrderSide,
    OrderStatus,
    OrderType,
)
from crypto_trader.domain.errors import (
    InvalidOrder,
    OrderNotFound,
    OrderRejected,
    RateLimited,
    UnknownExecutionState,
)
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import Balance, ExchangeEvent, Fill, Instrument, Order, Position
from crypto_trader.domain.money import D, format_decimal
from crypto_trader.exchange.base import ExchangeAdapter
from crypto_trader.market_data.orderbook import OrderBook


class SimulatedExchangeAdapter(ExchangeAdapter):
    name = "SIMULATED"

    def __init__(
        self,
        *,
        initial_balances: dict[str, Decimal] | None = None,
        instruments: list[Instrument] | None = None,
        fee_rate: Decimal = Decimal("0.001"),
        order_id_namespace: str = "",
    ) -> None:
        self.balances: dict[str, Decimal] = {
            k: D(v) for k, v in (initial_balances or {"USDT": Decimal("100000")}).items()
        }
        self.positions: dict[str, Position] = {}
        self.orders: dict[str, Order] = {}
        self.books: dict[str, OrderBook] = {}
        self.sequence: dict[str, int] = {}
        self.fee_rate = D(fee_rate)
        self.connected = False
        self._handlers: dict[str, Callable[[ExchangeEvent], Awaitable[None]]] = {}
        self._sub_counter = 0
        self.next_exchange_order_id = 1000
        # A fresh process restarts the sequence at 1000 while the persistent
        # ledger/orders keep historical sim_N ids; without a per-process
        # namespace the DB UNIQUE(exchange_order_id) would collide on the
        # first order of every restart. The namespace is injected per run.
        self.order_id_namespace: str = order_id_namespace

        self.event_log: list[ExchangeEvent] = []

        # chaos / fault injection hooks
        self.fail_submit_with: Exception | None = None
        self.submit_delay_seconds: float = 0.0
        self.timeout_but_created: bool = False
        self.fill_before_ack: bool = False
        self.duplicate_fill: bool = False
        self.cancel_fill_race: bool = False
        self.reject_next_order: str | None = None
        self.rate_limit_next: bool = False
        self.sequence_gap_next_delta: bool = False
        self.disconnected: bool = False

        self.default_instrument = Instrument(
            symbol="BTCUSDT",
            base_asset="BTC",
            quote_asset="USDT",
            tick_size="0.01",
            step_size="0.00001",
            min_qty="0.00001",
            min_notional="5",
            price_precision=2,
            quantity_precision=5,
            exchange=self.name,
        )
        self.instruments = {i.symbol: i for i in (instruments or [self.default_instrument])}

    # ------------------------------------------------------------------ base
    async def connect(self) -> None:
        self.connected = True
        self.disconnected = False

    async def disconnect(self) -> None:
        self.connected = False
        self.disconnected = True

    def _ensure_connected(self) -> None:
        if not self.connected or self.disconnected:
            raise ConnectionError("simulated exchange is disconnected")

    async def _emit(self, event: ExchangeEvent) -> None:
        self.event_log.append(event)
        for handler in list(self._handlers.values()):
            try:
                await handler(event)
            except Exception:
                # a broken observer must not break exchange event distribution
                pass

    async def _subscribe(self, handler: Callable[[ExchangeEvent], Awaitable[None]]) -> str:
        self._sub_counter += 1
        sub_id = f"sim_sub_{self._sub_counter}"
        self._handlers[sub_id] = handler
        return sub_id

    async def subscribe_market_data(
        self, symbol: str, handler: Callable[[ExchangeEvent], Awaitable[None]]
    ) -> str:
        return await self._subscribe(handler)

    async def subscribe_order_updates(
        self, handler: Callable[[ExchangeEvent], Awaitable[None]]
    ) -> str:
        return await self._subscribe(handler)

    async def subscribe_account_updates(
        self, handler: Callable[[ExchangeEvent], Awaitable[None]]
    ) -> str:
        return await self._subscribe(handler)

    # ------------------------------------------------------------- market data
    async def get_exchange_info(self, symbol: str | None = None) -> list[Instrument]:
        return [self.instruments[s] for s in self.instruments if symbol is None or s == symbol]

    async def get_orderbook(self, symbol: str, limit: int = 100) -> OrderBook:
        self._ensure_connected()
        if symbol not in self.books:
            self.seed_book(symbol)
        return self.books[symbol]

    def seed_book(
        self, symbol: str, mid: str = "100", spread: str = "0.05", depth: int = 5
    ) -> OrderBook:
        mid_d = D(mid)
        spread_d = D(spread)
        book = OrderBook(symbol=symbol, exchange=self.name)
        bids = [(mid_d - spread_d * (i + 1), Decimal("1")) for i in range(depth)]
        asks = [(mid_d + spread_d * (i + 1), Decimal("1")) for i in range(depth)]
        self.sequence[symbol] = self.sequence.get(symbol, 0) + 1
        book.apply_snapshot(self.sequence[symbol], bids, asks)
        self.books[symbol] = book
        return book

    async def emit_market_delta(
        self, symbol: str, bids: list[tuple[Decimal, Decimal]], asks: list[tuple[Decimal, Decimal]]
    ) -> None:
        self._ensure_connected()
        await self.get_orderbook(symbol)
        if self.sequence_gap_next_delta:
            self.sequence_gap_next_delta = False
            self.sequence[symbol] += 2  # create a gap
        else:
            self.sequence[symbol] += 1
        await self._emit(
            ExchangeEvent(
                event_id=new_id("exevt"),
                event_type=ExchangeEventType.MARKET_DELTA,
                symbol=symbol,
                timestamp=datetime.now(UTC),
                payload={
                    "sequence": self.sequence[symbol],
                    "bids": [[format_decimal(p), format_decimal(q)] for p, q in bids],
                    "asks": [[format_decimal(p), format_decimal(q)] for p, q in asks],
                },
            )
        )

    async def get_ticker(self, symbol: str) -> dict:
        book = await self.get_orderbook(symbol)
        bid = book.best_bid()
        ask = book.best_ask()
        return {
            "symbol": symbol,
            "bid": format_decimal(bid.price) if bid else "0",
            "ask": format_decimal(ask.price) if ask else "0",
            "bid_quantity": format_decimal(bid.quantity) if bid else "0",
            "ask_quantity": format_decimal(ask.quantity) if ask else "0",
        }

    # ----------------------------------------------------------------- orders
    def _local_order_for(self, raw: Order) -> Order:
        return Order(
            internal_order_id=raw.internal_order_id,
            client_order_id=raw.client_order_id,
            exchange_order_id=f"sim_{self.order_id_namespace}{self.next_exchange_order_id}",
            symbol=raw.symbol,
            side=raw.side,
            order_type=raw.order_type,
            time_in_force=raw.time_in_force,
            price=raw.price,
            quantity=raw.quantity,
            filled_quantity=Decimal("0"),
            avg_fill_price=None,
            status=OrderStatus.ACKNOWLEDGED,
            trading_mode=raw.trading_mode,
            strategy_id=raw.strategy_id,
            run_id=raw.run_id,
            created_at=raw.created_at,
            updated_at=raw.created_at,
            expires_at=raw.expires_at,
            market_type=raw.market_type,
            position_side=raw.position_side,
            reduce_only=raw.reduce_only,
        )

    async def submit_order(self, order: Order) -> Order:
        self._ensure_connected()
        if self.rate_limit_next:
            self.rate_limit_next = False
            raise RateLimited("simulated rate limit")
        if self.reject_next_order:
            reason = self.reject_next_order
            self.reject_next_order = None
            raise OrderRejected(f"simulated rejection: {reason}")
        if self.fail_submit_with is not None:
            exc = self.fail_submit_with
            self.fail_submit_with = None
            raise exc
        if self.submit_delay_seconds:
            await asyncio.sleep(self.submit_delay_seconds)

        local = self._local_order_for(order)
        self.next_exchange_order_id += 1
        self.orders[local.exchange_order_id] = local

        if self.timeout_but_created:
            self.timeout_but_created = False
            raise UnknownExecutionState(
                f"submit timeout after order reached exchange: {local.exchange_order_id}"
            )

        ack_event = self._order_event(ExchangeEventType.ORDER_ACK, local, payload={"status": "ACK"})
        fill_events = self._match_order(local)

        # Ordering hooks: normal = ack first; chaos = fill before ack
        if self.fill_before_ack:
            for fill_event in fill_events:
                await self._emit(fill_event)
            await self._emit(ack_event)
            if self.duplicate_fill and fill_events:
                await self._emit(fill_events[0])
        else:
            await self._emit(ack_event)
            await self._emit(
                self._order_event(ExchangeEventType.ORDER_OPENED, local, payload={"status": "OPEN"})
            )
            for fill_event in fill_events:
                await self._emit(fill_event)
                if self.duplicate_fill:
                    await self._emit(fill_event)
        return self.orders[local.exchange_order_id]

    def _order_event(
        self, event_type: ExchangeEventType, order: Order, payload: dict | None = None
    ) -> ExchangeEvent:
        return ExchangeEvent(
            event_id=new_id("exevt"),
            event_type=event_type,
            symbol=order.symbol,
            timestamp=datetime.now(UTC),
            payload={
                "exchange_order_id": order.exchange_order_id,
                "client_order_id": order.client_order_id,
                "order_id": order.internal_order_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "price": format_decimal(order.price) if order.price is not None else "0",
                "quantity": format_decimal(order.quantity),
                "filled_quantity": format_decimal(order.filled_quantity),
                **({"status": payload["status"]} if payload and "status" in payload else {}),
                **(payload or {}),
            },
        )

    def _match_order(self, order: Order) -> list[ExchangeEvent]:
        """Match a resting/marketable order against the simulated book."""
        # CRITICAL: seed_book() STORES the synthetic book into self.books;
        # calling it eagerly here (setdefault default) would overwrite a real
        # refreshed book on every match and fill every order at ~100.
        book = self.books.get(order.symbol)
        if book is None:
            book = self.seed_book(order.symbol)
        instrument = self.instruments.get(order.symbol, self.default_instrument)
        remaining = order.quantity
        fill_events: list[ExchangeEvent] = []
        limit = order.price if order.order_type == OrderType.LIMIT else None

        while remaining > 0:
            level = book.best_ask() if order.side == OrderSide.BUY else book.best_bid()
            if level is None:
                break
            if order.side == OrderSide.BUY and limit is not None and level.price > limit:
                break
            if order.side == OrderSide.SELL and limit is not None and level.price < limit:
                break
            qty = min(remaining, level.quantity)
            price = level.price
            gross = price * qty
            fee = (gross * self.fee_rate).quantize(Decimal("0.00000001"))
            fill = Fill(
                fill_id=new_id("fill"),
                trade_id=new_id("trade"),
                order_id=order.internal_order_id,
                client_order_id=order.client_order_id,
                exchange_order_id=order.exchange_order_id,
                symbol=order.symbol,
                side=order.side,
                price=price,
                quantity=qty,
                fee=fee,
                fee_currency=instrument.quote_asset,
                timestamp=datetime.now(UTC),
            )
            remaining -= qty
            order.filled_quantity += qty
            if order.filled_quantity == order.quantity:
                order.status = OrderStatus.FILLED
                order.avg_fill_price = (
                    (order.avg_fill_price or Decimal("0")) * (order.filled_quantity - qty)
                    + price * qty
                ) / order.filled_quantity
            else:
                order.status = OrderStatus.PARTIALLY_FILLED
                order.avg_fill_price = (
                    (order.avg_fill_price or Decimal("0")) * (order.filled_quantity - qty)
                    + price * qty
                ) / order.filled_quantity
            self._apply_fill_to_balances(fill, instrument)
            # consume book level
            key = format_decimal(price)
            side_book = book.asks if order.side == OrderSide.BUY else book.bids
            if qty == level.quantity:
                side_book.pop(key, None)
            else:
                side_book[key] = side_book[key].model_copy(
                    update={"quantity": level.quantity - qty}
                )
            fill_events.append(
                self._order_event(
                    ExchangeEventType.ORDER_FILLED
                    if order.status == OrderStatus.FILLED
                    else ExchangeEventType.ORDER_PARTIALLY_FILLED,
                    order,
                    payload={
                        "fill_id": fill.fill_id,
                        "trade_id": fill.trade_id,
                        "fill_price": format_decimal(fill.price),
                        "fill_quantity": format_decimal(fill.quantity),
                        "fee": format_decimal(fill.fee),
                        "fee_currency": fill.fee_currency,
                    },
                )
            )
        return fill_events

    def _apply_fill_to_balances(self, fill: Fill, instrument: Instrument) -> None:
        quote = instrument.quote_asset
        base = instrument.base_asset
        gross = fill.price * fill.quantity
        if fill.side == OrderSide.BUY:
            self.balances[base] = self.balances.get(base, Decimal("0")) + fill.quantity
            self.balances[quote] = self.balances.get(quote, Decimal("0")) - gross - fill.fee
        else:
            self.balances[base] = self.balances.get(base, Decimal("0")) - fill.quantity
            self.balances[quote] = self.balances.get(quote, Decimal("0")) + gross - fill.fee
        pos = self.positions.get(fill.symbol)
        if pos is None:
            pos = Position(symbol=fill.symbol, base_asset=base, quote_asset=quote)
            self.positions[fill.symbol] = pos
        if fill.side == OrderSide.BUY:
            new_qty = pos.quantity + fill.quantity
            new_cost = pos.cost_basis + gross
            pos.quantity = new_qty
            pos.cost_basis = new_cost
            pos.avg_entry_price = (new_cost / new_qty) if new_qty else None
        else:
            release = (pos.avg_entry_price or Decimal("0")) * fill.quantity
            pos.quantity -= fill.quantity
            pos.cost_basis = max(pos.cost_basis - release, Decimal("0"))
            pos.realized_pnl += gross - release
            if pos.quantity == 0:
                pos.avg_entry_price = None
                pos.cost_basis = Decimal("0")
        pos.updated_at = fill.timestamp

    async def cancel_order(self, symbol: str, exchange_order_id: str) -> Order:
        self._ensure_connected()
        order = self.orders.get(exchange_order_id)
        if order is None:
            raise OrderNotFound(f"simulated order not found: {exchange_order_id}")
        if order.status == OrderStatus.FILLED:
            return order
        if self.cancel_fill_race and order.remaining_quantity > 0:
            fill = Fill(
                fill_id=new_id("fill"),
                trade_id=new_id("trade"),
                order_id=order.internal_order_id,
                client_order_id=order.client_order_id,
                exchange_order_id=order.exchange_order_id,
                symbol=order.symbol,
                side=order.side,
                price=(order.price or self.books[symbol].mid_price() or Decimal("100")),
                quantity=order.remaining_quantity,
                fee=Decimal("0"),
                fee_currency=None,
                timestamp=datetime.now(UTC),
            )
            order.filled_quantity = order.quantity
            order.status = OrderStatus.FILLED
            await self._emit(
                self._order_event(
                    ExchangeEventType.ORDER_FILLED,
                    order,
                    payload={
                        "fill_id": fill.fill_id,
                        "fill_price": format_decimal(fill.price),
                        "fill_quantity": format_decimal(fill.quantity),
                        "fee": "0",
                    },
                )
            )
            return order
        order.status = OrderStatus.CANCELLED
        await self._emit(
            self._order_event(
                ExchangeEventType.ORDER_CANCELLED, order, payload={"status": "CANCELED"}
            )
        )
        return order

    async def get_order(self, symbol: str, exchange_order_id: str) -> Order:
        """Look up by exchange id; also accepts client id like Binance origClientOrderId."""
        self._ensure_connected()
        order = self.orders.get(exchange_order_id)
        if order is None:
            for candidate in self.orders.values():
                if candidate.client_order_id == exchange_order_id:
                    order = candidate
                    break
        if order is None:
            raise OrderNotFound(f"simulated order not found: {exchange_order_id}")
        return order

    # ------------------------------------------------------------ account/pos
    async def get_balances(self) -> list[Balance]:
        self._ensure_connected()
        return [
            Balance(currency=currency, total=amount, available=amount, frozen=Decimal("0"))
            for currency, amount in sorted(self.balances.items())
        ]

    async def hydrate_from_ledger(self, session_factory) -> None:
        """Ledger-first startup: adopt the persistent ledger projection.

        The simulated exchange state is in-memory; without hydration every
        restart diverges from the persistent ledger and the reconciliation
        service (correctly) halts all execution. The ledger is the source of
        truth, so the paper exchange adopts it on startup.
        """
        from crypto_trader.ledger.projections import (
            FUTURES_EXCLUDED_ENTRY_TYPES,
            replay_projections,
        )

        # Same spot scope as ReconciliationService so the hydrated exchange
        # view stays comparable with the reconciliation replay.
        async with session_factory() as session:
            snapshot = await replay_projections(
                session, exclude_entry_types=FUTURES_EXCLUDED_ENTRY_TYPES
            )
        if snapshot.balances:
            self.balances = {
                currency: D(row["total"])
                for currency, row in snapshot.balances.items()
            }
        hydrated_positions: dict[str, Position] = {}
        for symbol, view in snapshot.positions.items():
            if view.quantity == 0:
                continue
            hydrated_positions[symbol] = Position(
                symbol=symbol,
                base_asset=view.base_asset,
                quote_asset=view.quote_asset,
                quantity=view.quantity,
                avg_entry_price=view.avg_entry_price,
                cost_basis=view.cost_basis,
                realized_pnl=view.realized_pnl,
            )
        self.positions = hydrated_positions

    async def get_positions(self) -> list[Position]:
        self._ensure_connected()
        return list(self.positions.values())

    # ------------------------------------------------------------ normalize
    def normalize_symbol(self, raw: object) -> str:
        return str(raw).upper()

    def normalize_order(self, raw: dict) -> Order:
        order = raw.get("_order")
        if order is not None:
            return order
        raise InvalidOrder("simulated normalize_order expects a simulated order")

    def normalize_fill(self, raw: dict) -> Fill:
        return Fill(
            fill_id=raw["fill_id"],
            trade_id=raw.get("trade_id"),
            order_id=raw.get("order_id", ""),
            client_order_id=raw.get("client_order_id"),
            exchange_order_id=raw.get("exchange_order_id"),
            symbol=raw["symbol"],
            side=OrderSide(raw["side"]),
            price=D(raw["fill_price"]),
            quantity=D(raw["fill_quantity"]),
            fee=D(raw.get("fee", "0")),
            fee_currency=raw.get("fee_currency"),
            timestamp=datetime.now(UTC),
        )

    async def emit_order_rejected(self, exchange_order_id: str, reason: str) -> None:
        order = self.orders.get(exchange_order_id)
        if order is None:
            return
        order.status = OrderStatus.REJECTED
        await self._emit(
            self._order_event(
                ExchangeEventType.ORDER_REJECTED,
                order,
                payload={"status": "REJECTED", "reason": reason},
            )
        )
