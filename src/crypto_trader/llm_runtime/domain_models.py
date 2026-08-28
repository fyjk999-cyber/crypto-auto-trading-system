"""Versioned domain reasoning profiles above the provider transport.

Profiles constrain a general-purpose provider model. They are not additional
Brains and cannot access execution or exchange services.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from crypto_trader.domain.identifiers import new_id
from crypto_trader.llm_runtime.contracts import LLMRequest


class TradingAnalysisResult(BaseModel):
    """Validated advisory analysis; downstream decision/risk layers remain authoritative."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    symbol: str
    action: Literal["LONG", "SHORT", "NO_TRADE", "WAIT"]
    market_regime: str = "UNKNOWN"
    thesis: str = ""
    reason_codes: list[str] = Field(default_factory=list)
    position_size_request: float = 0.0
    leverage_request: float = 0.0
    raw_llm_confidence: float = 0.0


class DomainModelProfile(BaseModel):
    """A versioned constrained-reasoning profile over a base provider model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain_model_id: str
    display_name: str
    version: str
    brain: Literal["LIVE", "DAILY", "EVOLUTION"]
    routes: tuple[str, ...]
    prompt_version: str
    context_profile_version: str
    factor_profile_version: str
    tool_policy_version: str
    memory_retrieval_policy_version: str
    output_schema_version: str
    token_budget: int
    reasoning_policy: str
    allowed_tools: tuple[str, ...] = ("read_only_context",)

    def to_dict(self, route_bindings: dict[str, dict[str, str]]) -> dict[str, Any]:
        routes = [{"route": route, **route_bindings.get(route, {})} for route in self.routes]
        return {**self.model_dump(mode="json"), "routes": routes}


CRYPTO_TRADER_LIVE = DomainModelProfile(
    domain_model_id="crypto-trader-live",
    display_name="CryptoTrader-Live-v1",
    version="v1",
    brain="LIVE",
    routes=("live_analysis",),
    prompt_version="live-prompt-v1",
    context_profile_version="live-context-v1",
    factor_profile_version="factor-profile-v1",
    tool_policy_version="read-only-tools-v1",
    memory_retrieval_policy_version="relevant-memory-v1",
    output_schema_version="trading-analysis-v1",
    token_budget=800,
    reasoning_policy="evidence-bound-no-execution-v1",
)

CRYPTO_TRADER_LEARNING = DomainModelProfile(
    domain_model_id="crypto-trader-learning",
    display_name="CryptoTrader-Learning-v1",
    version="v1",
    brain="DAILY",
    routes=("daily_review", "daily_lesson_extraction"),
    prompt_version="learning-prompt-v1",
    context_profile_version="learning-context-v1",
    factor_profile_version="factor-profile-v1",
    tool_policy_version="read-only-tools-v1",
    memory_retrieval_policy_version="historical-lessons-v1",
    output_schema_version="review-lesson-v1",
    token_budget=800,
    reasoning_policy="deterministic-values-are-authoritative-v1",
)

CRYPTO_TRADER_EVOLUTION = DomainModelProfile(
    domain_model_id="crypto-trader-evolution",
    display_name="CryptoTrader-Evolution-v1",
    version="v1",
    brain="EVOLUTION",
    routes=(
        "evolution_research",
        "evolution_hypothesis",
        "evolution_candidate_reasoning",
    ),
    prompt_version="evolution-prompt-v1",
    context_profile_version="evolution-context-v1",
    factor_profile_version="factor-profile-v1",
    tool_policy_version="read-only-tools-v1",
    memory_retrieval_policy_version="confirmed-lessons-v1",
    output_schema_version="research-hypothesis-candidate-v1",
    token_budget=800,
    reasoning_policy="proposal-only-validation-required-v1",
)


class DomainModelRuntime:
    def __init__(self, gateway) -> None:
        self.gateway = gateway
        self.profiles = (
            CRYPTO_TRADER_LIVE,
            CRYPTO_TRADER_LEARNING,
            CRYPTO_TRADER_EVOLUTION,
        )

    def profile_for_route(self, route: str) -> DomainModelProfile:
        for profile in self.profiles:
            if route in profile.routes:
                return profile
        raise ValueError(f"no domain model profile for route: {route}")

    def describe(self) -> list[dict[str, Any]]:
        bindings = {
            route_name: {
                "provider_id": route.provider_id,
                "base_model": route.model_name,
            }
            for route_name, route in self.gateway.routes.items()
        }
        return [profile.to_dict(bindings) for profile in self.profiles]

    async def invoke(self, *, route: str, context: dict[str, Any], response_model):
        profile = self.profile_for_route(route)
        context = dict(context)
        if route == "live_analysis":
            # Correlation anchor: the model must echo this id back so the
            # DecisionEvidence row can be traced to one LLM invocation.
            context.setdefault("DecisionId", new_id("dec"))
        prompt = self._prompt(profile, context)
        return await self.gateway.invoke(
            LLMRequest(route=route, brain=profile.brain, prompt=prompt), response_model
        )

    @staticmethod
    def _prompt(profile: DomainModelProfile, context: dict[str, Any]) -> str:
        envelope = {
            "domain_model": profile.display_name,
            "domain_model_version": profile.version,
            "prompt_version": profile.prompt_version,
            "context_profile_version": profile.context_profile_version,
            "factor_profile_version": profile.factor_profile_version,
            "tool_policy": profile.tool_policy_version,
            "allowed_tools": list(profile.allowed_tools),
            "memory_policy": profile.memory_retrieval_policy_version,
            "output_schema_version": profile.output_schema_version,
            "reasoning_policy": profile.reasoning_policy,
            "instruction": (
                "Return JSON only. Use supplied immutable evidence only. Never execute actions."
            ),
            "context": context,
        }
        for route_name, schema_example in ROUTE_OUTPUT_EXAMPLES.items():
            if route_name in profile.routes:
                envelope["output_schema_example"] = schema_example
                envelope["instruction"] += (
                    " Match output_schema_example keys exactly;"
                    " use enum values verbatim where shown."
                )
                break
        return json.dumps(envelope, default=str, separators=(",", ":"))


ROUTE_OUTPUT_EXAMPLES: dict[str, dict[str, Any]] = {
    "live_analysis": {
        "decision_id": "<copy context.DecisionId>",
        "symbol": "<string>",
        "action": "LONG|SHORT|NO_TRADE|WAIT",
        "market_regime": "<string>",
        "thesis": "<string>",
        "reason_codes": ["<string>"],
        "position_size_request": 0.0,
        "leverage_request": 0.0,
        "raw_llm_confidence": 0.0,
    },
    "daily_review": {
        "summary": "<string>",
        "error_categories": ["<string>"],
        "evidence_refs": ["<string>"],
    },
    "daily_lesson_extraction": {
        "lessons": ["<string>"],
        "evidence_refs": ["<string>"],
    },
    "evolution_research": {
        "summary": "<string>",
        "evidence_refs": ["<string>"],
        "proposals": ["<string>"],
    },
    "evolution_hypothesis": {
        "hypothesis": "<string>",
        "falsification_test": "<string>",
        "evidence_refs": ["<string>"],
    },
    "evolution_candidate_reasoning": {
        "rationale": "<string>",
        "proposed_changes": ["<string>"],
        "validation_requirements": ["<string>"],
    },
}
