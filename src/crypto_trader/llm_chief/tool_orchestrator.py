"""Two-stage tool orchestration under one ChiefTrader decision authority."""

from __future__ import annotations

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
        selected, error = await self.chief.select_tools(ctx, self.tools.available())
        if selected is None:
            return self.chief.fail_closed(ctx, error or "TOOL_SELECTION_FAILED"), None
        try:
            package = await self.tools.build_package(
                selected,
                ctx.symbol,
                tool_context,
                now=now,
            )
        except (KeyError, TypeError, ValueError):
            return self.chief.fail_closed(ctx, "TOOL_ROUTER_FAILED"), None
        enriched = replace(
            ctx,
            quant_evidence=[package.model_dump(mode="json")],
        )
        return await self.chief.decide(enriched), package
