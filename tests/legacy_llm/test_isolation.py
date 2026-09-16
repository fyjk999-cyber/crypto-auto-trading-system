from __future__ import annotations

import asyncio

import pytest

from crypto_trader.deepseek.client import DeepSeekClient
from crypto_trader.legacy_llm.isolation import LEGACY_LLM_DISABLED_BY_CONFIG
from crypto_trader.llm_runtime.executor import LLMExecutor


class UnexpectedNetworkClient:
    """Fails the test if disabled legacy code tries to open an HTTP client."""

    def __init__(self, *_args, **_kwargs) -> None:
        raise AssertionError("legacy LLM attempted to construct an HTTP client")


class ProviderSpy:
    def __init__(self) -> None:
        self.calls = 0

    async def complete_json(self, **_kwargs):
        self.calls += 1
        raise AssertionError("disabled legacy executor called its provider")


@pytest.mark.asyncio
async def test_disabled_legacy_deepseek_stops_before_http_client(monkeypatch) -> None:
    monkeypatch.setattr("crypto_trader.deepseek.client.httpx.AsyncClient", UnexpectedNetworkClient)
    client = DeepSeekClient(api_key="not-a-real-key", enabled=False)

    result = await client.market_opinion("this prompt must never leave process")

    assert result is None
    assert client.diagnostics()["last_status"] == LEGACY_LLM_DISABLED_BY_CONFIG
    assert client.diagnostics()["provider_calls"] == 0
    assert client.diagnostics()["deepseek_requests"] == 0
    assert client.diagnostics()["glm_requests"] == 0
    assert client.diagnostics()["other_llm_requests"] == 0
    assert client.diagnostics()["disabled_calls"] == 1


@pytest.mark.asyncio
async def test_disabled_legacy_executor_never_calls_injected_provider() -> None:
    provider = ProviderSpy()
    executor = LLMExecutor(
        provider=provider,
        fallback_decision={"action": "BUY"},
        enabled=False,
    )

    result = await executor.execute("legacy decision")

    assert provider.calls == 0
    assert result.ok is False
    assert result.reason == LEGACY_LLM_DISABLED_BY_CONFIG
    assert result.decision == {
        "action": "NO_DECISION",
        "reason_codes": [LEGACY_LLM_DISABLED_BY_CONFIG],
    }
    assert executor.tracker.snapshot()["provider_calls"] == 0


def test_env_switch_disables_legacy_client_without_exposing_credentials(monkeypatch) -> None:
    monkeypatch.setenv("LEGACY_LLM_ENABLED", "false")
    client = DeepSeekClient(api_key="not-a-real-key")

    asyncio.run(client.capital_review("never sent"))

    snapshot = client.diagnostics()
    assert snapshot["enabled"] is False
    assert snapshot["provider_calls"] == 0
    assert "not-a-real-key" not in repr(snapshot)
