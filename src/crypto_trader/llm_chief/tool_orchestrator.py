"""Two-stage tool orchestration under one ChiefTrader decision authority."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from typing import Any

from crypto_trader.llm.tools.registry import DynamicEvidencePackage, LLMToolRegistry
from crypto_trader.llm_chief.budget import (
    P1_POSITION_LIFECYCLE,
    P2_FINAL_ENTRY_DECISION,
    BudgetFallbackStats,
)
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import ChiefTraderDecision, PositionState
from crypto_trader.llm_chief.engine import ChiefTraderEngine


class ToolDrivenChiefTrader:
    """The same Chief selects evidence tools and makes the final decision."""

    tool_round_budget_seconds = 45.0
    tool_selection_timeout_seconds = 20.0

    def __init__(
        self,
        chief: ChiefTraderEngine,
        tools: LLMToolRegistry,
        *,
        selection_recorder=None,
        card_trace_store=None,
        fallback_stats: BudgetFallbackStats | None = None,
    ) -> None:
        self.chief = chief
        self.tools = tools
        self.selection_recorder = selection_recorder
        self.card_trace_store = card_trace_store
        self.fallback_stats = fallback_stats or BudgetFallbackStats()

    async def decide(
        self,
        ctx: ChiefTraderContext,
        *,
        tool_context: dict[str, Any],
        now: datetime,
    ) -> tuple[ChiefTraderDecision, DynamicEvidencePackage | None]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.1, float(self.tool_round_budget_seconds))
        selection_budget = min(
            float(self.tool_selection_timeout_seconds),
            max(0.0, deadline - loop.time()),
        )
        try:
            selected, error = await asyncio.wait_for(
                self.chief.select_tools(
                    ctx,
                    self.tools.catalog(),
                    timeout_seconds=max(0.1, selection_budget),
                ),
                timeout=max(0.1, selection_budget),
            )
        except TimeoutError:
            return self.chief.fail_closed(ctx, "TOOL_SELECTION_TIMEOUT"), None
        if selected is None:
            if error == "SKIPPED_BUDGET":
                # P3 is optional enrichment.  Its exhaustion must never become
                # a hard prerequisite for the P1/P2 final decision.
                return await self._decide_with_baseline_context(ctx, now=now)
            return self.chief.fail_closed(ctx, error or "TOOL_SELECTION_FAILED"), None
        remaining = deadline - loop.time()
        if remaining <= 0:
            return self.chief.fail_closed(ctx, "TOOL_ROUND_DEADLINE_EXCEEDED"), None
        try:
            package, ctx = await asyncio.wait_for(
                self._build_evidence(
                    selected,
                    ctx,
                    tool_context=tool_context,
                    now=now,
                    deadline=deadline,
                ),
                timeout=remaining,
            )
        except (KeyError, TimeoutError, TypeError, ValueError):
            return self.chief.fail_closed(ctx, "TOOL_ROUTER_FAILED"), None
        enriched = replace(
            ctx,
            quant_evidence=[package.model_dump(mode="json")],
        )
        # The exact deterministic prompt rendered here is the same prompt that
        # ChiefTraderEngine.decide sends to the provider. Persist its hash only
        # after the provider returns a decision, then bind any card trace to
        # that application-owned decision id.
        final_prompt = self.chief.render_prompt(enriched)
        decision = await self.chief.decide(enriched)
        if self.selection_recorder is not None:
            await self.selection_recorder.record_selection(
                context=enriched,
                selected_tools=package.selected_tools,
                evidence_package=package,
                decision_id=decision.decision_id,
                prompt=final_prompt,
            )
        await self._attach_card_trace(decision, package)
        return decision, package

    async def _decide_with_baseline_context(
        self, ctx: ChiefTraderContext, *, now: datetime
    ) -> tuple[ChiefTraderDecision, None]:
        """Make the P1/P2 decision when optional P3 research is budget-skipped.

        The baseline context is the canonical factual context already assembled
        by the caller; no synthetic evidence is created and no quant component
        is allowed to emit direction.  The final decision still acquires its
        own P1 or P2 budget ticket inside ``ChiefTraderEngine.decide``.
        """

        stats = self.fallback_stats
        stats.p3_optional_fallback_count += 1
        stats.last_research_budget_state = "SKIPPED_BUDGET"
        stats.last_research_fallback = "BASELINE_FACTUAL_CONTEXT"
        priority = (
            P1_POSITION_LIFECYCLE
            if ctx.position_state != PositionState.FLAT
            else P2_FINAL_ENTRY_DECISION
        )
        stats.last_final_decision_priority = priority
        stats.last_final_decision_attempted = True

        decision = await self.chief.decide(ctx)
        core_budget_skip = (
            str(getattr(decision.action, "value", decision.action)) == "FAIL_CLOSED"
            and "SKIPPED_BUDGET" in (decision.reason_codes or [])
        )
        if core_budget_skip:
            # True P1/P2 exhaustion must remain fail-closed and must not be
            # relabelled as an optional-research fallback.
            return decision, None

        if priority == P1_POSITION_LIFECYCLE:
            stats.p1_decisions_after_p3_skip += 1
        else:
            stats.p2_decisions_after_p3_skip += 1
        reason_codes = list(decision.reason_codes or [])
        if "OPTIONAL_RESEARCH_SKIPPED_BUDGET" not in reason_codes:
            reason_codes.append("OPTIONAL_RESEARCH_SKIPPED_BUDGET")
        decision = decision.model_copy(update={"reason_codes": reason_codes})
        return decision, None

    def budget_observability(self) -> dict:
        """Read-only fallback/priority observability for watchdog consumers."""

        return self.fallback_stats.snapshot()

    async def _attach_card_trace(self, decision, package) -> None:
        if self.card_trace_store is None:
            return
        for item in package.items:
            finding = item.finding
            trace_id = finding.get("card_trace_id") if isinstance(finding, dict) else None
            if trace_id:
                attached = await self.card_trace_store.attach_decision(
                    trace_id=str(trace_id),
                    decision_id=decision.decision_id,
                    evidence_package_id=None,
                )
                if not attached:
                    raise RuntimeError("card evidence trace could not be attached")
                return

    async def _build_evidence(
        self,
        selected,
        ctx,
        *,
        tool_context: dict[str, Any],
        now: datetime,
        deadline: float,
    ) -> tuple[DynamicEvidencePackage, ChiefTraderContext]:
        loop = asyncio.get_running_loop()
        first_items = []
        if "market_regime" in selected:
            remaining = max(0.0, deadline - loop.time())
            if remaining <= 0:
                raise TimeoutError("tool round deadline exceeded")
            first = await self.tools.build_package(
                ["market_regime"], ctx.symbol,
                {**tool_context, "chief_context": ctx}, now=now,
                overall_timeout_seconds=remaining,
                timeout_seconds=min(10.0, remaining),
            )
            first_items = first.items
            regime_payload = first.items[0].finding.get("regime", {}) if first.items else {}
            regime = regime_payload.get("regime") if isinstance(regime_payload, dict) else None
            if regime:
                ctx = replace(ctx, regime=str(regime))
        remaining = [name for name in selected if name != "market_regime"]
        remaining_budget = max(0.0, deadline - loop.time())
        if remaining and remaining_budget <= 0:
            raise TimeoutError("tool round deadline exceeded")
        rest = await self.tools.build_package(
            remaining, ctx.symbol, {**tool_context, "chief_context": ctx}, now=now,
            overall_timeout_seconds=remaining_budget,
            timeout_seconds=min(10.0, remaining_budget) if remaining_budget else 10.0,
        )
        selected_versions = {
            name: self.tools.tool_versions().get(name, "v1") for name in selected
        }
        return DynamicEvidencePackage(
            symbol=ctx.symbol,
            selected_tools=selected,
            items=first_items + rest.items,
            tool_versions=selected_versions,
            created_at=now,
        ), ctx
