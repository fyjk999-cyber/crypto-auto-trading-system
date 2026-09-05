"""Canonical OPEN-position orchestration owned by the same ChiefTraderEngine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import Position, SignalIntent
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.context_loader import ChiefContextLoader
from crypto_trader.llm_chief.decision import OpenAction, PositionState
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.tool_orchestrator import ToolDrivenChiefTrader
from crypto_trader.observability.audit import AuditService
from crypto_trader.strategy.base import StrategyContext
from crypto_trader.trade_plan.service import TradePlanService


class LiveLLMPositionManager:
    """Collect context, call ChiefTrader, persist, and translate HOLD/REDUCE/EXIT."""

    name = "live_llm_position"
    version = "canonical-open-1.0.0"

    def __init__(
        self,
        *,
        chief: ChiefTraderEngine,
        evidence_engine: Any,
        decisions: LLMDecisionStore,
        plans: TradePlanService,
        audit: AuditService,
        risk_summary: dict[str, Any] | None = None,
        review_cooldown_seconds: float = 30.0,
        tool_chief: ToolDrivenChiefTrader | None = None,
        context_loader: ChiefContextLoader | None = None,
    ) -> None:
        self.chief = chief
        self.evidence_engine = evidence_engine
        self.decisions = decisions
        self.plans = plans
        self.audit = audit
        self.risk_summary = risk_summary or {}
        self.review_cooldown = timedelta(seconds=max(1.0, review_cooldown_seconds))
        self.tool_chief = tool_chief
        self.context_loader = context_loader
        self._last_review_attempt: dict[str, datetime] = {}

    async def review(
        self, ctx: StrategyContext, position: Position
    ) -> SignalIntent | None:
        if position.quantity == 0:
            return None
        plan = await self.plans.get_active_for_symbol(position.symbol)
        if plan is None:
            await self.audit.log(
                "OPEN_POSITION_WITHOUT_ACTIVE_TRADEPLAN",
                target=position.symbol,
                run_id=ctx.run_id,
            )
            return None

        now = ctx.clock_time.astimezone(UTC)
        last_attempt = self._last_review_attempt.get(position.symbol)
        if last_attempt is not None and now - last_attempt < self.review_cooldown:
            return None

        evidence = (
            self.evidence_engine.analyze_evidence(ctx)
            if self.tool_chief is None
            else {"regime": "UNKNOWN", "source_refs": []}
        )
        mark = ctx.mark_price or ctx.book.mid_price() or position.avg_entry_price or Decimal("0")
        entry = position.avg_entry_price or Decimal("0")
        # Keep OPEN-decision PnL context on the same linear-contract semantics
        # used by fills, ledger projections, sizing, Risk, and exposure APIs.
        unrealized = (
            (mark - entry)
            * position.quantity
            * position.contract_size
            * position.contract_multiplier
        )
        opened_at = _utc(plan.opened_at or position.updated_at or now)
        position_context = {
            "symbol": position.symbol,
            "side": "LONG" if position.quantity > 0 else "SHORT",
            "quantity": str(abs(position.quantity)),
            "signed_quantity": str(position.quantity),
            "entry_price": str(entry),
            "mark_price": str(mark),
            "realized_pnl": str(position.realized_pnl),
            "unrealized_pnl": str(unrealized),
            "time_in_trade_seconds": max(0.0, (now - opened_at).total_seconds()),
            "trade_plan_id": plan.trade_plan_id,
            "entry_decision_id": plan.decision_id,
            "original_thesis": plan.thesis,
            "invalidation_conditions": plan.invalidation_conditions,
            "reduce_conditions": plan.reduce_conditions,
            "exit_conditions": plan.exit_conditions,
            "expected_holding_period": plan.expected_holding_period,
            "max_holding_time_seconds": plan.max_holding_time_seconds,
        }
        chief_ctx = ChiefTraderContext(
            symbol=position.symbol,
            market_snapshot=_market_snapshot(ctx, now, mark),
            regime=_regime(evidence),
            quant_evidence=[evidence],
            portfolio_state={
                "account": ctx.account.model_dump(mode="json"),
                "position": position.model_dump(mode="json"),
            },
            risk_summary=self.risk_summary,
            position_state=PositionState.OPEN,
            position_context=position_context,
        )
        if self.context_loader is not None:
            chief_ctx = await self.context_loader.enrich(chief_ctx)
        self._last_review_attempt[position.symbol] = now
        if self.tool_chief is None:
            decision = await self.chief.decide(chief_ctx)
        else:
            decision, package = await self.tool_chief.decide(
                chief_ctx,
                tool_context={"strategy_context": ctx},
                now=now,
            )
            if package is not None:
                evidence = {
                    "source_refs": package.source_refs,
                    "selected_tools": package.selected_tools,
                }
        await self.decisions.save(
            decision,
            run_id=ctx.run_id,
            prompt_version=self.version,
            tool_refs=[str(ref) for ref in evidence.get("source_refs", [])],
            memory_refs=chief_ctx.memory_refs,
            research_refs=chief_ctx.research_refs,
            episode_refs=chief_ctx.episode_refs,
            parent_decision_id=plan.decision_id,
            position_context=position_context,
        )
        await self.decisions.link_trade_plan(decision.decision_id, plan.trade_plan_id)
        max_hold_reached = (
            position_context["time_in_trade_seconds"] >= plan.max_holding_time_seconds
        )
        time_stop = max_hold_reached and decision.action in {
            OpenAction.HOLD,
            OpenAction.FAIL_CLOSED,
        }
        await self.plans.link_position_decision(
            plan.trade_plan_id,
            decision.decision_id,
            is_exit=decision.action == OpenAction.EXIT or time_stop,
        )
        await self.audit.log(
            "LIVE_LLM_POSITION_DECISION",
            target=decision.decision_id,
            actor="live_llm",
            run_id=ctx.run_id,
            after={
                "action": decision.action.value,
                "symbol": position.symbol,
                "trade_plan_id": plan.trade_plan_id,
                "decision_authority": "LIVE_LLM_ONLY",
            },
        )
        if decision.action in {OpenAction.HOLD, OpenAction.FAIL_CLOSED} and not time_stop:
            return None

        quantity = (
            abs(position.quantity)
            if decision.action == OpenAction.EXIT or time_stop
            else Decimal(str(decision.position_size_request))
        )
        if quantity <= 0 or quantity > abs(position.quantity):
            await self.audit.log(
                "LIVE_LLM_POSITION_DECISION_INVALID",
                target=decision.decision_id,
                actor="live_llm",
                run_id=ctx.run_id,
                after={"reason": "reduction quantity outside current position"},
            )
            return None
        return SignalIntent(
            signal_id=new_id("position_decision"),
            strategy_id=self.name,
            symbol=position.symbol,
            side=OrderSide.SELL if position.quantity > 0 else OrderSide.BUY,
            quantity=quantity,
            reason=(
                "maximum holding time safety fallback"
                if time_stop
                else decision.thesis or decision.action.value
            ),
            metadata={
                "trade_plan_id": plan.trade_plan_id,
                "decision_id": decision.decision_id,
                "entry_decision_id": plan.decision_id,
                "lifecycle_action": (
                    "TIME_STOP_SAFETY_FALLBACK" if time_stop else decision.action.value
                ),
                "time_stop": time_stop,
                "reduce_only": True,
                "instrument_type": position.instrument_type,
                "contract_size": str(position.contract_size),
                "contract_multiplier": str(position.contract_multiplier),
            },
        )


def _regime(evidence: dict[str, Any]) -> str:
    raw = evidence.get("regime", "UNKNOWN")
    if isinstance(raw, dict):
        return str(raw.get("regime") or raw.get("value") or "UNKNOWN")
    return str(raw)


def _market_snapshot(
    ctx: StrategyContext, now: datetime, mark: Decimal
) -> dict[str, Any]:
    """Return the factual OKX state needed to reassess the entry thesis."""

    best_bid = ctx.book.best_bid()
    best_ask = ctx.book.best_ask()
    return {
        "symbol": ctx.symbol,
        "timestamp": now.isoformat(),
        "best_bid": str(best_bid.price) if best_bid is not None else None,
        "best_ask": str(best_ask.price) if best_ask is not None else None,
        "mark_price": str(mark),
        "index_price": str(ctx.index_price) if ctx.index_price is not None else None,
        "funding": str(ctx.funding) if ctx.funding is not None else None,
        "open_interest": str(ctx.oi) if ctx.oi is not None else None,
        "basis": str(ctx.basis) if ctx.basis is not None else None,
        "source": "OKX_PUBLIC",
        "instrument": (
            {
                "instrument_type": ctx.instrument.instrument_type,
                "contract_size": str(ctx.instrument.contract_size),
                "contract_multiplier": str(ctx.instrument.contract_multiplier),
            }
            if ctx.instrument is not None
            else None
        ),
    }


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
