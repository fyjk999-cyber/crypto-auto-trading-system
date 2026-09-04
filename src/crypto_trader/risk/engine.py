"""Trading-system risk engine.

Only system-level limits are implemented (SPAC section 8). Strategy-specific
risk preference is intentionally out of scope.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from crypto_trader.domain.enums import ExecutionDecision
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import Account, OrderIntent, Position, RiskDecision, SignalIntent
from crypto_trader.domain.money import D, format_decimal
from crypto_trader.exposure.service import ExposureService, InstrumentExposureSpec
from crypto_trader.risk.kill_switch import KillSwitch


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
        metadata = getattr(intent, "metadata", {})
        reduce_only = metadata.get("reduce_only") is True
        current_position = positions.get(intent.symbol)
        if reduce_only:
            if current_position is None or current_position.quantity == 0:
                return fail("REDUCE_ONLY_NO_POSITION")
            expected_side = (
                "SELL" if current_position.quantity > 0 else "BUY"
            )
            if intent.side.value != expected_side:
                return fail("REDUCE_ONLY_DIRECTION_REVERSAL")
            if qty > abs(current_position.quantity):
                return fail("REDUCE_ONLY_CROSSES_ZERO")
            checks["reduce_only"] = True
        contract_size = D(str(getattr(intent, "metadata", {}).get("contract_size", "1")))
        contract_multiplier = D(
            str(getattr(intent, "metadata", {}).get("contract_multiplier", "1"))
        )
        exposure = ExposureService.calculate(
            quantity=qty,
            price=price,
            spec=InstrumentExposureSpec(
                instrument_type=str(getattr(intent, "metadata", {}).get("instrument_type", "SPOT")),
                contract_size=contract_size,
                contract_multiplier=contract_multiplier,
            ),
            side="LONG" if intent.side.value == "BUY" else "SHORT",
        )
        notional = exposure.gross_notional
        if getattr(intent, "quote_order_qty", None) is not None:
            notional = D(intent.quote_order_qty)

        if notional > self.config.max_order_notional:
            approved_quantity = self.config.max_order_notional / (
                price * contract_size * contract_multiplier
            )
            if approved_quantity <= 0:
                return fail("MAX_ORDER_NOTIONAL")
            checks.update(
                {
                    "max_order_notional": False,
                    "original_quantity": str(qty),
                    "approved_quantity": format_decimal(approved_quantity),
                    "original_notional": str(notional),
                    "approved_notional": str(self.config.max_order_notional),
                    "supporting_risk_evidence": "MAX_ORDER_NOTIONAL",
                    "contrary_risk_evidence": "requested order exceeds configured limit",
                }
            )
            return RiskDecision(
                risk_decision_id=new_id("risk"),
                order_id=order_id,
                client_order_id=client_order_id,
                symbol=intent.symbol,
                side=intent.side,
                decision=ExecutionDecision.SCALE_DOWN,
                reason="MAX_ORDER_NOTIONAL",
                checks=checks,
                timestamp=now,
                run_id=run_id,
            )
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

        cash = account.equity
        existing_notional = sum((abs(p.cost_basis) for p in positions.values()), Decimal("0"))
        current_symbol = positions.get(intent.symbol)
        current_symbol_notional = abs(current_symbol.cost_basis) if current_symbol else Decimal("0")
        symbol_notional = (
            max(current_symbol_notional - notional, Decimal("0"))
            if reduce_only
            else current_symbol_notional + notional
        )

        if symbol_notional > self.config.max_symbol_exposure:
            return fail("MAX_SYMBOL_EXPOSURE")
        checks["max_symbol_exposure"] = True

        projected_exposure = (
            max(existing_notional - notional, Decimal("0"))
            if reduce_only
            else existing_notional + notional
        )
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
