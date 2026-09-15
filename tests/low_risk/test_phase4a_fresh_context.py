"""Phase 4A tests for the shared fresh-state rebuild helper."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from crypto_trader.llm_chief.fresh_context import build_rebuild_kwargs


class _Chief:
    def render_prompt(self, ctx) -> str:
        return f"PROMPT {ctx.symbol} v={ctx.state_version}"


def _fresh(state_version: str) -> SimpleNamespace:
    return SimpleNamespace(symbol="BTCUSDT", state_version=state_version)


def test_no_provider_returns_empty_kwargs() -> None:
    kwargs = build_rebuild_kwargs(chief=_Chief(), provider=None, symbol="BTCUSDT", strategy_ctx={})
    assert kwargs == {}


async def test_rebuilder_uses_fresh_context_and_version() -> None:
    async def provider(symbol, strategy_ctx):
        assert symbol == "BTCUSDT"
        return _fresh("v42")

    kwargs = build_rebuild_kwargs(
        chief=_Chief(), provider=provider, symbol="BTCUSDT", strategy_ctx={}
    )
    prompt, version = await kwargs["rebuild_context"]()
    assert version == "v42"
    assert prompt == "PROMPT BTCUSDT v=v42"


async def test_rebuilder_fails_safe_without_fresh_context() -> None:
    async def provider(symbol, strategy_ctx):
        return None

    kwargs = build_rebuild_kwargs(
        chief=_Chief(), provider=provider, symbol="BTCUSDT", strategy_ctx={}
    )
    with pytest.raises(RuntimeError, match="NO_FRESH_CONTEXT"):
        await kwargs["rebuild_context"]()
