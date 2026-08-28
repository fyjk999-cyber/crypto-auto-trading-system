"""OpenAI-compatible provider transport shared by OpenAI, DeepSeek and custom endpoints."""

from __future__ import annotations

import json
import time
from typing import Protocol

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend

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


class DoHNetworkBackend(httpcore.AsyncNetworkBackend):
    """Resolves hosts via a JSON DoH endpoint before opening the TCP socket.

    Some local VPN/TUN clients answer DNS with fake IPs that hang TLS
    handshakes for specific providers. Resolving through DoH and dialing the
    real address (TLS SNI and certificate validation stay bound to the
    original hostname) restores correct routing. Opt-in only.
    """

    def __init__(self, doh_endpoint: str, doh_client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self.doh_endpoint = doh_endpoint.rstrip("/")
        self._doh_client = doh_client or httpx.AsyncClient(timeout=5.0)
        self._owns_client = doh_client is None
        self._inner = AutoBackend()  # concrete TCP backend to delegate to

    async def _resolve(self, host: str) -> str | None:
        try:
            response = await self._doh_client.get(
                self.doh_endpoint, params={"name": host, "type": "A"}
            )
            answers = response.json().get("Answer") or []
            for answer in answers:
                if answer.get("type") == 1 and answer.get("data"):
                    return str(answer["data"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None
        return None

    async def connect_tcp(self, host, port, timeout=None, local_address=None,  # noqa: ASYNC109
                          socket_options=None):
        resolved = await self._resolve(str(host))
        return await self._inner.connect_tcp(
            resolved or str(host), port, timeout, local_address, socket_options
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._doh_client.aclose()


class DoHTransport(httpx.AsyncHTTPTransport):
    """httpx transport that dials DoH-resolved addresses; SNI/TLS unchanged."""

    def __init__(self, doh_endpoint: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._pool = httpcore.AsyncConnectionPool(
            network_backend=DoHNetworkBackend(doh_endpoint)
        )


class OpenAICompatibleProvider:
    def __init__(self, client_factory=None, doh_endpoint: str | None = None) -> None:
        self.client_factory = client_factory
        self.doh_endpoint = doh_endpoint

    def _build_client(self, config: ProviderConfig, route: ModelRoute) -> httpx.AsyncClient:
        kwargs: dict = {"base_url": config.base_url, "timeout": route.timeout_seconds}
        if self.doh_endpoint:
            kwargs["transport"] = DoHTransport(self.doh_endpoint)
        return httpx.AsyncClient(**kwargs)

    async def complete(
        self, *, config: ProviderConfig, route: ModelRoute, api_key: str, prompt: str
    ) -> ProviderResult:
        started = time.monotonic()
        owns_client = self.client_factory is None
        client = (
            self._build_client(config, route)
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
