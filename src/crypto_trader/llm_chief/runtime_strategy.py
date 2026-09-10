"""Canonical Live-LLM entry adapter.

Quant/factor/strategy engines are evidence providers only.  This adapter is the
only StrategyPlugin allowed to emit a new directional SignalIntent in the
official runtime: it gathers factual evidence, asks the ChiefTraderEngine for
the direction, durably audits that decision, then creates the TradePlan before
returning a signal to the existing Risk -> ExecutionAuthority pipeline.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from crypto_trader.alpha.ensemble import MultiStrategyAlpha
from crypto_trader.alpha.evidence_router import PerSymbolEvidenceRouter
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.context_loader import ChiefContextLoader
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.tool_orchestrator import ToolDrivenChiefTrader
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.context import build_opportunity_context
from crypto_trader.market_data.opportunity.scanner import (
    CANDIDATE_SOURCE_MARKET_OBSERVER,
)
from crypto_trader.observability.audit import AuditService
from crypto_trader.sizing.service import LiveEntrySizingService
from crypto_trader.strategy.base import StrategyContext, StrategyPlugin


class LiveLLMDecisionStrategy(StrategyPlugin):
    """Evidence -> Live LLM -> durable decision -> TradePlan -> SignalIntent.

    The wrapped quant engine never emits executable signals.  LLM failure or an
    invalid/non-directional decision fails closed to no entry.
    """

    name = "live_llm"
    version = "canonical-1.0.0"

    def __init__(
        self,
        *,
        evidence_engine: MultiStrategyAlpha,
        chief: ChiefTraderEngine,
        planner: LiveLLMTradePlanner,
        decisions: LLMDecisionStore,
        audit: AuditService,
        risk_summary: dict[str, Any] | None = None,
        retry_cooldown_seconds: float = 30.0,
        tool_chief: ToolDrivenChiefTrader | None = None,
        sizer: LiveEntrySizingService | None = None,
        context_loader: ChiefContextLoader | None = None,
        attempt_clock: Callable[[], datetime] | None = None,
        opportunity_board: OpportunityBoard | None = None,
        evidence_router: PerSymbolEvidenceRouter | None = None,
    ) -> None:
        self.evidence_engine = evidence_engine
        self.chief = chief
        self.planner = planner
        self.decisions = decisions
        self.audit = audit
        self.risk_summary = risk_summary or {}
        self.symbol = evidence_engine.symbol
        self.retry_cooldown = timedelta(seconds=max(1.0, retry_cooldown_seconds))
        self.tool_chief = tool_chief
        self.sizer = sizer
        self.context_loader = context_loader
        self.attempt_clock = attempt_clock or (lambda: datetime.now(UTC))
        # MASTER DIRECTIVE §10: agenda-driven multi-symbol review. The board
        # nominates; DeepSeek still owns every decision. Per-symbol attempt
        # cooldown replaces the single-symbol clock (same semantics).
        self.opportunity_board = opportunity_board
        self.evidence_router = evidence_router
        self._last_attempt_by_symbol: dict[str, datetime] = {}
        self._skip_until: dict[str, datetime] = {}
        # This is an attempt cooldown, not an entry cooldown.  Every provider
        # call consumes the interval, including NO_TRADE and fail-closed output.
        self._last_decision_attempt: datetime | None = None

    def desired_symbol(self) -> str | None:
        """Next symbol for DeepSeek review (MASTER DIRECTIVE §10/§24/§39).

        Priority: due factor candidates (priority-ranked), then rotation
        symbols outside the candidate pool (no factor-induced blind spots).
        Pure scheduling — never admissibility. Returns None when no board is
        wired (legacy single-symbol behavior preserved).
        """
        if self.opportunity_board is None:
            return None
        now = self.attempt_clock()
        exclude = {s for s, until in self._skip_until.items() if until > now}
        exclude |= {
            s
            for s, last in self._last_attempt_by_symbol.items()
            if now - last < self.retry_cooldown
        }
        return self.opportunity_board.next_agenda_symbol(exclude=exclude)

    async def on_market_data(self, ctx: StrategyContext):
        # OPEN-position management is a separate canonical LLM lifecycle.  New
        # directional entry authority must not pyramid through this entry path.
        position = ctx.positions.get(ctx.symbol)
        if position is not None and Decimal(str(position.quantity)) != 0:
            # Not an entry slot; back this symbol off the agenda for a while.
            self._skip_until[ctx.symbol] = self.attempt_clock() + timedelta(seconds=60)
            return []

        now = ctx.clock_time.astimezone(UTC)
        last_attempt = self._last_attempt_by_symbol.get(ctx.symbol)
        if last_attempt is not None and now - last_attempt < self.retry_cooldown:
            return []

        evidence_engine = self.evidence_engine
        if self.evidence_router is not None:
            resolved = await self.evidence_router.resolve(ctx.symbol)
            if resolved is not None:
                evidence_engine = resolved

        # MASTER DIRECTIVE §16: compact optional-evidence context for this
        # symbol (factor candidates are evidence only, never a gate).
        candidate = (
            self.opportunity_board.candidate_for(ctx.symbol)
            if self.opportunity_board is not None
            else None
        )
        opportunity_context = None
        if self.opportunity_board is not None:
            opportunity_context = build_opportunity_context(
                symbol=ctx.symbol,
                candidate=candidate,
                board=self.opportunity_board,
                deepseek_selected=False,
            )

        evidence = (
            evidence_engine.analyze_evidence(ctx)
            if self.tool_chief is None
            else {"regime": "UNKNOWN", "source_refs": []}
        )
        chief_ctx = ChiefTraderContext(
            symbol=ctx.symbol,
            market_snapshot=self._market_snapshot(ctx),
            regime=self._regime(evidence),
            quant_evidence=[evidence],
            portfolio_state=self._portfolio_state(ctx),
            risk_summary=self.risk_summary,
            opportunity_context=opportunity_context,
        )
        if self.context_loader is not None:
            chief_ctx = await self.context_loader.enrich(chief_ctx)
        memory_refs = list(chief_ctx.memory_refs)
        research_refs = list(chief_ctx.research_refs)
        episode_refs = list(chief_ctx.episode_refs)
        try:
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
                    memory_refs = package.refs_with_prefix("memory:")
                    research_refs = package.refs_with_prefix("research:")
                    episode_refs = package.refs_with_prefix("episode:")
        finally:
            completed_at = self.attempt_clock()
            if completed_at.tzinfo is None:
                completed_at = completed_at.replace(tzinfo=UTC)
            else:
                completed_at = completed_at.astimezone(UTC)
            self._last_attempt_by_symbol[ctx.symbol] = max(now, completed_at)
            self._last_decision_attempt = max(now, completed_at)

        evidence_refs = [
            str(ref)
            for ref in evidence.get("source_refs", [])
            if isinstance(ref, (str, int, float))
        ]
        # MASTER DIRECTIVE §30: durable opportunity lineage (observability
        # only — it never gates Risk or Execution).
        lineage = self._lineage(candidate)
        await self.decisions.save(
            decision,
            run_id=ctx.run_id,
            prompt_version=self.version,
            tool_refs=evidence_refs,
            memory_refs=memory_refs,
            research_refs=research_refs,
            episode_refs=episode_refs,
            opportunity_lineage=lineage,
        )
        if self.opportunity_board is not None:
            self.opportunity_board.record_decision(
                symbol=ctx.symbol,
                action=decision.action.value,
                candidate_source=lineage["candidate_source"],
                factor_evidence_present=lineage["factor_evidence_present"],
                factor_trigger_count=len(lineage["triggered_factors"]),
                decision_id=decision.decision_id,
            )
            self.opportunity_board.mark_reviewed(ctx.symbol)

        # This commit is deliberately before TradePlan creation.  It is the
        # durable factual proof that the LLM owned the proposed direction.
        await self.audit.log(
            "LIVE_LLM_DECISION",
            target=decision.decision_id,
            actor="live_llm",
            run_id=ctx.run_id,
            after={
                "decision": decision.model_dump(mode="json"),
                "evidence_source": getattr(evidence_engine, "name", "unknown"),
                "selected_tools": evidence.get("selected_tools", []),
                "decision_authority": "LIVE_LLM_ONLY",
                "opportunity_candidate_source": lineage["candidate_source"],
                "factor_evidence_present": lineage["factor_evidence_present"],
            },
        )

        if decision.action not in {"LONG", "SHORT"}:
            return []
        mid = ctx.book.mid_price()
        if self.sizer is None or mid is None or ctx.instrument is None:
            await self.audit.log(
                "LIVE_LLM_SIZING_UNAVAILABLE",
                target=decision.decision_id,
                actor="live_llm",
                run_id=ctx.run_id,
            )
            return []
        stop_price = Decimal(str(decision.stop_loss))
        stop_is_directional = (
            decision.action == "LONG" and stop_price < mid
        ) or (decision.action == "SHORT" and stop_price > mid)
        if not stop_is_directional:
            await self.audit.log(
                "LIVE_LLM_SIZING_REJECTED",
                target=decision.decision_id,
                actor="live_llm",
                run_id=ctx.run_id,
                after={"reason_codes": ["INVALID_DIRECTIONAL_STOP"]},
            )
            return []
        volatility = ctx.realized_volatility or Decimal("0")
        best_bid = ctx.book.best_bid()
        best_ask = ctx.book.best_ask()
        liquidity = Decimal("1") if (
            best_bid is not None
            and best_ask is not None
            and best_bid.quantity > 0
            and best_ask.quantity > 0
        ) else Decimal("0")
        if ctx.instrument is None:
            await self.audit.log(
                "LIVE_LLM_INSTRUMENT_UNAVAILABLE",
                target=decision.decision_id,
                actor="live_llm",
                run_id=ctx.run_id,
                after={"symbol": ctx.symbol},
            )
            return []
        sized = self.sizer.size(
            side=decision.action.value,
            requested_quantity=Decimal(str(decision.position_size_request)),
            requested_exposure=(
                Decimal(str(decision.requested_exposure))
                if decision.requested_exposure is not None
                else None
            ),
            requested_leverage=Decimal(str(decision.leverage_request or 1)),
            account=ctx.account,
            positions=ctx.positions,
            instrument=ctx.instrument,
            price=mid,
            stop_price=stop_price,
            volatility=volatility,
            liquidity=liquidity,
        )
        if sized.normalized_quantity <= 0:
            await self.audit.log(
                "LIVE_LLM_SIZING_REJECTED",
                target=decision.decision_id,
                actor="live_llm",
                run_id=ctx.run_id,
                after={"reason_codes": list(sized.sizing_reason_codes)},
            )
            return []
        try:
            plan, signal = await self.planner.create_entry_signal(
                decision,
                limit_price=mid,
                quantity=sized.normalized_quantity,
                execution_metadata={
                    "instrument_type": ctx.instrument.instrument_type,
                    "contract_size": str(ctx.instrument.contract_size),
                    "contract_multiplier": str(ctx.instrument.contract_multiplier),
                    "requested_quantity": str(decision.position_size_request),
                    "normalized_quantity": str(sized.normalized_quantity),
                    "requested_notional": str(sized.requested_notional),
                    "risk_normalized_notional": str(sized.risk_normalized_notional),
                    "requested_leverage": str(sized.requested_leverage),
                    "sizing_approved_leverage": str(sized.risk_bounded_leverage),
                    "volatility": str(volatility),
                    "liquidity": str(liquidity),
                    "max_loss_estimate": str(sized.max_loss_estimate),
                    "portfolio_exposure_after_trade": str(
                        sized.portfolio_exposure_after_trade
                    ),
                    "sizing_reason_codes": list(sized.sizing_reason_codes),
                },
            )
            if plan is not None:
                await self.decisions.link_trade_plan(decision.decision_id, plan.trade_plan_id)
        except (TypeError, ValueError) as exc:
            await self.audit.log(
                "LIVE_LLM_DECISION_INVALID",
                target=decision.decision_id,
                actor="live_llm",
                run_id=ctx.run_id,
                after={"reason": str(exc), "action": decision.action},
            )
            return []
        return [signal] if signal is not None else []

    @staticmethod
    def _lineage(candidate) -> dict[str, Any]:
        """Bounded factual lineage for §29/§30 (no chain-of-thought)."""
        if candidate is None:
            return {
                "candidate_source": CANDIDATE_SOURCE_MARKET_OBSERVER,
                "triggered_factors": [],
                "factor_evidence_present": False,
                "nominated_reason": "routine broad-market review; no factor trigger",
            }
        return {
            "candidate_source": candidate.source,
            "triggered_factors": [
                {"factor": o.factor, "strength": o.strength, "facts": o.facts}
                for o in candidate.triggered
            ],
            "factor_evidence_present": candidate.factor_evidence_present,
            "nominated_reason": candidate.nominated_reason[:255],
        }

    @staticmethod
    def _regime(evidence: dict[str, Any]) -> str:
        raw = evidence.get("regime", "UNKNOWN")
        if isinstance(raw, dict):
            return str(raw.get("regime") or raw.get("value") or "UNKNOWN")
        return str(raw)

    @staticmethod
    def _portfolio_state(ctx: StrategyContext) -> dict[str, Any]:
        return {
            "account": ctx.account.model_dump(mode="json"),
            "positions": {
                symbol: position.model_dump(mode="json")
                for symbol, position in ctx.positions.items()
            },
        }

    @staticmethod
    def _market_snapshot(ctx: StrategyContext) -> dict[str, Any]:
        best_bid = ctx.book.best_bid()
        best_ask = ctx.book.best_ask()
        mid = ctx.book.mid_price()
        return {
            "symbol": ctx.symbol,
            "timestamp": ctx.clock_time.isoformat(),
            "best_bid": str(best_bid.price) if best_bid is not None else None,
            "best_ask": str(best_ask.price) if best_ask is not None else None,
            "mid": str(mid) if mid is not None else None,
            "mark_price": str(ctx.mark_price) if ctx.mark_price is not None else None,
            "index_price": str(ctx.index_price) if ctx.index_price is not None else None,
            "funding": str(ctx.funding) if ctx.funding is not None else None,
            "open_interest": str(ctx.oi) if ctx.oi is not None else None,
            "basis": str(ctx.basis) if ctx.basis is not None else None,
            "realized_volatility": (
                str(ctx.realized_volatility)
                if ctx.realized_volatility is not None
                else None
            ),
            "source": "OKX_PUBLIC",
            "instrument": (
                {
                    "symbol": ctx.instrument.symbol,
                    "instrument_type": ctx.instrument.instrument_type,
                    "contract_size": str(ctx.instrument.contract_size),
                    "contract_multiplier": str(ctx.instrument.contract_multiplier),
                    "lot_size": str(ctx.instrument.step_size),
                    "min_quantity": str(ctx.instrument.min_qty),
                    "tick_size": str(ctx.instrument.tick_size),
                }
                if ctx.instrument is not None
                else None
            ),
        }
