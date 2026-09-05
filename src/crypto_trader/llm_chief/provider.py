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
        retries: int = 1,
        max_tokens: int = 1200,
        thinking: bool = True,
        reasoning_effort: str = "low",
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
        self.last_attempt_count: int | None = None

    def healthy(self) -> bool:
        return bool(self.api_key)

    async def complete_json(
        self,
        *,
        prompt: str,
        temperature: float = 0.2,
        timeout_seconds: float = 30.0,
        retries: int = 1,
        max_tokens: int = 1200,
        thinking: bool = True,
        reasoning_effort: str = "low",
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
            last_invalid_response: LLMResponse | None = None
            for attempt in range(retries + 1):
                self.last_attempt_count = attempt + 1
                try:
                    response = await client.post(
                        "/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={
                            "model": self.model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                            "thinking": {
                                "type": "enabled" if thinking else "disabled"
                            },
                            **(
                                {"reasoning_effort": reasoning_effort}
                                if thinking
                                else {}
                            ),
                            "response_format": {"type": "json_object"},
                        },
                    )
                    if response.status_code != 200:
                        self.last_error = f"HTTP_{response.status_code}"
                        if response.status_code != 429 and response.status_code < 500:
                            break
                        continue
                    try:
                        payload = response.json()
                        content = payload["choices"][0]["message"]["content"]
                        if not isinstance(content, str):
                            raise TypeError("content is not text")
                    except (ValueError, KeyError, IndexError, TypeError):
                        self.last_error = "MALFORMED_PROVIDER_RESPONSE"
                        break
                    latency_ms = (time.monotonic() - start) * 1000
                    usage = payload.get("usage")
                    try:
                        parsed = json.loads(content)
                        if not isinstance(parsed, dict):
                            self.last_error = "INVALID_JSON_OBJECT"
                            self.last_latency_ms = latency_ms
                            self.last_token_usage = usage
                            break
                        result = LLMResponse(
                            text=content,
                            provider=self.name,
                            model=self.model,
                            latency_ms=latency_ms,
                            parsed_json=parsed,
                            ok=True,
                            token_usage=usage,
                        )
                        self.last_success_ts = datetime.now(UTC).isoformat()
                        self.last_error = None
                        self.last_latency_ms = result.latency_ms
                        self.last_token_usage = result.token_usage
                        return result
                    except json.JSONDecodeError:
                        self.last_error = (
                            "EMPTY_CONTENT"
                            if not content.strip()
                            else "PROSE_CONTAMINATION"
                            if content.lstrip().startswith("```")
                            else "INVALID_JSON"
                        )
                        self.last_latency_ms = latency_ms
                        self.last_token_usage = usage
                        last_invalid_response = LLMResponse(
                            text=content,
                            provider=self.name,
                            model=self.model,
                            latency_ms=latency_ms,
                            ok=False,
                            error=self.last_error,
                            token_usage=usage,
                        )
                        # Empty, truncated, or prose-contaminated JSON is a
                        # recoverable provider response, not a trading signal.
                        # Retry only within the caller's bounded retry budget;
                        # if every response is invalid the final result remains
                        # fail-closed and no TradePlan can be created.
                        if attempt < retries:
                            continue
                        return last_invalid_response
                except httpx.TimeoutException:
                    self.last_error = "LLM_TIMEOUT"
                    continue
                except httpx.HTTPError:
                    self.last_error = "LLM_TRANSPORT_ERROR"
                    continue
        if last_invalid_response is not None:
            return last_invalid_response
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
            "last_attempt_count": self.last_attempt_count,
        }
