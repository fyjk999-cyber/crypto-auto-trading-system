"""Two-stage tool orchestration under one ChiefTrader decision authority."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from typing import Any

from crypto_trader.llm.tools.registry import DynamicEvidencePackage, LLMToolRegistry
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.engine import ChiefTraderEngine

_LOGGER = logging.getLogger(__name__)


class ToolDrivenChiefTrader:
    """The same Chief selects evidence tools and makes the final decision."""

    def __init__(
        self, chief: ChiefTraderEngine, tools: LLMToolRegistry, audit: Any | None = None
    ) -> None:
        self.chief = chief
        self.tools = tools
        self.audit = audit

    async def decide(
        self,
        ctx: ChiefTraderContext,
        *,
        tool_context: dict[str, Any],
        now: datetime,
        rebuild_context=None,
    ) -> tuple[ChiefTraderDecision, DynamicEvidencePackage | None]:
        selected, error = await self.chief.select_tools(ctx, self.tools.available())
        trace = getattr(self.chief, "last_tool_selection_trace", None)
        if isinstance(trace, dict) and (
            trace.get("repair_attempted") or trace.get("final_status") != "VALID"
        ):
            if self.audit is not None:
                try:
                    await self.audit.log(
                        "LLM_TOOL_SELECTION_TRACE", target=ctx.symbol, after=dict(trace)
                    )
                except Exception:  # noqa: BLE001 - audit must never change the decision
                    _LOGGER.warning("tool selection trace audit failed", exc_info=False)
        if selected is None:
            return self.chief.fail_closed(ctx, error or "TOOL_SELECTION_FAILED"), None
        try:
            package = await self.tools.build_package(
                selected,
                ctx.symbol,
                {**tool_context, "chief_context": ctx},
                now=now,
            )
        except (KeyError, TypeError, ValueError):
            return self.chief.fail_closed(ctx, "TOOL_ROUTER_FAILED"), None
        enriched = replace(
            ctx,
            quant_evidence=[package.model_dump(mode="json")],
        )
        # Phase 4A seam: forward the fresh-state rebuilder so a Core LLM
        # failover never replays the pre-tool stale prompt.
        if rebuild_context is not None:
            return await self.chief.decide(enriched, rebuild_context=rebuild_context), package
        return await self.chief.decide(enriched), package
