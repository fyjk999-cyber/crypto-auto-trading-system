"""Read-only learned-context tools selected by the canonical ChiefTrader."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crypto_trader.llm.tools.registry import LLMToolRegistry
from crypto_trader.llm_chief.context import ChiefTraderContext

if TYPE_CHECKING:
    from crypto_trader.llm_chief.context_loader import ChiefContextLoader


def register_context_tools(
    registry: LLMToolRegistry,
    loader: ChiefContextLoader,
) -> None:
    for name in (
        "memory_search",
        "episode_search",
        "research_retrieval",
        "coin_profile",
        "factor_intelligence",
    ):
        registry.register(
            name, _tool(loader, name),
            description=f"Reviewed {name} records available at the decision as-of time",
        )


def _tool(loader: ChiefContextLoader, name: str):
    async def execute(symbol: str, context: dict):
        chief_context = context.get("chief_context")
        if not isinstance(chief_context, ChiefTraderContext) or chief_context.symbol != symbol:
            raise ValueError("canonical ChiefTraderContext required")
        return await loader.load_tool(
            name,
            chief_context,
            as_of=context["as_of"],
            account_id=context.get("account_id"),
            mode=context.get("mode"),
        )

    return execute
