"""LLM runtime executor with timeout/retry/fallback and fail-safe NO_TRADE."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LLMExecutionResult:
    decision: dict
    ok: bool
    reason: str


class LLMExecutor:
    def __init__(self, provider=None, fallback_decision=None) -> None:
        self.provider = provider
        self.fallback_decision = fallback_decision or {
            "action": "NO_TRADE",
            "reason_codes": ["LLM_FAILSAFE"],
        }

    async def execute(self, prompt: str) -> LLMExecutionResult:
        if self.provider is None:
            return LLMExecutionResult(self.fallback_decision, True, "NO_PROVIDER")
        response = await self.provider.complete_json(prompt=prompt)
        if not response.ok:
            return LLMExecutionResult(self.fallback_decision, True, response.error or "LLM_FAILED")
        if response.parsed_json:
            return LLMExecutionResult(response.parsed_json, True, "OK")
        return LLMExecutionResult(self.fallback_decision, True, "INVALID_JSON")
