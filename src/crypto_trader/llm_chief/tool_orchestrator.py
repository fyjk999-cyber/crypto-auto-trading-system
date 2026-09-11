"""Two-stage tool orchestration under one ChiefTrader decision authority."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from typing import Any

from crypto_trader.llm.tools.registry import DynamicEvidencePackage, LLMToolRegistry
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.engine import ChiefTraderEngine


class ToolDrivenChiefTrader:
    """The same Chief selects evidence tools and makes the final decision."""

    tool_round_budget_seconds = 45.0
    tool_selection_timeout_seconds = 20.0

    def __init__(self, chief: ChiefTraderEngine, tools: LLMToolRegistry) -> None:
        self.chief = chief
        self.tools = tools

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
        return await self.chief.decide(enriched), package

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
