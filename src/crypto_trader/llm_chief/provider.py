"""LLM provider abstraction. Business layer depends only on this interface."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    latency_ms: float
    parsed_json: dict | None = None
    ok: bool = True
    error: str | None = None
    invocation_id: str = ""


class LLMProvider(Protocol):
    name: str

    async def complete_json(
        self,
        *,
        prompt: str,
        temperature: float = 0.2,
        timeout_seconds: float = 30.0,
        retries: int = 2,
    ) -> LLMResponse: ...

    def healthy(self) -> bool: ...


class DeepSeekProvider:
    name = "deepseek"

    def __init__(self, api_key: str | None = None, model: str = "deepseek-chat") -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        self.model = model

    def healthy(self) -> bool:
        return bool(self.api_key)

    async def complete_json(
        self,
        *,
        prompt: str,
        temperature: float = 0.2,
        timeout_seconds: float = 30.0,
        retries: int = 2,
    ) -> LLMResponse:
        import json
        import time

        if not self.api_key:
            return LLMResponse(
                text="",
                provider=self.name,
                model=self.model,
                latency_ms=0,
                ok=False,
                error="NO_API_KEY",
            )
        import httpx

        start = time.monotonic()
        async with httpx.AsyncClient(
            base_url="https://api.deepseek.com", timeout=timeout_seconds
        ) as client:
            for _ in range(retries + 1):
                try:
                    response = await client.post(
                        "/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={
                            "model": self.model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": temperature,
                        },
                    )
                    if response.status_code != 200:
                        continue
                    content = response.json()["choices"][0]["message"]["content"]
                    try:
                        parsed = json.loads(content)
                        return LLMResponse(
                            text=content,
                            provider=self.name,
                            model=self.model,
                            latency_ms=(time.monotonic() - start) * 1000,
                            parsed_json=parsed,
                            ok=True,
                        )
                    except json.JSONDecodeError:
                        return LLMResponse(
                            text=content,
                            provider=self.name,
                            model=self.model,
                            latency_ms=(time.monotonic() - start) * 1000,
                            ok=False,
                            error="INVALID_JSON",
                        )
                except httpx.HTTPError:
                    continue
        return LLMResponse(
            text="",
            provider=self.name,
            model=self.model,
            latency_ms=(time.monotonic() - start) * 1000,
            ok=False,
            error="LLM_TIMEOUT",
        )
