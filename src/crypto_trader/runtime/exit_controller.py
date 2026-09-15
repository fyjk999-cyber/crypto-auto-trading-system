"""Deterministic exit control for the canonical runtime (Low-Risk V2 Phase 4).

Hosts the already-tested deterministic protections and turns them into a
single ordered list of reduce-only intents the existing ``TradingEngine`` can
execute through the canonical ``live_llm_position`` path:

  1 Risk Hard Exit / L1 escalation   (authority RISK_HARD_EXIT)
  2 Fast Profit Protection           (authority FAST_PROFIT_PROTECTION)
  3 Active Base Exit                 (authority ACTIVE_BASE_EXIT)

Every reduce intent is reserved through the canonical ``ExitCoordinator``
before it is returned, so ``TotalReduceQty <= factual_qty`` holds across all
exit mechanisms. The controller never opens/adds/hedges/reverses and never
submits an order itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.enums import OrderSide
from crypto_trader.execution.base_exit import BaseExitRegistry, StaleBaseExitError
from crypto_trader.execution.exit_coordinator import ExitCoordinator, ExitPriority
from crypto_trader.factors.expert.context import AllInCostEstimate
from crypto_trader.llm_chief.invocation import (
    MaterialEvent,
    ReassessmentInvocationManager,
)
from crypto_trader.market_data.state import MarketState
from crypto_trader.risk.fast_profit import FastProfitConfig, evaluate_fast_profit
from crypto_trader.risk.risk_levels import (
    PositionRiskEpisode,
    PositionRiskMonitor,
    RiskLevel,
)


@dataclass(slots=True)
class DeterministicExitIntent:
    leg_id: str
    symbol: str
    side: str  # leg direction LONG | SHORT
    quantity: Decimal
    exit_pct: float
    priority: ExitPriority
    reason_code: str
    authority: str
    state_version: str
    reservation_request_id: str | None = None
    requires_llm_reassessment: bool = False
    is_new_risk: bool = False
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "leg_id": self.leg_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": str(self.quantity),
            "exit_pct": self.exit_pct,
            "priority": self.priority.name,
            "reason_code": self.reason_code,
            "authority": self.authority,
            "state_version": self.state_version,
            "reservation_request_id": self.reservation_request_id,
            "requires_llm_reassessment": self.requires_llm_reassessment,
            "is_new_risk": self.is_new_risk,
            "detail": dict(self.detail),
        }


@dataclass(slots=True)
class ControlledLeg:
    leg_id: str
    symbol: str
    side: str
    entry_price: Decimal
    state_version: str
    plan_version: int = 1
    risk_episode: PositionRiskEpisode | None = None


class DeterministicExitController:
    def __init__(
        self,
        *,
        coordinator: ExitCoordinator | None = None,
        base_exits: BaseExitRegistry | None = None,
        risk_monitor: PositionRiskMonitor | None = None,
        invocation: ReassessmentInvocationManager | None = None,
        costs: AllInCostEstimate | None = None,
        fast_profit_config: FastProfitConfig | None = None,
    ) -> None:
        self.coordinator = coordinator or ExitCoordinator()
        self.base_exits = base_exits or BaseExitRegistry()
        self.risk_monitor = risk_monitor or PositionRiskMonitor()
        self.invocation = invocation or ReassessmentInvocationManager()
        self.costs = costs or AllInCostEstimate()
        self.fast_profit_config = fast_profit_config or FastProfitConfig()
        self.legs: dict[str, ControlledLeg] = {}
        self.rejected_intents: list[dict] = []

    # ------------------------------------------------------------------- legs
    def ensure_leg(
        self,
        *,
        leg_id: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        entry_price: Decimal,
        state_version: str,
        plan_version: int = 1,
        base_exit: dict | None = None,
        exposure_usd: Decimal = Decimal("0"),
        equity_usd: Decimal = Decimal("1"),
        leverage: Decimal = Decimal("1"),
        notional_usd: Decimal = Decimal("0"),
        unrealized_pnl_pct: float = 0.0,
    ) -> ControlledLeg:
        side = side.upper()
        leg = self.legs.get(leg_id)
        if leg is None:
            leg = ControlledLeg(
                leg_id=leg_id,
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                state_version=state_version,
                plan_version=plan_version,
                risk_episode=PositionRiskEpisode(
                    leg_id=leg_id, symbol=symbol, side=side, entry_price=entry_price
                ),
            )
            self.legs[leg_id] = leg
            self.coordinator.register_leg(
                leg_id, symbol=symbol, side=side, quantity=quantity, state_version=state_version
            )
            self.invocation.register(
                leg_id,
                symbol=symbol,
                state_version=state_version,
                exposure_usd=exposure_usd,
                equity_usd=equity_usd,
                leverage=leverage,
                notional_usd=notional_usd,
                unrealized_pnl_pct=unrealized_pnl_pct,
            )
        else:
            leg.state_version = state_version
            leg.plan_version = plan_version
            self.coordinator.set_factual_qty(leg_id, quantity, state_version=state_version)
        if quantity <= 0:
            self.base_exits.mark_filled(leg_id)
            return leg
        if leg_id in self.base_exits.closed_legs:
            self.base_exits.reopen_leg(leg_id)
        if base_exit and self.base_exits.active(leg_id) is None:
            try:
                version = self.base_exits.stage(
                    leg_id,
                    plan_version=plan_version,
                    exit_type=str(base_exit.get("type", "PRICE")),
                    trigger=str(base_exit.get("trigger", "")),
                    size_pct=float(base_exit.get("size_pct", 100.0) or 100.0),
                    reason_code=str(base_exit.get("reason_code", "BASE_EXIT")),
                    based_on_state_version=state_version,
                )
                self.base_exits.activate(version.version_id, factual_state_version=state_version)
            except (StaleBaseExitError, ValueError):
                # Fail-safe: an unregisterable exit never blocks the position,
                # but the old active exit (if any) remains authoritative.
                pass
        self.invocation.update_position(
            leg_id,
            state_version=state_version,
            exposure_usd=exposure_usd,
            equity_usd=equity_usd,
            leverage=leverage,
            notional_usd=notional_usd,
            unrealized_pnl_pct=unrealized_pnl_pct,
        )
        return leg

    def observe_fill(
        self, leg_id: str, signed_qty: Decimal, *, state_version: str | None = None
    ) -> None:
        leg = self.legs.get(leg_id)
        if leg is None:
            return
        self.coordinator.apply_fill(leg_id, signed_qty, state_version=state_version)
        if state_version:
            leg.state_version = state_version
        if self.coordinator.legs[leg_id].factual_qty == 0:
            self.base_exits.mark_filled(leg_id)

    # ---------------------------------------------------------------- evaluate
    def evaluate(
        self,
        leg_id: str,
        *,
        price: Decimal,
        now: datetime | None = None,
        state: MarketState | None = None,
        account_drawdown_pct: float = 0.0,
        atr_pct: float = 0.0,
        rvol: float | None = None,
        price_rejection: bool = False,
    ) -> list[DeterministicExitIntent]:
        moment = now or datetime.now(UTC)
        leg = self.legs.get(leg_id)
        if leg is None or self.coordinator.legs[leg_id].factual_qty <= 0:
            return []
        factual = self.coordinator.legs[leg_id].factual_qty
        intents: list[DeterministicExitIntent] = []

        # 1. Risk hard exit / L1 (deterministic protection outranks everything).
        risk_decision = self.risk_monitor.evaluate(
            leg.risk_episode,  # type: ignore[arg-type]
            mark_price=price,
            account_drawdown_pct=account_drawdown_pct,
            now=moment,
        )
        if risk_decision.force_close or risk_decision.level == RiskLevel.L2:
            intent = self._reserve(
                leg,
                factual=factual,
                exit_pct=100.0,
                priority=ExitPriority.RISK_HARD_EXIT,
                reason_code="RISK_HARD_EXIT",
                authority="RISK_HARD_EXIT",
                detail={"risk": risk_decision.as_dict()},
            )
            if intent is not None:
                intents.append(intent)
            return intents
        if risk_decision.level == RiskLevel.L1:
            invocation = self.invocation.decide(
                leg_id,
                now=moment,
                price=price,
                event=MaterialEvent(
                    kind="RISK_L1", severity=0.9, novelty=0.9, urgency=0.9, at=moment
                ),
            )
            if invocation.should_invoke:
                intents.append(
                    DeterministicExitIntent(
                        leg_id=leg_id,
                        symbol=leg.symbol,
                        side=leg.side,
                        quantity=Decimal("0"),
                        exit_pct=0.0,
                        priority=ExitPriority.LLM_REDUCE_CLOSE,
                        reason_code="RISK_L1_LLM_REASSESSMENT",
                        authority="RISK_L1",
                        state_version=leg.state_version,
                        requires_llm_reassessment=True,
                        detail={
                            "risk": risk_decision.as_dict(),
                            "invocation": invocation.as_dict(),
                        },
                    )
                )

        # 2. Fast Profit Protection.
        fast = evaluate_fast_profit(
            symbol=leg.symbol,
            side=leg.side,
            quantity=factual,
            entry_price=leg.entry_price,
            mark_price=price,
            atr_pct=atr_pct,
            state=state,
            costs=self.costs,
            price_rejection=price_rejection,
            rvol=rvol,
            config=self.fast_profit_config,
        )
        if fast.trigger:
            intent = self._reserve(
                leg,
                factual=factual,
                exit_pct=fast.exit_pct,
                priority=ExitPriority.FAST_PROFIT,
                reason_code="FAST_PROFIT_PROTECTION",
                authority="FAST_PROFIT_PROTECTION",
                detail={"fast_profit": fast.as_dict()},
            )
            if intent is not None:
                intents.append(intent)
                return intents

        # 3. Active Base Exit.
        base = self.base_exits.evaluate(leg_id, now=moment, price=price)
        if base.due:
            intent = self._reserve(
                leg,
                factual=factual,
                exit_pct=base.exit_pct,
                priority=ExitPriority.ACTIVE_BASE_EXIT,
                reason_code=base.reason_code,
                authority="ACTIVE_BASE_EXIT",
                detail={"base_exit": base.as_dict()},
            )
            if intent is not None:
                intents.append(intent)
        return intents

    def confirm_fill(self, request_id: str, filled_qty: Decimal) -> None:
        self.coordinator.confirm_fill(request_id, filled_qty)

    def cancel(self, request_id: str, reason: str = "CANCELLED") -> None:
        self.coordinator.cancel(request_id, reason)

    def snapshot(self, leg_id: str) -> dict:
        leg = self.legs.get(leg_id)
        if leg is None:
            return {"leg_id": leg_id, "registered": False}
        return {
            "leg_id": leg_id,
            "registered": True,
            "side": leg.side,
            "state_version": leg.state_version,
            "plan_version": leg.plan_version,
            "risk_episode": leg.risk_episode.as_dict() if leg.risk_episode else None,
            "coordinator": self.coordinator.snapshot(leg_id),
            "base_exit": (
                self.base_exits.active(leg_id).as_dict() if self.base_exits.active(leg_id) else None
            ),
        }

    # --------------------------------------------------------------- internals
    def _reserve(
        self,
        leg: ControlledLeg,
        *,
        factual: Decimal,
        exit_pct: float,
        priority: ExitPriority,
        reason_code: str,
        authority: str,
        detail: dict,
    ) -> DeterministicExitIntent | None:
        quantity = factual * Decimal(str(exit_pct / 100.0))
        side = "SELL" if leg.side == "LONG" else "BUY"
        result = self.coordinator.submit(
            leg_id=leg.leg_id,
            side=OrderSide(side),
            quantity=quantity,
            priority=priority,
            reason_code=reason_code,
            authority=authority,
            state_version=leg.state_version,
        )
        if not result.accepted or result.request is None or result.approved_qty <= 0:
            self.rejected_intents.append(
                {
                    "leg_id": leg.leg_id,
                    "reason_code": reason_code,
                    "reasons": list(result.reason_codes),
                }
            )
            return None
        return DeterministicExitIntent(
            leg_id=leg.leg_id,
            symbol=leg.symbol,
            side=leg.side,
            quantity=result.approved_qty,
            exit_pct=exit_pct,
            priority=priority,
            reason_code=reason_code,
            authority=authority,
            state_version=leg.state_version,
            reservation_request_id=result.request.request_id,
            detail=detail,
        )
