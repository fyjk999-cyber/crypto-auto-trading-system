"""Translate validated Live-LLM decisions into durable, non-executing signals."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.models import SignalIntent
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.trade_plan.service import TradePlan, TradePlanService


class LiveLLMTradePlanner:
    """Creates a TradePlan before returning a SignalIntent; never calls execution."""

    def __init__(
        self,
        plans: TradePlanService,
        *,
        max_holding_time_seconds: float = 86400.0,
    ) -> None:
        self.plans = plans
        self.max_holding_time_seconds = max_holding_time_seconds

    async def create_entry_signal(
        self,
        decision: ChiefTraderDecision,
        *,
        limit_price: Decimal | None = None,
        quantity: Decimal | None = None,
        execution_metadata: dict | None = None,
    ) -> tuple[TradePlan | None, SignalIntent | None]:
        if decision.action not in {"LONG", "SHORT"}:
            return None, None
        quantity = quantity or Decimal(str(decision.position_size_request))
        if quantity <= 0 or not decision.thesis:
            raise ValueError("Live LLM entry decision requires positive size and thesis")
        plan = await self.plans.create(
            decision_id=decision.decision_id,
            symbol=decision.symbol,
            direction=decision.action,
            thesis=decision.thesis,
            requested_quantity=quantity,
            requested_leverage=Decimal(str(decision.leverage_request))
            if decision.leverage_request > 0
            else None,
            requested_exposure=(
                Decimal(str(decision.requested_exposure))
                if decision.requested_exposure is not None
                else None
            ),
            entry_conditions=[decision.entry_plan] if decision.entry_plan else [],
            invalidation_conditions=decision.invalidation_conditions,
            reduce_conditions=decision.reduce_conditions,
            exit_conditions=decision.exit_conditions,
            expected_holding_period=decision.expected_holding_period,
            max_holding_time_seconds=self.max_holding_time_seconds,
        )
        signal = SignalIntent(
            signal_id=decision.decision_id,
            strategy_id="live_llm",
            symbol=decision.symbol,
            side=OrderSide.BUY if decision.action == "LONG" else OrderSide.SELL,
            quantity=quantity,
            limit_price=limit_price,
            reason=decision.thesis,
            metadata={
                "trade_plan_id": plan.trade_plan_id,
                "decision_id": decision.decision_id,
                "direction": decision.action.value,
                "requested_leverage": str(decision.leverage_request),
                "instrument_type": "LINEAR_PERP",
                "contract_size": "1",
                "contract_multiplier": "1",
                **(execution_metadata or {}),
            },
        )
        await self.plans.link(plan.trade_plan_id, signal_id=signal.signal_id)
        return plan, signal
