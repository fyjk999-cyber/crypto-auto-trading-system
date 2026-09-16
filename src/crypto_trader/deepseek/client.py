"""DeepSeek API client. Never logs the API key, never enables live trading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

from crypto_trader.deepseek.schemas import CapitalReview, MarketOpinion
from crypto_trader.legacy_llm.isolation import (
    LEGACY_LLM_DISABLED_BY_CONFIG,
    LegacyLLMInvocationTracker,
    legacy_llm_enabled,
)


@dataclass
class DeepSeekClient:
    api_key: str | None = field(default_factory=lambda: os.environ.get("DEEPSEEK_API_KEY"))
    base_url: str = "https://api.deepseek.com"
    timeout: float = 30.0
    retries: int = 2
    enabled: bool | None = None
    tracker: LegacyLLMInvocationTracker = field(default_factory=LegacyLLMInvocationTracker)
    last_status: str | None = field(default=None, init=False)

    def configured(self) -> bool:
        return legacy_llm_enabled(self.enabled) and bool(self.api_key)

    def diagnostics(self) -> dict[str, object]:
        """Return only non-secret legacy-boundary state."""

        return {
            "enabled": legacy_llm_enabled(self.enabled),
            "configured": self.configured(),
            "last_status": self.last_status,
            **self.tracker.snapshot(),
        }

    async def _chat(self, prompt: str) -> dict | None:
        if not legacy_llm_enabled(self.enabled):
            self.last_status = LEGACY_LLM_DISABLED_BY_CONFIG
            self.tracker.record_disabled("DeepSeekClient._chat")
            return None
        if not self.configured():
            self.last_status = "NO_API_KEY"
            return None
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            for _attempt in range(self.retries + 1):
                try:
                    # Count immediately before dispatch, so the number proves
                    # attempts rather than merely successful HTTP responses.
                    self.tracker.record_provider_call(
                        "DeepSeekClient._chat", provider="deepseek"
                    )
                    response = await client.post(
                        "/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={
                            "model": "deepseek-chat",
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.2,
                        },
                    )
                    if response.status_code == 200:
                        data = response.json()
                        self.last_status = "OK"
                        return {"content": data["choices"][0]["message"]["content"]}
                    if response.status_code in (401, 403):
                        self.last_status = f"HTTP_{response.status_code}"
                        return None
                except httpx.HTTPError:
                    self.last_status = "LLM_TRANSPORT_ERROR"
                    continue
        self.last_status = self.last_status or "LLM_PROVIDER_ERROR"
        return None

    async def market_opinion(self, prompt: str) -> MarketOpinion | None:
        result = await self._chat(prompt)
        if result is None:
            return None
        try:
            import json

            raw = json.loads(result["content"])
            return MarketOpinion(**raw)
        except Exception:
            return None

    async def capital_review(self, prompt: str) -> CapitalReview | None:
        result = await self._chat(prompt)
        if result is None:
            return None
        try:
            import json

            raw = json.loads(result["content"])
            return CapitalReview(**raw)
        except Exception:
            return None
