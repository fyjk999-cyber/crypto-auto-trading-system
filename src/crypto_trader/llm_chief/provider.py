"""LLM provider abstraction. Business layer depends only on this interface."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


def prompt_cache_hit_rate(
    hit_tokens: int | None, miss_tokens: int | None
) -> float | None:
    """Official DeepSeek prompt-cache formula.

    UNKNOWN (``None``) is returned when either provider field is missing or the
    denominator is zero.  It is never coerced to 0.0.
    """
    if hit_tokens is None or miss_tokens is None:
        return None
    total = int(hit_tokens) + int(miss_tokens)
    if total <= 0:
        return None
    return int(hit_tokens) / total


def _usage_token(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
        operation: str = "completion",
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
        self._operation_diagnostics: dict[str, dict] = {}
        self._cache_totals: dict[str, int] = {
            "hit_tokens": 0,
            "miss_tokens": 0,
            "known_calls": 0,
            "unknown_calls": 0,
        }
        self._operation_cache: dict[str, dict[str, int]] = {}

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
        operation: str = "completion",
    ) -> LLMResponse:
        import json
        import time

        if not self.api_key:
            result = LLMResponse(
                text="",
                provider=self.name,
                model=self.model,
                latency_ms=0,
                ok=False,
                error="NO_API_KEY",
            )
            self._record_operation(operation, result, attempts=0)
            return result
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
                # If a reasoning response spends its output budget without a
                # JSON body, the single bounded recovery attempt asks the same
                # provider for JSON without hidden reasoning. It remains a
                # real provider response and still fails closed if malformed.
                attempt_thinking = thinking and last_invalid_response is None
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
                                "type": "enabled" if attempt_thinking else "disabled"
                            },
                            **(
                                {"reasoning_effort": reasoning_effort}
                                if attempt_thinking
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
                        self._record_operation(operation, result, attempts=attempt + 1)
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
                        self._record_operation(
                            operation, last_invalid_response, attempts=attempt + 1
                        )
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
        self._record_operation(
            operation, result, attempts=self.last_attempt_count or retries + 1
        )
        return result

    def _record_operation(
        self, operation: str, response: LLMResponse, *, attempts: int
    ) -> None:
        previous = self._operation_diagnostics.get(operation, {})
        usage = response.token_usage or {}
        hit = _usage_token(usage.get("prompt_cache_hit_tokens"))
        miss = _usage_token(usage.get("prompt_cache_miss_tokens"))
        if hit is None or miss is None:
            cache = {
                "status": "UNKNOWN",
                "reason": "PROVIDER_FIELDS_MISSING",
                "hit_tokens": None,
                "miss_tokens": None,
                "eligible_prompt_tokens": None,
                "hit_rate": None,
            }
            self._cache_totals["unknown_calls"] += 1
            operation_cache = self._operation_cache.setdefault(
                operation,
                {
                    "hit_tokens": 0,
                    "miss_tokens": 0,
                    "known_calls": 0,
                    "unknown_calls": 0,
                },
            )
            operation_cache["unknown_calls"] += 1
        else:
            rate = prompt_cache_hit_rate(hit, miss)
            cache = {
                "status": "KNOWN" if rate is not None else "UNKNOWN",
                "reason": None if rate is not None else "ZERO_DENOMINATOR",
                "hit_tokens": hit,
                "miss_tokens": miss,
                "eligible_prompt_tokens": hit + miss,
                "hit_rate": rate,
            }
            self._cache_totals["hit_tokens"] += hit
            self._cache_totals["miss_tokens"] += miss
            self._cache_totals["known_calls"] += 1
            operation_cache = self._operation_cache.setdefault(
                operation,
                {
                    "hit_tokens": 0,
                    "miss_tokens": 0,
                    "known_calls": 0,
                    "unknown_calls": 0,
                },
            )
            operation_cache["hit_tokens"] += hit
            operation_cache["miss_tokens"] += miss
            operation_cache["known_calls"] += 1
        self._operation_diagnostics[operation] = {
            "last_success_ts": (
                datetime.now(UTC).isoformat()
                if response.ok
                else previous.get("last_success_ts")
            ),
            "last_error": response.error,
            "last_latency_ms": response.latency_ms,
            "last_token_usage": response.token_usage,
            "last_attempt_count": attempts,
            "prompt_cache": cache,
        }

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
            "operations": {
                operation: dict(values)
                for operation, values in self._operation_diagnostics.items()
            },
            "prompt_cache": self._prompt_cache_snapshot(),
        }

    def _prompt_cache_snapshot(self) -> dict:
        known = int(self._cache_totals.get("known_calls", 0))
        hit = int(self._cache_totals.get("hit_tokens", 0))
        miss = int(self._cache_totals.get("miss_tokens", 0))
        overall_rate = prompt_cache_hit_rate(hit, miss) if known else None
        operations: dict[str, dict] = {}
        for operation, values in self._operation_cache.items():
            op_known = int(values.get("known_calls", 0))
            op_hit = int(values.get("hit_tokens", 0))
            op_miss = int(values.get("miss_tokens", 0))
            op_rate = prompt_cache_hit_rate(op_hit, op_miss) if op_known else None
            operations[operation] = {
                "status": "KNOWN" if op_rate is not None else "UNKNOWN",
                "hit_tokens": op_hit if op_known else None,
                "miss_tokens": op_miss if op_known else None,
                "eligible_prompt_tokens": (op_hit + op_miss) if op_known else None,
                "hit_rate": op_rate,
                "known_calls": op_known,
                "unknown_calls": int(values.get("unknown_calls", 0)),
            }
        return {
            "status": "KNOWN" if overall_rate is not None else "UNKNOWN",
            "hit_tokens": hit if known else None,
            "miss_tokens": miss if known else None,
            "eligible_prompt_tokens": (hit + miss) if known else None,
            "hit_rate": overall_rate,
            "known_calls": known,
            "unknown_calls": int(self._cache_totals.get("unknown_calls", 0)),
            "operations": operations,
        }
