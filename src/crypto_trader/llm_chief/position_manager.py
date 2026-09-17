"""Canonical OPEN-position orchestration owned by the same ChiefTraderEngine."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import Position, SignalIntent
from crypto_trader.execution.base_exit import StaleBaseExitError
from crypto_trader.execution.hedge_legs import HedgeLegContract, LegKind, validate_hedge_leg
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.context_loader import ChiefContextLoader
from crypto_trader.llm_chief.decision import OpenAction, PositionState
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.fresh_context import build_rebuild_kwargs
from crypto_trader.llm_chief.state_version import position_state_version
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
        attempt_clock: Callable[[], datetime] | None = None,
        expert_engine=None,
        fresh_context_provider=None,
        hedge_planner=None,
        leg_service=None,
        leg_registry=None,
        base_exit_registry=None,
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
        self.attempt_clock = attempt_clock or (lambda: datetime.now(UTC))
        # One horizon reassessment per factual state version (dedup/novelty).
        self._last_horizon_wake_state: dict[str, str] = {}
        # Low-Risk V2 Phase 2: 25-model factual evidence package (evidence only).
        self.expert_engine = expert_engine
        self.fresh_context_provider = fresh_context_provider
        # Low-Risk V2 Phase 4D: hedge/reverse legs are NEW RISK with their own
        # independent contract, plan and durable leg row.
        self.hedge_planner = hedge_planner
        self.leg_service = leg_service
        self.leg_registry = leg_registry
        self.base_exit_registry = base_exit_registry
        self._last_review_attempt: dict[str, datetime] = {}

    async def _hedge_leg_signal(self, decision, plan, position: Position, ctx: StrategyContext):
        """Build the independent opposite leg through the canonical plan path."""
        if self.hedge_planner is None:
            return None
        side = "SHORT" if position.quantity > 0 else "LONG"
        contract = HedgeLegContract(
            leg_id=new_id("leg"),
            symbol=position.symbol,
            side=side,
            kind=LegKind.HEDGE if decision.action == OpenAction.HEDGE else LegKind.REVERSE,
            strategy=decision.strategy
            or (decision.strategy_selected[0] if decision.strategy_selected else "live_llm"),
            thesis=decision.thesis or "",
            base_exit=decision.base_exit.model_dump(mode="json") if decision.base_exit else None,
            invalidation=decision.thesis_invalidation or None,
            evidence_families=[str(ref) for ref in decision.supporting_evidence],
            reason=decision.thesis or "",
            reverse_of=plan.trade_plan_id,
        )
        existing = []
        if self.leg_service is not None:
            existing = await self.leg_service.list_for_symbol(position.symbol)
        elif self.leg_registry is not None:
            existing = self.leg_registry.legs_for(position.symbol)
        validation = validate_hedge_leg(contract, existing)
        if not validation.allowed:
            await self.audit.log(
                "HEDGE_LEG_REJECTED",
                target=decision.decision_id,
                actor="live_llm",
                run_id=ctx.run_id,
                after={"leg_id": contract.leg_id, "violations": validation.violations},
            )
            return None
        hedge_plan, signal = await self.hedge_planner.create_hedge_signal(
            decision,
            hedge_contract=contract,
            existing_legs=existing,
            current_position_side="LONG" if position.quantity > 0 else "SHORT",
        )
        if hedge_plan is None or signal is None:
            return None
        if self.leg_service is not None:
            await self.leg_service.register(
                contract,
                trade_plan_id=hedge_plan.trade_plan_id,
                decision_id=decision.decision_id,
            )
        elif self.leg_registry is not None:
            self.leg_registry.register(contract)
        await self.audit.log(
            "HEDGE_LEG_REGISTERED",
            target=contract.leg_id,
            actor="live_llm",
            run_id=ctx.run_id,
            after={
                "side": contract.side,
                "kind": contract.kind.value,
                "trade_plan_id": hedge_plan.trade_plan_id,
            },
        )
        return signal

    def horizon_wake_due(self, position, plan, now) -> bool:
        """Horizon wake only once per factual state version (dedup/novelty)."""
        if not self.expected_holding_horizon_reached(position, plan, now):
            return False
        current = position_state_version(position, plan)
        return self._last_horizon_wake_state.get(position.symbol) != current

    async def _modify_exit(self, decision, plan, position, ctx, state_version: str):
        """Versioned Base Exit replacement: validate -> stage -> atomic activate.

        Never emits an order and never creates a protection gap: the currently
        active Base Exit remains authoritative until the new version is
        validated and atomically activated.
        """
        if decision.base_exit is None:
            await self.audit.log(
                "MODIFY_EXIT_MISSING_BASE_EXIT",
                target=decision.decision_id,
                actor="live_llm",
                run_id=ctx.run_id,
                after={"is_order": False},
            )
            return None
        if self.base_exit_registry is None:
            await self.audit.log(
                "MODIFY_EXIT_UNAVAILABLE",
                target=decision.decision_id,
                actor="live_llm",
                run_id=ctx.run_id,
                after={
                    "required_path": "BASE_EXIT_VALIDATE_PERSIST_ATOMIC_ACTIVATE",
                    "is_order": False,
                },
            )
            return None
        if decision.based_on_state_version not in (None, state_version):
            await self.audit.log(
                "MODIFY_EXIT_STALE_REJECTED",
                target=decision.decision_id,
                actor="live_llm",
                run_id=ctx.run_id,
                after={
                    "based_on_state_version": decision.based_on_state_version,
                    "current_state_version": state_version,
                    "is_order": False,
                },
            )
            return None
        new_exit = decision.base_exit.model_dump(mode="json")
        try:
            version = self.base_exit_registry.stage(
                plan.trade_plan_id,
                plan_version=int(getattr(plan, "plan_version", 1)) + 1,
                exit_type=str(new_exit.get("type", "PRICE")),
                trigger=str(new_exit.get("trigger", "")),
                size_pct=float(new_exit.get("size_pct", 100.0) or 100.0),
                reason_code=str(new_exit.get("reason_code", "BASE_EXIT")),
                based_on_state_version=state_version,
            )
            activated = self.base_exit_registry.activate(
                version.version_id, factual_state_version=state_version
            )
        except (StaleBaseExitError, ValueError) as exc:
            await self.audit.log(
                "MODIFY_EXIT_STALE_REJECTED",
                target=decision.decision_id,
                actor="live_llm",
                run_id=ctx.run_id,
                after={"reason": str(exc), "is_order": False},
            )
            return None
        updated = await self.plans.replace_base_exit(
            plan.trade_plan_id,
            base_exit=new_exit,
            expected_plan_version=int(getattr(plan, "plan_version", 1)),
        )
        if updated is None:
            await self.audit.log(
                "MODIFY_EXIT_PLAN_CONFLICT",
                target=decision.decision_id,
                actor="live_llm",
                run_id=ctx.run_id,
                after={
                    "version_id": version.version_id,
                    "reason": "plan_version_changed",
                    "is_order": False,
                },
            )
            return None
        await self.audit.log(
            "MODIFY_EXIT_ACTIVATED",
            target=decision.decision_id,
            actor="live_llm",
            run_id=ctx.run_id,
            after={
                "version_id": activated.version_id,
                "trade_plan_id": plan.trade_plan_id,
                "new_plan_version": updated.plan_version,
                "trigger": activated.trigger,
                "size_pct": activated.size_pct,
                "based_on_state_version": state_version,
                "is_order": False,
            },
        )
        return None

    def expected_holding_horizon_reached(self, position, plan, now) -> bool:
        """Expected holding horizon is an informational reassessment trigger.

        Low-Risk V2 has NO hard maximum holding time: reaching the expectation
        wakes the Core LLM with fresh factual state and never forces an exit.
        """
        horizon = getattr(plan, "max_holding_time_seconds", None)
        if horizon is None or float(horizon) <= 0:
            return False
        opened_at = _utc(plan.opened_at or position.updated_at or now)
        return (now - opened_at).total_seconds() >= float(horizon)

    def _rebuild_kwargs(self, position: Position, ctx: StrategyContext) -> dict:
        """Build the fresh-state rebuilder passed to the Core LLM on failover.

        The provider must re-fetch current position/fills/pending/plan/price/
        evidence; returning None raises so the router fails safe instead of
        replaying the stale prompt.
        """
        return build_rebuild_kwargs(
            chief=self.chief,
            provider=self.fresh_context_provider,
            symbol=position.symbol,
            strategy_ctx=ctx,
        )

    def review_priority(self, position: Position) -> tuple[int, datetime, str]:
        """Never-reviewed positions first, then the position waiting longest."""
        last = self._last_review_attempt.get(position.symbol)
        return (
            0 if last is None else 1,
            last or datetime.min.replace(tzinfo=UTC),
            position.symbol,
        )

    async def review(
        self, ctx: StrategyContext, position: Position, *, force: bool = False
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
        state_version_before = position_state_version(position, plan)
        horizon_reached = self.expected_holding_horizon_reached(position, plan, now)
        last_attempt = self._last_review_attempt.get(position.symbol)
        if not force and last_attempt is not None and now - last_attempt < self.review_cooldown:
            # Ordinary cadence. A Risk L1 material wake bypasses this cooldown.
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
            "state_version": state_version_before,
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
        chief_ctx.state_version = state_version_before
        if self.context_loader is not None:
            chief_ctx = await self.context_loader.enrich(chief_ctx)
        if self.expert_engine is not None:
            try:
                package = await self.expert_engine.evaluate(symbol=position.symbol)
            except Exception:
                package = None
            if package is not None:
                chief_ctx.model_evidence = package.as_llm_context()
        memory_refs = list(chief_ctx.memory_refs)
        research_refs = list(chief_ctx.research_refs)
        episode_refs = list(chief_ctx.episode_refs)
        try:
            if self.tool_chief is None:
                decision = await self.chief.decide(chief_ctx, **self._rebuild_kwargs(position, ctx))
            else:
                decision, package = await self.tool_chief.decide(
                    chief_ctx,
                    tool_context={"strategy_context": ctx},
                    now=now,
                    **self._rebuild_kwargs(position, ctx),
                )
                if package is not None:
                    evidence = {
                        "source_refs": package.source_refs,
                        "selected_tools": package.selected_tools,
                    }
                    memory_refs = package.refs_with_prefix("memory:")
                    research_refs = package.refs_with_prefix("research:")
                    episode_refs = package.refs_with_prefix("episode:")
        finally:
            completed_at = _utc(self.attempt_clock())
            self._last_review_attempt[position.symbol] = max(now, completed_at)
        if decision.based_on_state_version is None:
            # Bind provenance only when the provider did not state one. An
            # explicit (wrong) claim is preserved so MODIFY_EXIT validation can
            # reject a stale replacement instead of silently re-basing it.
            decision = decision.model_copy(update={"based_on_state_version": state_version_before})
        state_version_after = position_state_version(position, plan)
        await self.decisions.save(
            decision,
            run_id=ctx.run_id,
            prompt_version=self.version,
            tool_refs=[str(ref) for ref in evidence.get("source_refs", [])],
            memory_refs=memory_refs,
            research_refs=research_refs,
            episode_refs=episode_refs,
            parent_decision_id=plan.decision_id,
            position_context=position_context,
            news_context=chief_ctx.news_context,
            state_version=chief_ctx.state_version,
        )
        if state_version_after != state_version_before:
            # Factual state moved while the LLM was thinking (Base Exit fill,
            # partial reduction, position close, leg change, UNKNOWN...).
            # The decision is stale: no new risk, no exit replacement, no order.
            if horizon_reached:
                self._last_horizon_wake_state[position.symbol] = state_version_after
            await self.audit.log(
                "STALE_LLM_RESPONSE_REJECTED",
                target=decision.decision_id,
                actor="live_llm",
                run_id=ctx.run_id,
                after={
                    "action": decision.action.value,
                    "based_on_state_version": state_version_before,
                    "current_state_version": state_version_after,
                    "trade_plan_id": plan.trade_plan_id,
                    "is_order": False,
                },
            )
            return None
        await self.decisions.link_trade_plan(decision.decision_id, plan.trade_plan_id)
        if horizon_reached:
            # Time threshold -> high-priority Core LLM reassessment. The trigger
            # itself is never an order; Base Exit / Fast Profit / Risk hard exit
            # remain active independently while the LLM thinks.
            await self.audit.log(
                "TIME_THRESHOLD_REASSESSMENT",
                target=decision.decision_id,
                actor="live_llm",
                run_id=ctx.run_id,
                after={
                    "trigger": "EXPECTED_HOLDING_HORIZON_REACHED",
                    "authority": "REASSESSMENT_ONLY",
                    "is_order": False,
                    "trade_plan_id": plan.trade_plan_id,
                    "plan_version": getattr(plan, "plan_version", None),
                    "based_on_state_version": plan.based_on_state_version,
                    "time_in_trade_seconds": position_context["time_in_trade_seconds"],
                    "expected_holding_period": plan.expected_holding_period,
                    "max_holding_time_seconds": plan.max_holding_time_seconds,
                },
            )
        await self.plans.link_position_decision(
            plan.trade_plan_id,
            decision.decision_id,
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
                "expected_holding_horizon_reached": horizon_reached,
                "time_threshold_reassessment_only": True,
            },
        )
        if horizon_reached:
            # One horizon reassessment per factual state version.
            self._last_horizon_wake_state[position.symbol] = state_version_before
        if decision.action in {OpenAction.HOLD, OpenAction.FAIL_CLOSED}:
            if horizon_reached:
                await self.audit.log(
                    "EXPECTED_HOLDING_NO_FORCED_EXIT",
                    target=decision.decision_id,
                    actor="live_llm",
                    run_id=ctx.run_id,
                    after={
                        "action": decision.action.value,
                        "reason": "TIME_THRESHOLD_IS_REASSESSMENT_ONLY",
                        "is_order": False,
                    },
                )
            return None
        if decision.action == OpenAction.ADD:
            # ADD is NEW RISK (Core-LLM child with its own TradePlan/Base
            # Exit). It must never be transformed into a reduce-only order on
            # the original leg.
            await self.audit.log(
                "ADD_REQUIRES_CORE_NEW_RISK_PATH",
                target=decision.decision_id,
                actor="live_llm",
                run_id=ctx.run_id,
                after={
                    "required_path": "CORE_LLM_TRADEPLAN_EXECUTION",
                    "is_order": False,
                    "expected_holding_horizon_reached": horizon_reached,
                },
            )
            return None
        if decision.action == OpenAction.MODIFY_EXIT:
            return await self._modify_exit(decision, plan, position, ctx, state_version_before)
        if decision.action in {OpenAction.HEDGE, OpenAction.REVERSE}:
            # Low-Risk V2: a hedge/reverse is NEW RISK with its own strategy,
            # thesis, model-family evidence, Base Exit and invalidation. It must
            # travel the Core-LLM -> TradePlan -> ExecutionAuthority path; it must
            # never be silently converted into a reduce-only order on the legacy
            # leg ("reduce the original loss" is not a legal hedge reason).
            signal = await self._hedge_leg_signal(decision, plan, position, ctx)
            if signal is None:
                await self.audit.log(
                    "HEDGE_REVERSE_REQUIRES_CORE_NEW_RISK",
                    target=decision.decision_id,
                    actor="live_llm",
                    run_id=ctx.run_id,
                    after={
                        "action": decision.action.value,
                        "symbol": position.symbol,
                        "trade_plan_id": plan.trade_plan_id,
                        "required_path": "CORE_LLM_TRADEPLAN_EXECUTION",
                    },
                )
            return signal

        full_reduce = decision.action in {OpenAction.EXIT, OpenAction.CLOSE}
        quantity = (
            abs(position.quantity) if full_reduce else Decimal(str(decision.position_size_request))
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
            reason=decision.thesis or decision.action.value,
            metadata={
                "trade_plan_id": plan.trade_plan_id,
                "decision_id": decision.decision_id,
                "entry_decision_id": plan.decision_id,
                "direction": plan.direction,
                "lifecycle_action": decision.action.value,
                "reduce_only": True,
                "expected_holding_horizon_reached": horizon_reached,
                "time_threshold_reassessment_only": True,
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


def _market_snapshot(ctx: StrategyContext, now: datetime, mark: Decimal) -> dict[str, Any]:
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
