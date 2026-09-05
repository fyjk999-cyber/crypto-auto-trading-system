"""LLM provider abstraction. Business layer depends only on this interface."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
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
    token_usage: dict | None = None


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

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        transport=None,
    ) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        self.model = model or os.environ.get("LLM_MODEL", "deepseek-chat")
        self.base_url = base_url or os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
        self._transport = transport
        self.last_success_ts: str | None = None
        self.last_error: str | None = None
        self.last_latency_ms: float | None = None
        self.last_token_usage: dict | None = None

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
            base_url=self.base_url,
            timeout=timeout_seconds,
            transport=self._transport,
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
                            "response_format": {"type": "json_object"},
                        },
                    )
                    if response.status_code != 200:
                        self.last_error = f"HTTP_{response.status_code}"
                        if response.status_code != 429 and response.status_code < 500:
                            break
                        continue
                    payload = response.json()
                    content = payload["choices"][0]["message"]["content"]
                    try:
                        parsed = json.loads(content)
                        if not isinstance(parsed, dict):
                            self.last_error = "INVALID_JSON_OBJECT"
                            break
                        result = LLMResponse(
                            text=content,
                            provider=self.name,
                            model=self.model,
                            latency_ms=(time.monotonic() - start) * 1000,
                            parsed_json=parsed,
                            ok=True,
                            token_usage=payload.get("usage"),
                        )
                        self.last_success_ts = datetime.now(UTC).isoformat()
                        self.last_error = None
                        self.last_latency_ms = result.latency_ms
                        self.last_token_usage = result.token_usage
                        return result
                    except json.JSONDecodeError:
                        self.last_error = "INVALID_JSON"
                        return LLMResponse(
                            text=content,
                            provider=self.name,
                            model=self.model,
                            latency_ms=(time.monotonic() - start) * 1000,
                            ok=False,
                            error="INVALID_JSON",
                        )
                except httpx.TimeoutException:
                    self.last_error = "LLM_TIMEOUT"
                    continue
                except httpx.HTTPError:
                    self.last_error = "LLM_TRANSPORT_ERROR"
                    continue
        result = LLMResponse(
            text="",
            provider=self.name,
            model=self.model,
            latency_ms=(time.monotonic() - start) * 1000,
            ok=False,
            error=self.last_error or "LLM_PROVIDER_ERROR",
        )
        self.last_latency_ms = result.latency_ms
        return result

    def diagnostics(self) -> dict:
        """Return non-secret operational state for health reporting."""

        return {
            "provider": self.name,
            "model": self.model,
            "configured": self.healthy(),
            "last_success_ts": self.last_success_ts,
            "last_error": self.last_error,
            "last_latency_ms": self.last_latency_ms,
            "last_token_usage": self.last_token_usage,
        }
