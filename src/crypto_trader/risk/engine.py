"""Trading-system risk engine.

Only system-level limits are implemented (SPAC section 8). Strategy-specific
risk preference is intentionally out of scope.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from crypto_trader.domain.enums import ExecutionDecision, MarketType, OrderSide
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import Account, OrderIntent, Position, RiskDecision, SignalIntent
from crypto_trader.domain.money import D
from crypto_trader.risk.kill_switch import KillSwitch


def check_no_reversal(
    *,
    market_type: MarketType,
    side: OrderSide,
    quantity: Decimal,
    reduce_only: bool,
    current_signed_qty: Decimal,
) -> tuple[bool, str]:
    """Pre-trade no-reversal hard gate.

    ``current_signed_qty`` is the signed position for the order's symbol
    (positive = LONG, negative = SHORT, zero = FLAT). Returns ``(allowed,
    reason)``.
    """
    qty = D(quantity)
    if qty <= 0:
        return False, "INVALID_QUANTITY"
    signed = D(current_signed_qty)

    if reduce_only:
        if signed == 0:
            return False, "REDUCE_ONLY_WITHOUT_POSITION"
        if side == OrderSide.SELL:
            # reducing a LONG
            if signed <= 0:
                return False, "REDUCE_ONLY_SELL_AGAINST_SHORT_OR_FLAT"
            if qty > signed:
                return False, "REDUCE_ONLY_WOULD_REVERSE"
        else:
            # reducing a SHORT
            if signed >= 0:
                return False, "REDUCE_ONLY_BUY_AGAINST_LONG_OR_FLAT"
            if qty > -signed:
                return False, "REDUCE_ONLY_WOULD_REVERSE"
        return True, "NO_REVERSAL_PASS"

    # reduce_only = False: OPEN/ADD path. Spot may never create a SHORT.
    if market_type == MarketType.SPOT and side == OrderSide.SELL:
        if qty > signed:
            return False, "SPOT_OVERSHORT"
    return True, "NO_REVERSAL_PASS"


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_order_notional: Decimal = Field(default=Decimal("1000000"))
    max_position_notional: Decimal = Field(default=Decimal("1000000"))
    max_account_exposure: Decimal = Field(default=Decimal("5000000"))
    max_open_orders: int = Field(default=20)
    max_daily_loss: Decimal = Field(default=Decimal("100000"))
    max_drawdown: Decimal = Field(default=Decimal("200000"))
    max_leverage: Decimal = Field(default=Decimal("5"))
    max_symbol_exposure: Decimal = Field(default=Decimal("1000000"))
    max_exchange_exposure: Decimal = Field(default=Decimal("5000000"))
    max_consecutive_failures: int = Field(default=10)


class RiskEngine:
    def __init__(
        self, config: RiskConfig | None = None, kill_switch: KillSwitch | None = None
    ) -> None:
        self.config = config or RiskConfig()
        self.kill_switch = kill_switch or KillSwitch()

    def check(
        self,
        intent: SignalIntent | OrderIntent,
        *,
        account: Account,
        positions: dict[str, Position],
        market_price: Decimal,
        open_order_count: int,
        daily_pnl: Decimal = Decimal("0"),
        drawdown: Decimal = Decimal("0"),
        consecutive_failures: int = 0,
        run_id: str | None = None,
        order_id: str | None = None,
        current_signed_qty: Decimal | None = None,
    ) -> RiskDecision:
        now = datetime.now(UTC)
        client_order_id = (
            getattr(intent, "client_order_id", None)
            or getattr(intent, "signal_id", None)
            or "unknown"
        )
        checks: dict[str, bool | str] = {}

        def fail(reason: str) -> RiskDecision:
            checks[reason] = False
            return RiskDecision(
                risk_decision_id=new_id("risk"),
                order_id=order_id,
                client_order_id=client_order_id,
                symbol=intent.symbol,
                side=intent.side,
                decision=ExecutionDecision.REJECT,
                reason=reason,
                checks=checks,
                timestamp=now,
                run_id=run_id,
            )

        if self.kill_switch.enabled:
            return fail("GLOBAL_KILL_SWITCH")

        qty = D(intent.quantity)
        price = D(intent.limit_price or market_price)
        if qty <= 0:
            return fail("INVALID_QUANTITY")
        if price <= 0:
            return fail("INVALID_PRICE")
        notional = price * qty

        # Pre-trade no-reversal hard gate (SPOT long-only + reduce_only).
        market_type = getattr(intent, "market_type", MarketType.SPOT)
        metadata = getattr(intent, "metadata", None) or {}
        reduce_only = bool(
            getattr(intent, "reduce_only", False) or metadata.get("reduce_only", False)
        )

        # Signed position for the order's symbol: explicit override wins, else
        # derive from the spot position projection.
        if current_signed_qty is None:
            current_symbol = positions.get(intent.symbol)
            current_signed_qty = D(current_symbol.quantity if current_symbol else Decimal("0"))

        allowed, reason = check_no_reversal(
            market_type=market_type,
            side=intent.side,
            quantity=qty,
            reduce_only=reduce_only,
            current_signed_qty=current_signed_qty,
        )
        if not allowed:
            return fail(reason)

        if getattr(intent, "quote_order_qty", None) is not None:
            notional = D(intent.quote_order_qty)

        if notional > self.config.max_order_notional:
            return fail("MAX_ORDER_NOTIONAL")
        checks["max_order_notional"] = True

        if open_order_count >= self.config.max_open_orders:
            return fail("MAX_OPEN_ORDERS")
        checks["max_open_orders"] = True

        if consecutive_failures >= self.config.max_consecutive_failures:
            return fail("MAX_CONSECUTIVE_FAILURES")
        checks["max_consecutive_failures"] = True

        if daily_pnl < -abs(self.config.max_daily_loss):
            return fail("MAX_DAILY_LOSS")
        checks["max_daily_loss"] = True

        if drawdown < -abs(self.config.max_drawdown):
            return fail("MAX_DRAWDOWN")
        checks["max_drawdown"] = True

        # Exposure accounting (direction-aware: a reduce never widens exposure).
        cash = account.equity
        existing_notional = sum((p.cost_basis for p in positions.values()), Decimal("0"))
        current_symbol = positions.get(intent.symbol)
        current_symbol_notional = abs(
            D(current_symbol.cost_basis if current_symbol else Decimal("0"))
        )
        delta = qty if intent.side == OrderSide.BUY else -qty
        projected_signed = current_signed_qty + delta
        checks["projected_signed_quantity"] = str(projected_signed)
        increasing = abs(projected_signed) > abs(current_signed_qty)

        if increasing:
            symbol_notional = current_symbol_notional + notional
            if symbol_notional > self.config.max_symbol_exposure:
                return fail("MAX_SYMBOL_EXPOSURE")
            checks["max_symbol_exposure"] = True

            projected_exposure = existing_notional + notional
            if projected_exposure > self.config.max_account_exposure:
                return fail("MAX_ACCOUNT_EXPOSURE")
            checks["max_account_exposure"] = True

            if existing_notional > self.config.max_exchange_exposure:
                return fail("MAX_EXCHANGE_EXPOSURE")
            checks["max_exchange_exposure"] = True

            if projected_exposure > self.config.max_position_notional:
                return fail("MAX_POSITION_NOTIONAL")
            checks["max_position_notional"] = True

            if cash > 0 and (projected_exposure / cash) > self.config.max_leverage:
                return fail("MAX_LEVERAGE")
            checks["max_leverage"] = True
        else:
            # Reducing or flat: over-exposure limits must never block a de-risk.
            checks["max_symbol_exposure"] = "REDUCE_ONLY"
            checks["max_account_exposure"] = "REDUCE_ONLY"
            checks["max_exchange_exposure"] = "REDUCE_ONLY"
            checks["max_position_notional"] = "REDUCE_ONLY"
            checks["max_leverage"] = "REDUCE_ONLY"

        checks["notional"] = str(notional)
        return RiskDecision(
            risk_decision_id=new_id("risk"),
            order_id=order_id,
            client_order_id=client_order_id,
            symbol=intent.symbol,
            side=intent.side,
            decision=ExecutionDecision.APPROVE,
            reason="RISK_PASS",
            checks=checks,
            timestamp=now,
            run_id=run_id,
        )
