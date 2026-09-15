"""Shared Phase 4A fresh-state rebuild seam for Core LLM failover.

The DeepSeek -> GLM failover must never replay the prompt that was built before
the primary attempt failed.  Instead each decide call carries a rebuilder that
re-fetches the factual state (position/fills/pending/plan version/price/
evidence/state_version) and re-renders the prompt.

If the provider cannot produce fresh state, the rebuilder raises
``NO_FRESH_CONTEXT`` so the router fails safe to LLM_OFFLINE_MODE rather than
executing on stale facts.
"""

from __future__ import annotations

from typing import Any


def build_rebuild_kwargs(
    *,
    chief,
    provider,
    symbol: str,
    strategy_ctx: Any,
) -> dict:
    """Return ``{"rebuild_context": callable}`` or ``{}`` when no provider."""
    if provider is None:
        return {}

    async def rebuild_context() -> tuple[str, str | None]:
        fresh = await provider(symbol, strategy_ctx)
        if fresh is None:
            raise RuntimeError("NO_FRESH_CONTEXT")
        return chief.render_prompt(fresh), getattr(fresh, "state_version", None)

    return {"rebuild_context": rebuild_context}
