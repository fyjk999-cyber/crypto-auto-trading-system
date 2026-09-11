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
        selected, error = await self.chief.select_tools(ctx, self.tools.catalog())
        if selected is None:
            return self.chief.fail_closed(ctx, error or "TOOL_SELECTION_FAILED"), None
        try:
            async with asyncio.timeout(30):
                package, ctx = await self._build_evidence(
                    selected, ctx, tool_context=tool_context, now=now
                )
        except (KeyError, TimeoutError, TypeError, ValueError):
            return self.chief.fail_closed(ctx, "TOOL_ROUTER_FAILED"), None
        enriched = replace(
            ctx,
            quant_evidence=[package.model_dump(mode="json")],
        )
        return await self.chief.decide(enriched), package

    async def _build_evidence(
        self, selected, ctx, *, tool_context: dict[str, Any], now: datetime
    ) -> tuple[DynamicEvidencePackage, ChiefTraderContext]:
        first_items = []
        if "market_regime" in selected:
            first = await self.tools.build_package(
                ["market_regime"], ctx.symbol,
                {**tool_context, "chief_context": ctx}, now=now,
            )
            first_items = first.items
            regime_payload = first.items[0].finding.get("regime", {}) if first.items else {}
            regime = regime_payload.get("regime") if isinstance(regime_payload, dict) else None
            if regime:
                ctx = replace(ctx, regime=str(regime))
        remaining = [name for name in selected if name != "market_regime"]
        rest = await self.tools.build_package(
            remaining, ctx.symbol, {**tool_context, "chief_context": ctx}, now=now,
        )
        return DynamicEvidencePackage(
            symbol=ctx.symbol,
            selected_tools=selected,
            items=first_items + rest.items,
            created_at=now,
        ), ctx
