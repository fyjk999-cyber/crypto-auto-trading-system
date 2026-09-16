"""LLM runtime executor with timeout/retry/fallback and fail-safe NO_TRADE."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_trader.legacy_llm.isolation import (
    LEGACY_LLM_DISABLED_BY_CONFIG,
    LegacyLLMInvocationTracker,
    legacy_llm_enabled,
)


@dataclass
class LLMExecutionResult:
    decision: dict
    ok: bool
    reason: str


class LLMExecutor:
    def __init__(
        self,
        provider=None,
        fallback_decision=None,
        *,
        enabled: bool | None = None,
        tracker: LegacyLLMInvocationTracker | None = None,
    ) -> None:
        self.provider = provider
        self.enabled = enabled
        self.tracker = tracker or LegacyLLMInvocationTracker()
        self.fallback_decision = fallback_decision or {
            "action": "NO_TRADE",
            "reason_codes": ["LLM_FAILSAFE"],
        }

    async def execute(self, prompt: str) -> LLMExecutionResult:
        if not legacy_llm_enabled(self.enabled):
            self.tracker.record_disabled("LLMExecutor.execute")
            # Ignore any caller-supplied fallback here: a disabled LLM may
            # never turn stale cache data or a default BUY/SELL into risk.
            return LLMExecutionResult(
                {"action": "NO_DECISION", "reason_codes": [LEGACY_LLM_DISABLED_BY_CONFIG]},
                False,
                LEGACY_LLM_DISABLED_BY_CONFIG,
            )
        if self.provider is None:
            return LLMExecutionResult(self.fallback_decision, True, "NO_PROVIDER")
        self.tracker.record_provider_call(
            "LLMExecutor.execute", provider=str(getattr(self.provider, "name", "injected"))
        )
        response = await self.provider.complete_json(prompt=prompt)
        if not response.ok:
            return LLMExecutionResult(self.fallback_decision, True, response.error or "LLM_FAILED")
        if response.parsed_json:
            return LLMExecutionResult(response.parsed_json, True, "OK")
        return LLMExecutionResult(self.fallback_decision, True, "INVALID_JSON")
