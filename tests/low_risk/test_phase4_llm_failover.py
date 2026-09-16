"""Phase 4G (Low-Risk V2) Core LLM failover tests.

DeepSeek (one immediate retry) -> GLM with LATEST factual state (one immediate
retry) -> LLM_OFFLINE_MODE with five-minute probe windows. These tests use
deterministic fake providers (no network, no credentials, no fake acceptance).
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from crypto_trader.llm_chief import failover as failover_module
from crypto_trader.llm_chief.failover import CoreLLMRouter, LLMLatencyTracker
from crypto_trader.llm_chief.provider import GLMProvider, LLMResponse

BASE_TIME = datetime(2026, 9, 16, 0, 0, 0, tzinfo=UTC)


class FakeProvider:
    def __init__(self, name: str, outcomes: list[dict], *, healthy: bool = True) -> None:
        self.name = name
        self._outcomes = list(outcomes)
        self._healthy = healthy
        self.calls: list[dict] = []
        self.last_attempt_count: int | None = None

    def healthy(self) -> bool:
        return self._healthy

    async def complete_json(self, *, prompt: str, **kwargs) -> LLMResponse:
        self.calls.append({"prompt": prompt, **kwargs})
        outcome = self._outcomes.pop(0) if self._outcomes else {"ok": False, "error": "NO_MORE"}
        self.last_attempt_count = int(outcome.get("attempts", 1))
        return LLMResponse(
            text=outcome.get("text", ""),
            provider=self.name,
            model=f"{self.name}-test",
            latency_ms=float(outcome.get("latency_ms", 100.0)),
            parsed_json=outcome.get("parsed"),
            ok=bool(outcome.get("ok", False)),
            error=outcome.get("error"),
        )


def _clock(start: datetime = BASE_TIME):
    current = {"now": start}
    return current, (lambda: current["now"])


async def test_primary_success_never_calls_backup() -> None:
    primary = FakeProvider("deepseek", [{"ok": True, "parsed": {"action": "WAIT"}}])
    backup = FakeProvider("glm", [{"ok": True, "parsed": {"action": "WAIT"}}])
    router = CoreLLMRouter(primary=primary, backup=backup)
    response = await router.complete_json(prompt="p", state_version="v1")
    assert response.ok is True
    assert response.served_by == "deepseek"
    assert response.state_version == "v1"
    assert backup.calls == []
    assert router.offline is False


async def test_failover_uses_fresh_state_not_stale_prompt() -> None:
    primary = FakeProvider("deepseek", [{"ok": False, "error": "LLM_TIMEOUT"}])
    backup = FakeProvider("glm", [{"ok": True, "parsed": {"action": "HOLD"}}])
    rebuilds = {"count": 0}

    async def rebuild():
        rebuilds["count"] += 1
        return ("FRESH PROMPT v7", "v7")

    router = CoreLLMRouter(primary=primary, backup=backup, prompt_rebuilder=rebuild)
    response = await router.complete_json(
        prompt="STALE PROMPT v1", state_version="v1", operation="trading_decision"
    )
    assert response.ok is True
    assert response.served_by == "glm"
    assert rebuilds["count"] == 1
    assert backup.calls[0]["prompt"] == "FRESH PROMPT v7"
    assert primary.calls[0]["prompt"] == "STALE PROMPT v1"
    # The GLM answer is bound to the fresh state version, not the stale request.
    assert response.state_version == "v7"


async def test_stale_prompt_is_never_replayed_without_rebuilder() -> None:
    primary = FakeProvider("deepseek", [{"ok": False, "error": "LLM_TIMEOUT"}])
    backup = FakeProvider("glm", [{"ok": True, "parsed": {}}])
    router = CoreLLMRouter(primary=primary, backup=backup, prompt_rebuilder=None)
    response = await router.complete_json(prompt="STALE", state_version="v1")
    assert response.ok is False
    assert "BACKUP_SKIPPED_NO_FRESH_CONTEXT" in (response.error or "")
    assert backup.calls == []
    assert router.status.backup_skipped_no_fresh_context == 1
    assert router.offline is True


async def test_both_fail_enters_offline_and_window_blocks_calls() -> None:
    current, now = _clock()
    primary = FakeProvider("deepseek", [{"ok": False, "error": "LLM_TIMEOUT"}])
    backup = FakeProvider("glm", [{"ok": False, "error": "HTTP_500"}])

    async def rebuild():
        return "fresh"

    router = CoreLLMRouter(primary=primary, backup=backup, prompt_rebuilder=rebuild, now=now)
    first = await router.complete_json(prompt="p", state_version="v1")
    assert first.ok is False
    assert router.offline is True
    assert router.status.windows == 1
    assert router.status.next_probe_at == BASE_TIME + timedelta(seconds=300)
    assert router.status.reason and "ALL_PROVIDERS_FAILED" in router.status.reason

    # Inside the five-minute window the router returns immediately, no calls.
    current["now"] = BASE_TIME + timedelta(seconds=299)
    primary_calls = len(primary.calls)
    backup_calls = len(backup.calls)
    blocked = await router.complete_json(prompt="p", state_version="v2")
    assert blocked.ok is False
    assert blocked.error == "LLM_OFFLINE_MODE"
    assert len(primary.calls) == primary_calls
    assert len(backup.calls) == backup_calls


async def test_recovery_at_probe_window_is_immediate() -> None:
    current, now = _clock()
    primary = FakeProvider(
        "deepseek",
        [
            {"ok": False, "error": "LLM_TIMEOUT"},
            {"ok": True, "parsed": {"action": "HOLD"}},
        ],
    )
    backup = FakeProvider("glm", [{"ok": False, "error": "HTTP_500"}])

    async def rebuild():
        return "fresh"

    router = CoreLLMRouter(primary=primary, backup=backup, prompt_rebuilder=rebuild, now=now)
    await router.complete_json(prompt="p", state_version="v1")
    assert router.offline is True

    current["now"] = BASE_TIME + timedelta(seconds=300)
    recovered = await router.complete_json(prompt="stale-again", state_version="v2")
    assert recovered.ok is True
    assert recovered.served_by == "deepseek"
    assert router.offline is False
    assert router.status.next_probe_at is None
    assert any(event["event"] == "LLM_RECOVERED" for event in router.events)
    # Recovery is immediate: the successful probe answer is returned directly.
    assert recovered.state_version == "v2"


async def test_retry_attempts_are_counted_in_metrics() -> None:
    primary = FakeProvider(
        "deepseek",
        [{"ok": True, "parsed": {"action": "WAIT"}, "attempts": 2, "latency_ms": 9000}],
    )
    router = CoreLLMRouter(primary=primary, backup=None)
    response = await router.complete_json(prompt="p")
    assert response.ok is True
    snapshot = router.tracker.snapshot()
    assert snapshot["deepseek"]["calls"] == 1
    assert snapshot["deepseek"]["retries"] == 1
    assert snapshot["deepseek"]["retry_rate"] == 1.0
    assert snapshot["deepseek"]["success_rate"] == 1.0


def test_latency_tracker_percentiles_and_rates() -> None:
    tracker = LLMLatencyTracker()
    for index in range(1, 101):
        tracker.record(
            "deepseek",
            latency_ms=float(index * 100),
            ok=index <= 90,
            timeout=index > 90,
            attempts=2 if index % 2 == 0 else 1,
        )
    stats = tracker.snapshot()["deepseek"]
    assert stats["calls"] == 100
    assert stats["successes"] == 90
    assert stats["success_rate"] == pytest.approx(0.9)
    assert stats["timeouts"] == 10
    assert stats["timeout_rate"] == pytest.approx(0.1)
    assert stats["retries"] == 50
    assert stats["retry_rate"] == pytest.approx(0.5)
    assert stats["mean_ms"] == pytest.approx(5050.0)
    assert stats["p50_ms"] == pytest.approx(5000.0)
    assert stats["p90_ms"] == pytest.approx(9000.0)
    assert stats["p95_ms"] == pytest.approx(9500.0)
    assert stats["p99_ms"] == pytest.approx(9900.0)
    assert stats["max_ms"] == pytest.approx(10000.0)


def test_glm_provider_without_key_fails_closed_offline() -> None:
    import asyncio

    provider = GLMProvider(api_key="", model="glm-4-flash", base_url="https://example.invalid")
    assert provider.healthy() is False
    response = asyncio.run(provider.complete_json(prompt="p"))
    assert response.ok is False
    assert response.error == "NO_API_KEY"


def test_router_has_no_order_authority() -> None:
    source = inspect.getsource(failover_module)
    for forbidden in (
        "ExecutionAuthority",
        "OrderManager",
        "submit_order",
        "process_signal",
        "SignalIntent",
        "TradePlan",
    ):
        assert forbidden not in source
    assert failover_module.OFFLINE_WINDOW_SECONDS == 300.0


async def test_router_accepts_per_call_fresh_state_rebuilder() -> None:
    primary = FakeProvider("deepseek", [{"ok": False, "error": "LLM_TIMEOUT"}])
    backup = FakeProvider("glm", [{"ok": True, "parsed": {"action": "HOLD"}}])

    async def rebuild():
        return ("PER_CALL_FRESH", "v9")

    router = CoreLLMRouter(primary=primary, backup=backup)  # no constructor rebuilder
    response = await router.complete_json(
        prompt="STALE", state_version="v1", prompt_rebuilder=rebuild
    )
    assert response.ok is True
    assert response.served_by == "glm"
    assert backup.calls[0]["prompt"] == "PER_CALL_FRESH"
    assert response.state_version == "v9"


async def test_chief_engine_passes_rebuild_context_to_router() -> None:
    from crypto_trader.llm_chief.context import ChiefTraderContext
    from crypto_trader.llm_chief.engine import ChiefTraderEngine

    decision_json = {
        "decision_id": "d1",
        "symbol": "BTCUSDT",
        "action": "WAIT",
        "market_regime": "RANGE",
        "position_state": "FLAT",
        "thesis": "wait for clarity",
    }
    primary = FakeProvider("deepseek", [{"ok": False, "error": "LLM_TIMEOUT"}])
    backup = FakeProvider("glm", [{"ok": True, "parsed": decision_json}])

    async def rebuild():
        return ("ENGINE_FRESH", "v10")

    router = CoreLLMRouter(primary=primary, backup=backup)
    chief = ChiefTraderEngine(provider=router)
    ctx = ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={"last": "100"},
        regime="RANGE",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
    )
    decision = await chief.decide(ctx, rebuild_context=rebuild)
    assert decision.action.value == "WAIT"
    assert backup.calls[0]["prompt"] == "ENGINE_FRESH"


async def test_router_state_version_is_metadata_not_provider_kwarg() -> None:
    """Regression: the real DeepSeek/GLM providers must never receive state_version.

    Runtime startup with a real provider previously failed with TypeError
    inside complete_json; the router must bind state_version to the response.
    """
    from crypto_trader.llm_chief.failover import CoreLLMRouter
    from crypto_trader.llm_chief.provider import DeepSeekProvider

    primary = DeepSeekProvider(api_key=None)  # strict real signature, fails closed
    router = CoreLLMRouter(primary=primary, backup=None)

    response = await router.complete_json(
        prompt="decide",
        state_version="pos_v7",
    )
    assert response.ok is False
    assert response.error is not None
    assert response.state_version == "pos_v7"
    assert router.status.offline is True or router.status.offline is False  # no TypeError


def test_core_llm_prompt_requires_v2_new_risk_contract() -> None:
    """Natural PAPER entries need the LLM to emit plan_contract_version=2."""
    from crypto_trader.llm_chief.context import ChiefTraderContext
    from crypto_trader.llm_chief.decision import PositionState
    from crypto_trader.llm_chief.engine import ChiefTraderEngine
    from crypto_trader.llm_chief.provider import DeepSeekProvider

    engine = ChiefTraderEngine(provider=DeepSeekProvider(api_key=None))
    ctx = ChiefTraderContext(
        symbol="BTCUSDT",
        position_state=PositionState.FLAT,
        regime="UNKNOWN",
        market_snapshot="{}",
        quant_evidence="{}",
        portfolio_state="{}",
        risk_summary="{}",
    )
    prompt = engine.render_prompt(ctx)
    assert '"plan_contract_version":2' in prompt
    assert '"capital_allocation_pct":number' in prompt
    assert '"base_exit"' in prompt
    assert "plan_contract_version=2" in prompt
    assert "size_pct as a JSON number in (0,100]" in prompt
    assert "rejected by execution" in prompt


def test_deepseek_defaults_to_flash_high() -> None:
    import inspect

    from crypto_trader.llm_chief.provider import DeepSeekProvider

    provider = DeepSeekProvider(api_key=None)
    assert provider.model == "deepseek-flash"
    default_effort = (
        inspect.signature(DeepSeekProvider.complete_json).parameters["reasoning_effort"].default
    )
    assert default_effort == "high"


def test_trading_resolver_allowlist_and_generic_env_isolation(monkeypatch) -> None:
    from crypto_trader.llm_chief.provider import (
        DisallowedTradingLLMModel,
        resolve_trading_llm_config,
    )

    monkeypatch.delenv("TRADING_LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    default = resolve_trading_llm_config()
    assert default.model == "deepseek-flash"
    assert default.thinking is True
    assert default.reasoning_effort == "high"
    assert default.config_source == "canonical_default"

    monkeypatch.setenv("TRADING_LLM_MODEL", "deepseek-flash")
    assert resolve_trading_llm_config().model == "deepseek-flash"

    for bad in (
        "deepseek-v4-pro",
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-flash-high",
        "garbage",
    ):
        monkeypatch.setenv("TRADING_LLM_MODEL", bad)
        try:
            resolve_trading_llm_config()
        except DisallowedTradingLLMModel as exc:
            assert "DISALLOWED_TRADING_LLM_MODEL" in str(exc)
        else:
            raise AssertionError(f"{bad} must be rejected")

    # Generic Harness/developer env must never control the trading model.
    monkeypatch.delenv("TRADING_LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-pro")
    assert resolve_trading_llm_config().model == "deepseek-flash"
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    assert resolve_trading_llm_config().model == "deepseek-flash"
