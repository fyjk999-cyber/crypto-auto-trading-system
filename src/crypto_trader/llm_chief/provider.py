"""LLM provider abstraction. Business layer depends only on this interface."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

TRADING_MODEL_ENV = "TRADING_LLM_MODEL"
DEFAULT_TRADING_MODEL = "deepseek-flash"
FORBIDDEN_PRODUCTION_MODELS = frozenset({"deepseek-v4-pro", "deepseek-flash-high"})


def resolve_trading_model(explicit: str | None = None) -> str:
    """Canonical trading-model precedence and production model policy.

    ``TRADING_LLM_MODEL`` always wins over a generic ``LLM_MODEL`` and may only
    be ``deepseek-flash``. Forbidden production models fail closed instead of
    being silently used. An explicit constructor value is reserved for tests
    and dependency injection.
    """

    if explicit:
        return explicit
    trading_model = os.environ.get(TRADING_MODEL_ENV)
    if trading_model:
        if trading_model not in ALLOWED_TRADING_MODELS:
            raise ValueError(f"forbidden TRADING_LLM_MODEL: {trading_model}")
        return trading_model
    generic_model = os.environ.get("LLM_MODEL")
    if generic_model and generic_model in FORBIDDEN_PRODUCTION_MODELS:
        raise ValueError(f"forbidden production LLM_MODEL: {generic_model}")
    return generic_model or DEFAULT_TRADING_MODEL


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
    # Low-Risk V2 Phase 4: factual state binding so a stale model answer can
    # never be executed after fills/exits changed the position.
    state_version: str | None = None
    attempts: int | None = None
    served_by: str | None = None


PAUSE_ENV = "LLM_CALLS_PAUSED"
PAUSE_REASON_ENV = "LLM_CALLS_PAUSED_REASON"
_PAUSE_TRUE = frozenset({"1", "true", "yes", "on", "paused"})


@dataclass
class _ProviderCallPauseState:
    paused: bool = False
    reason: str | None = None
    paused_since: datetime | None = None
    outbound_calls_blocked: int = 0
    probe_suppressed: int = 0


_PAUSE_STATE = _ProviderCallPauseState()


def _sync_provider_pause_state() -> _ProviderCallPauseState:
    requested = os.environ.get(PAUSE_ENV, "").strip().lower() in _PAUSE_TRUE
    if requested:
        if not _PAUSE_STATE.paused:
            _PAUSE_STATE.paused = True
            _PAUSE_STATE.paused_since = datetime.now(UTC)
            _PAUSE_STATE.reason = (
                os.environ.get(PAUSE_REASON_ENV, "").strip() or "OPERATOR_PAUSE_REQUEST"
            )
    else:
        _PAUSE_STATE.paused = False
        _PAUSE_STATE.reason = None
        _PAUSE_STATE.paused_since = None
    return _PAUSE_STATE


def provider_calls_paused() -> bool:
    return _sync_provider_pause_state().paused


def provider_pause_snapshot() -> dict:
    state = _sync_provider_pause_state()
    return {
        "provider_calls_paused": state.paused,
        "pause_reason": state.reason,
        "paused_since": state.paused_since.isoformat() if state.paused_since else None,
        "outbound_calls_blocked": state.outbound_calls_blocked,
        "probe_suppressed": state.probe_suppressed,
    }


def record_outbound_blocked() -> None:
    _sync_provider_pause_state().outbound_calls_blocked += 1


def record_probe_suppressed() -> None:
    _sync_provider_pause_state().probe_suppressed += 1


def reset_provider_pause_counters() -> None:
    state = _sync_provider_pause_state()
    state.outbound_calls_blocked = 0
    state.probe_suppressed = 0


def paused_llm_response(provider: str, model: str) -> LLMResponse:
    return LLMResponse(
        text="",
        provider=provider,
        model=model,
        latency_ms=0.0,
        ok=False,
        error="LLM_CALLS_PAUSED_BY_CONFIG",
    )


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
        reasoning_effort: str = "high",
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
        self._configuration_error: str | None = None
        try:
            # Provider durability policy: forbidden production models fail
            # closed before any credential is attached.
            resolve_trading_model(model)
        except ValueError as exc:
            self._configuration_error = str(exc)
            self.model = model or "unconfigured"
            self.model_config_source = "unconfigured"
        else:
            try:
                trading_config = resolve_trading_llm_config(explicit_model=model)
                self.model = trading_config.model
                self.model_config_source = trading_config.config_source
            except DisallowedTradingLLMModel as exc:
                self._configuration_error = str(exc)
                self.model = model or "unconfigured"
                self.model_config_source = "unconfigured"
        resolved_api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if self._configuration_error is not None:
            resolved_api_key = None
        self.api_key = resolved_api_key
        self.base_url = base_url or os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
        self._transport = transport
        self.last_success_ts: str | None = None
        self.last_error: str | None = None
        self.last_latency_ms: float | None = None
        self.last_token_usage: dict | None = None
        self.last_attempt_count: int | None = None
        self._operation_diagnostics: dict[str, dict] = {}

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
        reasoning_effort: str = "high",
        operation: str = "completion",
    ) -> LLMResponse:
        if provider_calls_paused():
            record_outbound_blocked()
            result = paused_llm_response(self.name, self.model)
            self._record_operation(operation, result, attempts=0)
            return result
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
                            "thinking": {"type": "enabled" if attempt_thinking else "disabled"},
                            **({"reasoning_effort": reasoning_effort} if attempt_thinking else {}),
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
        self._record_operation(operation, result, attempts=self.last_attempt_count or retries + 1)
        return result

    def _record_operation(self, operation: str, response: LLMResponse, *, attempts: int) -> None:
        previous = self._operation_diagnostics.get(operation, {})
        self._operation_diagnostics[operation] = {
            "last_success_ts": (
                datetime.now(UTC).isoformat() if response.ok else previous.get("last_success_ts")
            ),
            "last_error": response.error,
            "last_latency_ms": response.latency_ms,
            "last_token_usage": response.token_usage,
            "last_attempt_count": attempts,
        }

    def diagnostics(self) -> dict:
        """Return non-secret operational state for health reporting."""

        return {
            "provider": self.name,
            "model": self.model,
            "configured": self.healthy(),
            "configuration_error": self._configuration_error,
            "last_success_ts": self.last_success_ts,
            "last_error": self.last_error,
            "last_latency_ms": self.last_latency_ms,
            "last_token_usage": self.last_token_usage,
            "last_attempt_count": self.last_attempt_count,
            "operations": {
                operation: dict(values) for operation, values in self._operation_diagnostics.items()
            },
        }


class GLMProvider:
    """Backup Core LLM provider (Zhipu GLM, OpenAI-compatible endpoint).

    Same ``LLMProvider`` Protocol as DeepSeek: one bounded immediate retry and
    fail-closed JSON handling. Callers must pass Freshest factual state; this
    provider itself never replays a stale prompt.
    """

    name = "glm"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        transport=None,
    ) -> None:
        self.api_key = api_key or os.environ.get("GLM_API_KEY")
        self.model = model or os.environ.get("GLM_MODEL", "glm-4-flash")
        self.base_url = base_url or os.environ.get(
            "GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
        )
        self._transport = transport
        self.last_success_ts: str | None = None
        self.last_error: str | None = None
        self.last_latency_ms: float | None = None
        self.last_token_usage: dict | None = None
        self.last_attempt_count: int | None = None
        self._operation_diagnostics: dict[str, dict] = {}

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
        reasoning_effort: str = "high",
        operation: str = "completion",
    ) -> LLMResponse:
        if provider_calls_paused():
            record_outbound_blocked()
            result = paused_llm_response(self.name, self.model)
            self._record_operation(operation, result, attempts=0)
            return result
        import json
        import time

        del thinking, reasoning_effort  # GLM endpoint takes a single JSON contract
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
            last_invalid: LLMResponse | None = None
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
                    except json.JSONDecodeError:
                        self.last_error = "INVALID_JSON"
                        self.last_latency_ms = latency_ms
                        self.last_token_usage = usage
                        last_invalid = LLMResponse(
                            text=content,
                            provider=self.name,
                            model=self.model,
                            latency_ms=latency_ms,
                            ok=False,
                            error=self.last_error,
                            token_usage=usage,
                        )
                        if attempt < retries:
                            continue
                        self._record_operation(operation, last_invalid, attempts=attempt + 1)
                        return last_invalid
                    if not isinstance(parsed, dict):
                        self.last_error = "INVALID_JSON_OBJECT"
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
                    self.last_latency_ms = latency_ms
                    self.last_token_usage = usage
                    self._record_operation(operation, result, attempts=attempt + 1)
                    return result
                except httpx.TimeoutException:
                    self.last_error = "LLM_TIMEOUT"
                    continue
                except httpx.HTTPError:
                    self.last_error = "LLM_TRANSPORT_ERROR"
                    continue
            if last_invalid is not None:
                return last_invalid
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

    def _record_operation(self, operation: str, response: LLMResponse, *, attempts: int) -> None:
        previous = self._operation_diagnostics.get(operation, {})
        self._operation_diagnostics[operation] = {
            "last_success_ts": (
                datetime.now(UTC).isoformat() if response.ok else previous.get("last_success_ts")
            ),
            "last_error": response.error,
            "last_latency_ms": response.latency_ms,
            "last_token_usage": response.token_usage,
            "last_attempt_count": attempts,
        }

    def diagnostics(self) -> dict:
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
                operation: dict(values) for operation, values in self._operation_diagnostics.items()
            },
        }


# --- Canonical trading-system LLM policy (DEEPSEEK_FLASH_HIGH) ---------------
CANONICAL_TRADING_PROVIDER = "deepseek"
CANONICAL_TRADING_MODEL = "deepseek-flash"
CANONICAL_THINKING = True
CANONICAL_REASONING_EFFORT = "high"
ALLOWED_TRADING_MODELS = frozenset({"deepseek-flash"})


class DisallowedTradingLLMModel(RuntimeError):
    """Raised when TRADING_LLM_MODEL is not on the trading allowlist."""


@dataclass(frozen=True)
class TradingLLMConfig:
    provider: str
    model: str
    thinking: bool
    reasoning_effort: str
    config_source: str


def resolve_trading_llm_config(explicit_model: str | None = None) -> TradingLLMConfig:
    """One canonical resolver; generic LLM_MODEL is ignored for trading."""
    requested = explicit_model or os.environ.get("TRADING_LLM_MODEL")
    if requested:
        if requested not in ALLOWED_TRADING_MODELS:
            raise DisallowedTradingLLMModel(
                "DISALLOWED_TRADING_LLM_MODEL "
                f"requested_model={requested} canonical_model={CANONICAL_TRADING_MODEL} "
                "config_source=TRADING_LLM_MODEL"
            )
        return TradingLLMConfig(
            provider=CANONICAL_TRADING_PROVIDER,
            model=requested,
            thinking=CANONICAL_THINKING,
            reasoning_effort=CANONICAL_REASONING_EFFORT,
            config_source="TRADING_LLM_MODEL",
        )
    return TradingLLMConfig(
        provider=CANONICAL_TRADING_PROVIDER,
        model=CANONICAL_TRADING_MODEL,
        thinking=CANONICAL_THINKING,
        reasoning_effort=CANONICAL_REASONING_EFFORT,
        config_source="canonical_default",
    )
