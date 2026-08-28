"""Single canonical LLM gateway for Live, Daily Learning and Evolution brains."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from crypto_trader.domain.identifiers import new_id
from crypto_trader.llm_runtime.contracts import (
    CandidateReasoningResult,
    DailyReviewReasoning,
    HypothesisReasoningResult,
    LessonExtractionResult,
    LiveAnalysisResult,
    LLMErrorCode,
    LLMRequest,
    LLMResponse,
    ModelRoute,
    ProviderConfig,
    ProviderUpsert,
    ResearchReasoningResult,
)
from crypto_trader.llm_runtime.domain_models import DomainModelRuntime, TradingAnalysisResult
from crypto_trader.llm_runtime.provider import OpenAICompatibleProvider
from crypto_trader.llm_runtime.repository import LLMRepository
from crypto_trader.llm_runtime.secrets import EncryptedFileSecretStore


@dataclass
class CircuitState:
    failures: int = 0
    opened_at: float | None = None


class LLMGateway:
    def __init__(
        self,
        repository: LLMRepository,
        secret_store: EncryptedFileSecretStore,
        *,
        provider_factory=None,
        sleep=asyncio.sleep,
        circuit_threshold: int = 3,
        circuit_reset_seconds: float = 60.0,
    ) -> None:
        self.repository = repository
        self.secret_store = secret_store
        self.provider_factory = provider_factory or (lambda _config: OpenAICompatibleProvider())
        self.sleep = sleep
        self.circuit_threshold = circuit_threshold
        self.circuit_reset_seconds = circuit_reset_seconds
        self.providers: dict[str, ProviderConfig] = {}
        self.routes: dict[str, ModelRoute] = {}
        self.circuits: dict[str, CircuitState] = {}
        self.last_check: dict[str, dict] = {}
        self._config_lock = asyncio.Lock()

    async def reload(self) -> None:
        async with self._config_lock:
            self.providers = {
                provider.provider_id: provider
                for provider in await self.repository.list_providers()
            }
            self.routes = {route.route_name: route for route in await self.repository.list_routes()}

    async def save_provider(self, payload: ProviderUpsert) -> dict:
        existing = await self.repository.get_provider(payload.provider_id)
        secret_ref = (
            existing.api_key_secret_ref if existing else f"llm:{payload.provider_id}:api-key"
        )
        if payload.api_key:
            self.secret_store.set(secret_ref, payload.api_key)
        elif existing is None:
            raise ValueError("api_key is required for a new provider")
        config = ProviderConfig(
            **payload.model_dump(exclude={"api_key"}), api_key_secret_ref=secret_ref
        )
        await self.repository.upsert_provider(config)
        await self.reload()
        return self.safe_provider(config)

    async def delete_provider(self, provider_id: str) -> None:
        config = await self.repository.get_provider(provider_id)
        if config:
            self.secret_store.delete(config.api_key_secret_ref)
        await self.repository.delete_provider(provider_id)
        await self.reload()

    async def save_routes(self, routes: list[ModelRoute]) -> list[dict]:
        for route in routes:
            if route.provider_id not in self.providers:
                raise ValueError(f"unknown provider: {route.provider_id}")
        await self.repository.replace_routes(routes)
        await self.reload()
        return [route.model_dump() for route in routes]

    async def invoke(
        self, request: LLMRequest, response_model: type[BaseModel] | None = None
    ) -> LLMResponse:
        invocation_id = new_id("llm")
        route = self.routes.get(request.route)
        if route is None or not route.enabled:
            return await self._failure(
                invocation_id, request, LLMErrorCode.UNKNOWN_ROUTE, route=route
            )
        provider = self.providers.get(route.provider_id)
        if provider is None:
            return await self._failure(
                invocation_id, request, LLMErrorCode.NOT_CONFIGURED, route=route
            )
        if not provider.enabled:
            return await self._failure(
                invocation_id,
                request,
                LLMErrorCode.DISABLED_PROVIDER,
                route=route,
                provider=provider,
            )
        api_key = self.secret_store.get(provider.api_key_secret_ref)
        if not api_key:
            return await self._failure(
                invocation_id,
                request,
                LLMErrorCode.NOT_CONFIGURED,
                route=route,
                provider=provider,
            )
        if self._circuit_open(provider.provider_id):
            return await self._failure(
                invocation_id,
                request,
                LLMErrorCode.CIRCUIT_OPEN,
                route=route,
                provider=provider,
            )

        transport = self.provider_factory(provider)
        result = None
        started = time.monotonic()
        for attempt in range(provider.max_retries + 1):
            result = await transport.complete(
                config=provider, route=route, api_key=api_key, prompt=request.prompt
            )
            if result.ok or not result.retryable or attempt >= provider.max_retries:
                break
            await self.sleep(min(2.0, 0.1 * (2**attempt)))
        assert result is not None
        latency_ms = (time.monotonic() - started) * 1000
        if not result.ok:
            self._record_failure(provider.provider_id)
            return await self._failure(
                invocation_id,
                request,
                result.error_code or LLMErrorCode.PROVIDER_UNAVAILABLE,
                route=route,
                provider=provider,
                latency_ms=latency_ms,
            )
        try:
            content: dict[str, Any] = result.content or {}
            if response_model is not None:
                content = response_model.model_validate(content).model_dump(mode="json")
        except ValidationError:
            self._record_failure(provider.provider_id)
            return await self._failure(
                invocation_id,
                request,
                LLMErrorCode.INVALID_RESPONSE,
                route=route,
                provider=provider,
                latency_ms=latency_ms,
            )
        self.circuits[provider.provider_id] = CircuitState()
        response = LLMResponse(
            invocation_id=invocation_id,
            ok=True,
            route=request.route,
            provider=provider.provider_id,
            model=route.model_name,
            content=content,
            latency_ms=latency_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
        )
        await self._record_usage(request, response)
        self.last_check[provider.provider_id] = {
            "health": "HEALTHY",
            "latency_ms": round(latency_ms, 2),
            "checked_at": response.checked_at,
            "error_code": None,
        }
        return response

    async def test_provider(self, provider_id: str) -> LLMResponse:
        provider = self.providers.get(provider_id)
        if provider is None:
            return LLMResponse(
                invocation_id=new_id("llm"),
                ok=False,
                route="provider_test",
                error_code=LLMErrorCode.NOT_CONFIGURED,
            )
        temporary_route = ModelRoute(
            route_name="provider_test",
            provider_id=provider_id,
            model_name=provider.default_model,
            max_tokens=32,
            timeout_seconds=provider.timeout_seconds,
        )
        previous = self.routes.get("provider_test")
        self.routes["provider_test"] = temporary_route

        class HealthResponse(BaseModel):
            ok: bool

        try:
            return await self.invoke(
                LLMRequest(
                    route="provider_test",
                    brain="LIVE",
                    prompt='Return exactly one JSON object: {"ok": true}',
                ),
                HealthResponse,
            )
        finally:
            if previous is None:
                self.routes.pop("provider_test", None)
            else:
                self.routes["provider_test"] = previous

    async def test_unsaved_provider(self, payload: ProviderUpsert) -> LLMResponse:
        if not payload.api_key:
            return LLMResponse(
                invocation_id=new_id("llm"),
                ok=False,
                route="provider_test",
                provider=payload.provider_id,
                model=payload.default_model,
                error_code=LLMErrorCode.NOT_CONFIGURED,
            )
        config = ProviderConfig(
            **payload.model_dump(exclude={"api_key"}),
            api_key_secret_ref="ephemeral:test-only",
        )
        route = ModelRoute(
            route_name="provider_test",
            provider_id=config.provider_id,
            model_name=config.default_model,
            max_tokens=32,
            timeout_seconds=config.timeout_seconds,
        )
        started = time.monotonic()
        result = await self.provider_factory(config).complete(
            config=config, route=route, api_key=payload.api_key, prompt='Return {"ok": true}'
        )
        response = LLMResponse(
            invocation_id=new_id("llm"),
            ok=bool(result.ok and result.content and result.content.get("ok") is True),
            route="provider_test",
            provider=config.provider_id,
            model=config.default_model,
            latency_ms=(time.monotonic() - started) * 1000,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
            error_code=None
            if result.ok and result.content and result.content.get("ok") is True
            else result.error_code or LLMErrorCode.INVALID_RESPONSE,
        )
        await self._record_usage(
            LLMRequest(route="provider_test", brain="LIVE", prompt="provider qualification"),
            response,
        )
        return response

    async def qualify_configured_routes(self) -> list[LLMResponse]:
        """Exercise configured routes with inert evidence only.

        This is deliberately a control-plane check: it invokes no trading,
        research mutation, order, or exchange code.
        """
        checks = (
            (
                "live_analysis",
                "LIVE",
                LiveAnalysisResult,
                (
                    "Return JSON only: "
                    '{"decision_id":"qualification","symbol":"BTCUSDT",'
                    '"action":"NO_TRADE","market_regime":"TEST",'
                    '"thesis":"qualification only","reason_codes":["QUALIFICATION"]}'
                ),
            ),
            (
                "daily_review",
                "DAILY",
                DailyReviewReasoning,
                (
                    "Return JSON only: "
                    '{"summary":"qualification only","error_categories":[],'
                    '"evidence_refs":["qualification"]}'
                ),
            ),
            (
                "daily_lesson_extraction",
                "DAILY",
                LessonExtractionResult,
                (
                    "Return JSON only: "
                    '{"lessons":["qualification only"],"evidence_refs":["qualification"]}'
                ),
            ),
            (
                "evolution_research",
                "EVOLUTION",
                ResearchReasoningResult,
                (
                    "Return JSON only: "
                    '{"summary":"qualification only","evidence_refs":["qualification"],'
                    '"proposals":[]}'
                ),
            ),
            (
                "evolution_hypothesis",
                "EVOLUTION",
                HypothesisReasoningResult,
                (
                    "Return JSON only: "
                    '{"hypothesis":"qualification only",'
                    '"falsification_test":"not executed",'
                    '"evidence_refs":["qualification"]}'
                ),
            ),
            (
                "evolution_candidate_reasoning",
                "EVOLUTION",
                CandidateReasoningResult,
                (
                    "Return JSON only: "
                    '{"rationale":"qualification only","proposed_changes":[],'
                    '"validation_requirements":[]}'
                ),
            ),
        )
        return [
            await self.invoke(LLMRequest(route=route, brain=brain, prompt=prompt), schema)
            for route, brain, schema, prompt in checks
        ]

    def status(self) -> dict:
        enabled = [provider for provider in self.providers.values() if provider.enabled]
        health_values = [
            self.last_check.get(provider.provider_id, {}).get("health") for provider in enabled
        ]
        health = (
            "NOT_CONFIGURED"
            if not enabled
            else "HEALTHY"
            if any(value == "HEALTHY" for value in health_values)
            else "DEGRADED"
            if any(value for value in health_values)
            else "UNVERIFIED"
        )
        return {
            "configured": bool(enabled),
            "health": health,
            "providers": len(enabled),
            "routes": len([route for route in self.routes.values() if route.enabled]),
        }

    def safe_provider(self, config: ProviderConfig) -> dict:
        secret = self.secret_store.get(config.api_key_secret_ref)
        return {
            "provider_id": config.provider_id,
            "provider_type": config.provider_type,
            "display_name": config.display_name,
            "base_url": config.base_url,
            "api_key_masked": self.secret_store.mask(secret),
            "configured": bool(secret),
            "default_model": config.default_model,
            "enabled": config.enabled,
            "timeout_seconds": config.timeout_seconds,
            "max_retries": config.max_retries,
            **self.last_check.get(config.provider_id, {}),
        }

    def _circuit_open(self, provider_id: str) -> bool:
        state = self.circuits.setdefault(provider_id, CircuitState())
        if state.opened_at is None:
            return False
        if time.monotonic() - state.opened_at >= self.circuit_reset_seconds:
            self.circuits[provider_id] = CircuitState()
            return False
        return True

    def _record_failure(self, provider_id: str) -> None:
        state = self.circuits.setdefault(provider_id, CircuitState())
        state.failures += 1
        if state.failures >= self.circuit_threshold:
            state.opened_at = time.monotonic()

    async def _failure(
        self,
        invocation_id: str,
        request: LLMRequest,
        error_code: LLMErrorCode,
        *,
        route: ModelRoute | None = None,
        provider: ProviderConfig | None = None,
        latency_ms: float = 0.0,
    ) -> LLMResponse:
        response = LLMResponse(
            invocation_id=invocation_id,
            ok=False,
            route=request.route,
            provider=provider.provider_id if provider else route.provider_id if route else "",
            model=route.model_name if route else "",
            latency_ms=latency_ms,
            error_code=error_code,
        )
        await self._record_usage(request, response)
        if provider:
            self.last_check[provider.provider_id] = {
                "health": "DEGRADED",
                "latency_ms": round(latency_ms, 2),
                "checked_at": response.checked_at,
                "error_code": error_code.value,
            }
        return response

    async def _record_usage(self, request: LLMRequest, response: LLMResponse) -> None:
        await self.repository.record_usage(
            {
                "invocation_id": response.invocation_id,
                "timestamp": datetime.now(UTC),
                "brain": request.brain,
                "route": request.route,
                "provider": response.provider,
                "model": response.model,
                "latency_ms": response.latency_ms,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "total_tokens": response.total_tokens,
                "success": response.ok,
                "error_classification": response.error_code.value if response.error_code else None,
                "correlation_id": request.correlation_id,
                "request_hash": hashlib.sha256(request.prompt.encode()).hexdigest(),
            }
        )


class GatewayProviderAdapter:
    """Adapts the canonical gateway to the existing ChiefTrader provider protocol."""

    name = "llm_gateway"

    def __init__(
        self,
        gateway: LLMGateway,
        route: str = "live_analysis",
        domain_runtime: DomainModelRuntime | None = None,
    ) -> None:
        self.gateway = gateway
        self.route = route
        self.domain_runtime = domain_runtime or DomainModelRuntime(gateway)

    def route_ready(self) -> bool:
        """True only when this adapter's route is resolvable to a usable key."""
        route = self.gateway.routes.get(self.route)
        if route is None or not route.enabled:
            return False
        provider = self.gateway.providers.get(route.provider_id)
        if provider is None or not provider.enabled:
            return False
        return bool(self.gateway.secret_store.get(provider.api_key_secret_ref))

    def healthy(self) -> bool:
        """LLM availability for the Live entry path.

        AI-FIRST doctrine: the Live LLM is AVAILABLE when the route resolves
        to an enabled provider with a usable secret. A missing in-process
        health probe (UNVERIFIED) must never be interpreted as "LLM
        unavailable" -- that would silently stall every decision after a
        restart. Actual invocation failures remain fail-closed at call time
        (gateway invoke error handling) and are surfaced through llm_usage.
        """
        return self.route_ready()

    @property
    def domain_model_version(self) -> str:
        return self.domain_runtime.profile_for_route(self.route).display_name

    async def complete_json(
        self,
        *,
        prompt: str,
        temperature: float = 0.2,
        timeout_seconds: float = 30.0,
        retries: int = 2,
    ):
        from crypto_trader.llm_chief.provider import LLMResponse as ChiefResponse

        response = await self.gateway.invoke(
            LLMRequest(route=self.route, brain="LIVE", prompt=prompt)
        )
        return ChiefResponse(
            text=json.dumps(response.content or {}),
            provider=response.provider,
            model=response.model,
            latency_ms=response.latency_ms,
            parsed_json=response.content,
            ok=response.ok,
            error=response.error_code.value if response.error_code else None,
            invocation_id=response.invocation_id,
        )

    async def complete_domain_analysis(self, *, context: dict):
        """The Live profile produces advisory structured analysis only."""
        from crypto_trader.llm_chief.provider import LLMResponse as ChiefResponse

        response = await self.domain_runtime.invoke(
            route=self.route,
            context=context,
            response_model=TradingAnalysisResult,
        )
        return ChiefResponse(
            text=json.dumps(response.content or {}),
            provider=response.provider,
            model=response.model,
            latency_ms=response.latency_ms,
            parsed_json=response.content,
            ok=response.ok,
            error=response.error_code.value if response.error_code else None,
            invocation_id=response.invocation_id,
        )
