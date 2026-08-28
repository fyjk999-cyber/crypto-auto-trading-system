"""OpenAI-compatible provider transport shared by OpenAI, DeepSeek and custom endpoints."""

from __future__ import annotations

import json
import time
from typing import Protocol

import httpx

from crypto_trader.llm_runtime.contracts import (
    LLMErrorCode,
    ModelRoute,
    ProviderConfig,
    ProviderResult,
)


class ProviderTransport(Protocol):
    async def complete(
        self, *, config: ProviderConfig, route: ModelRoute, api_key: str, prompt: str
    ) -> ProviderResult: ...


class OpenAICompatibleProvider:
    def __init__(self, client_factory=None) -> None:
        self.client_factory = client_factory

    async def complete(
        self, *, config: ProviderConfig, route: ModelRoute, api_key: str, prompt: str
    ) -> ProviderResult:
        started = time.monotonic()
        owns_client = self.client_factory is None
        client = (
            httpx.AsyncClient(base_url=config.base_url, timeout=route.timeout_seconds)
            if owns_client
            else self.client_factory(config, route)
        )
        try:
            response = await client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": route.model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": route.temperature,
                    "max_tokens": route.max_tokens,
                    "response_format": {"type": "json_object"},
                },
            )
        except httpx.TimeoutException:
            return self._failed(started, LLMErrorCode.TIMEOUT, retryable=True)
        except httpx.NetworkError:
            return self._failed(started, LLMErrorCode.NETWORK_ERROR, retryable=True)
        finally:
            if owns_client:
                await client.aclose()
        if response.status_code in (401, 403):
            return self._failed(started, LLMErrorCode.AUTHENTICATION_FAILED)
        if response.status_code == 404:
            return self._failed(started, LLMErrorCode.INVALID_MODEL)
        if response.status_code == 429:
            return self._failed(started, LLMErrorCode.RATE_LIMITED, retryable=True)
        if response.status_code >= 500:
            return self._failed(started, LLMErrorCode.PROVIDER_UNAVAILABLE, retryable=True)
        if response.status_code != 200:
            return self._failed(started, LLMErrorCode.PROVIDER_UNAVAILABLE)
        try:
            payload = response.json()
            raw_content = payload["choices"][0]["message"]["content"]
            content = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
            usage = payload.get("usage") or {}
            if not isinstance(content, dict):
                raise ValueError("content is not an object")
            return ProviderResult(
                ok=True,
                content=content,
                latency_ms=(time.monotonic() - started) * 1000,
                input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                output_tokens=int(usage.get("completion_tokens", 0) or 0),
                total_tokens=int(usage.get("total_tokens", 0) or 0),
            )
        except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
            return self._failed(started, LLMErrorCode.INVALID_RESPONSE)

    @staticmethod
    def _failed(
        started: float, error_code: LLMErrorCode, *, retryable: bool = False
    ) -> ProviderResult:
        return ProviderResult(
            ok=False,
            latency_ms=(time.monotonic() - started) * 1000,
            error_code=error_code,
            retryable=retryable,
        )
