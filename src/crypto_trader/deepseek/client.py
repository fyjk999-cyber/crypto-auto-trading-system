"""DeepSeek API client. Never logs the API key, never enables live trading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

from crypto_trader.deepseek.schemas import CapitalReview, MarketOpinion


@dataclass
class DeepSeekClient:
    api_key: str | None = field(default_factory=lambda: os.environ.get("DEEPSEEK_API_KEY"))
    base_url: str = "https://api.deepseek.com"
    timeout: float = 30.0
    retries: int = 2

    def configured(self) -> bool:
        return bool(self.api_key)

    async def _chat(self, prompt: str) -> dict | None:
        if not self.configured():
            return None
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            for _attempt in range(self.retries + 1):
                try:
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
                        return {"content": data["choices"][0]["message"]["content"]}
                    if response.status_code in (401, 403):
                        return None
                except httpx.HTTPError:
                    continue
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
