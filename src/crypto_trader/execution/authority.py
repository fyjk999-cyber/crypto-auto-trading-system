"""Final ExecutionAuthority gate before any order leaves core.

Every critical condition is checked; any failure returns HOLD (transient) or
REJECT (permanent invalid request). No order may pass while kill switch is on,
the execution lease is not held, or market data is unhealthy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from crypto_trader.domain.enums import ExecutionDecision, OrderStatus, TradingMode
from crypto_trader.domain.errors import KillSwitchEngaged, LeaseNotHeld, MarketDataUnhealthy
from crypto_trader.domain.models import Instrument, OrderIntent, RiskDecision
from crypto_trader.domain.money import D, floor_to_step, round_tick
from crypto_trader.execution.rate_limiter import RateLimiter
from crypto_trader.risk.kill_switch import KillSwitch


@dataclass
class AuthorizationContext:
    now: datetime | None = None
    trading_mode: TradingMode = TradingMode.PAPER
    live_enabled: bool = False
    lease_held: bool = False
    lease_token: str | None = None
    kill_switch: KillSwitch | None = None
    order_status: OrderStatus = OrderStatus.CREATED
    expires_at: datetime | None = None
    market_data_fresh: bool = False
    orderbook_fresh: bool = False
    orderbook_healthy: bool = False
    symbol_tradeable: bool = False
    exchange_connected: bool = False
    balance_fresh: bool = False
    risk_decision: RiskDecision | None = None
    instrument: Instrument | None = None
    duplicate_client_order: bool = False
    reconciliation_halted: bool = False
    rate_limiter: RateLimiter | None = None
    min_notional_ok: bool = True
    notes: list[str] = field(default_factory=list)


class ExecutionAuthority:
    def __init__(self) -> None:
        pass

    async def authorize(
        self, intent: OrderIntent, ctx: AuthorizationContext
    ) -> tuple[ExecutionDecision, list[str]]:
        """Return final gate decision with ordered failure notes."""
        now = ctx.now or datetime.now(timezone.utc)
        notes: list[str] = []

        def hold(reason: str) -> tuple[ExecutionDecision, list[str]]:
            notes.append(reason)
            return ExecutionDecision.HOLD, notes

        def reject(reason: str) -> tuple[ExecutionDecision, list[str]]:
            notes.append(reason)
            return ExecutionDecision.REJECT, notes

        # 1. lease must be valid for any new order
        if not ctx.lease_held:
            return reject("EXECUTION_LEASE_NOT_HELD")
        # 2. trading mode valid; live requires explicit live enable
        if ctx.trading_mode == TradingMode.LIVE and not ctx.live_enabled:
            return reject("LIVE_TRADING_DISABLED")
        if ctx.trading_mode not in (TradingMode.PAPER, TradingMode.SHADOW, TradingMode.LIVE):
            return reject("INVALID_TRADING_MODE")
        # 3. kill switch
        if ctx.kill_switch is not None and ctx.kill_switch.enabled:
            return reject("GLOBAL_KILL_SWITCH")
        # 4. reconciliation halt pauses new orders
        if ctx.reconciliation_halted:
            return hold("RECONCILIATION_HALT")
        # 5. order not expired
        if intent.expires_at is not None and intent.expires_at <= now:
            return reject("ORDER_EXPIRED")
        # 6. market data and orderbook freshness / health
        if not ctx.market_data_fresh:
            return hold("MARKET_DATA_STALE")
        if not ctx.orderbook_fresh:
            return hold("ORDERBOOK_STALE")
        if not ctx.orderbook_healthy:
            return hold("ORDERBOOK_UNHEALTHY")
        # 7. symbol tradeable
        if not ctx.symbol_tradeable:
            return reject("SYMBOL_NOT_TRADEABLE")
        # 8. exchange connection and balance freshness
        if not ctx.exchange_connected:
            return hold("EXCHANGE_NOT_CONNECTED")
        if not ctx.balance_fresh:
            return hold("BALANCE_STALE")
        # 9. order state must be valid
        if ctx.order_status not in (
            OrderStatus.CREATED,
            OrderStatus.VALIDATED,
            OrderStatus.UNKNOWN,
        ):
            return reject("ORDER_STATE_INVALID")
        # 10. duplicate client order id
        if ctx.duplicate_client_order:
            return hold("DUPLICATE_CLIENT_ORDER_ID")
        # 11. risk must still be valid
        if ctx.risk_decision is None or ctx.risk_decision.decision != ExecutionDecision.APPROVE:
            return reject("RISK_NOT_VALID")
        # 12. precision, min quantity, min notional
        instrument = ctx.instrument
        if instrument is None:
            return reject("INSTRUMENT_MISSING")
        price = intent.price or D("0")
        qty = intent.quantity
        if price > 0 and round_tick(price, instrument.tick_size) != price:
            return reject("PRICE_PRECISION_INVALID")
        if floor_to_step(qty, instrument.step_size) != qty:
            return reject("QUANTITY_PRECISION_INVALID")
        if qty < instrument.min_qty:
            return reject("MIN_QUANTITY_NOT_MET")
        notional = (price * qty) if price > 0 else D("0")
        if notional > 0 and notional < instrument.min_notional:
            return reject("MIN_NOTIONAL_NOT_MET")
        if not ctx.min_notional_ok:
            return reject("MIN_NOTIONAL_NOT_MET")
        # 13. rate-limit budget
        if ctx.rate_limiter is not None and not ctx.rate_limiter.allow(1):
            return hold("RATE_LIMIT_BUDGET_EXHAUSTED")
        notes.append("AUTHORITY_PASS")
        return ExecutionDecision.APPROVE, notes
