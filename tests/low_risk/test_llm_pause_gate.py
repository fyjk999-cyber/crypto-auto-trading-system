"""Zero-call LLM provider pause gate regressions.

The operator pause contract is stronger than LLM_OFFLINE_MODE: while paused,
no provider method may be invoked, including after the normal 300s offline
probe interval. Market data, Risk, deterministic exits, the PAPER runtime,
lease and single-writer logic remain untouched because the gate lives only in
the provider/router layer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from crypto_trader.api.deps import LLMRuntimeStatus
from crypto_trader.execution.base_exit import BaseExitRegistry
from crypto_trader.llm_chief.failover import CoreLLMRouter
from crypto_trader.llm_chief.provider import (
    DeepSeekProvider,
    GLMProvider,
    LLMResponse,
    provider_calls_paused,
    provider_pause_snapshot,
    reset_provider_pause_counters,
    resolve_trading_llm_config,
)


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 17, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class SpyProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.model = name
        self.calls = 0
        self.last_attempt_count = 0

    def healthy(self) -> bool:
        return True

    async def complete_json(self, **kwargs) -> LLMResponse:
        self.calls += 1
        return LLMResponse(text="{}", provider=self.name, model=self.model, latency_ms=0.0)


async def test_pause_blocks_router_primary_backup_and_auto_probes(monkeypatch) -> None:
    reset_provider_pause_counters()
    monkeypatch.setenv("LLM_CALLS_PAUSED", "true")
    monkeypatch.setenv("LLM_CALLS_PAUSED_REASON", "TEST_OPERATOR_PAUSE")

    primary = SpyProvider("deepseek")
    backup = SpyProvider("glm")
    clock = MutableClock()
    router = CoreLLMRouter(primary=primary, backup=backup, now=clock)

    for _ in range(12):
        response = await router.complete_json(prompt="{}", operation="trading_decision")
        assert response.ok is False
        assert response.error == "LLM_CALLS_PAUSED_BY_CONFIG"
        clock.advance(400)  # advance far beyond the 300s offline probe window

    assert primary.calls == 0
    assert backup.calls == 0
    snapshot = provider_pause_snapshot()
    assert snapshot["provider_calls_paused"] is True
    assert snapshot["pause_reason"] == "TEST_OPERATOR_PAUSE"
    assert snapshot["paused_since"] is not None
    assert snapshot["outbound_calls_blocked"] >= 12


async def test_pause_blocks_direct_deepseek_and_glm_provider_calls(monkeypatch) -> None:
    reset_provider_pause_counters()
    monkeypatch.setenv("LLM_CALLS_PAUSED", "yes")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("TRADING_LLM_MODEL", raising=False)

    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    transport = httpx.MockTransport(handler)
    deepseek = DeepSeekProvider(api_key="test-secret", transport=transport)
    glm = GLMProvider(api_key="test-secret", transport=transport)

    deepseek_response = await deepseek.complete_json(prompt="{}")
    glm_response = await glm.complete_json(prompt="{}")

    assert seen == []
    assert deepseek_response.error == "LLM_CALLS_PAUSED_BY_CONFIG"
    assert glm_response.error == "LLM_CALLS_PAUSED_BY_CONFIG"
    assert provider_pause_snapshot()["outbound_calls_blocked"] >= 2


async def test_pause_suppresses_runtime_health_probe(monkeypatch) -> None:
    reset_provider_pause_counters()
    monkeypatch.setenv("LLM_CALLS_PAUSED", "on")

    class NeverCalledProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def complete_json(self, **kwargs) -> LLMResponse:
            self.calls += 1
            return LLMResponse(
                text="{}", provider="deepseek", model="deepseek-flash", latency_ms=0.0
            )

    provider = NeverCalledProvider()
    status = LLMRuntimeStatus(provider_instance=provider)
    await status.probe()

    assert provider.calls == 0
    assert status.provider_state == "PROVIDER_PAUSED"
    assert status.last_error == "LLM_CALLS_PAUSED_BY_CONFIG"
    snapshot = status.snapshot()
    assert snapshot["provider_call_pause"]["provider_calls_paused"] is True
    assert snapshot["provider_call_pause"]["probe_suppressed"] >= 1


def test_pause_gate_keeps_model_policy_and_runtime_components_intact(monkeypatch) -> None:
    reset_provider_pause_counters()
    monkeypatch.setenv("LLM_CALLS_PAUSED", "true")
    monkeypatch.setenv("TRADING_LLM_MODEL", "deepseek-flash")
    config = resolve_trading_llm_config()
    assert config.provider == "deepseek"
    assert config.model == "deepseek-flash"
    assert config.thinking is True
    assert config.reasoning_effort == "high"
    assert provider_calls_paused() is True
    # Deterministic protection is independent of provider availability.
    assert BaseExitRegistry() is not None
