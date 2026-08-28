"""Canonical contracts for the shared three-brain LLM runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LLMErrorCode(str, Enum):
    NOT_CONFIGURED = "not_configured"
    UNKNOWN_ROUTE = "unknown_route"
    DISABLED_PROVIDER = "disabled_provider"
    AUTHENTICATION_FAILED = "authentication_failed"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_MODEL = "invalid_model"
    INVALID_RESPONSE = "invalid_response"
    NETWORK_ERROR = "network_error"
    CIRCUIT_OPEN = "circuit_open"


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    provider_type: Literal["openai", "deepseek", "custom"]
    display_name: str = Field(min_length=1, max_length=100)
    base_url: str
    api_key_secret_ref: str
    default_model: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    max_retries: int = Field(default=2, ge=0, le=5)

    @field_validator("base_url")
    @classmethod
    def secure_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith("https://") and not normalized.startswith(
            ("http://127.0.0.1", "http://localhost")
        ):
            raise ValueError("provider base_url must use HTTPS (except local development)")
        return normalized


class ProviderUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    provider_type: Literal["openai", "deepseek", "custom"]
    display_name: str = Field(min_length=1, max_length=100)
    base_url: str
    api_key: str | None = Field(default=None, min_length=1, max_length=500)
    default_model: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    max_retries: int = Field(default=2, ge=0, le=5)

    @field_validator("base_url")
    @classmethod
    def secure_base_url(cls, value: str) -> str:
        return ProviderConfig.secure_base_url(value)


class ModelRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_name: str = Field(min_length=1, max_length=64)
    provider_id: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=800, ge=16, le=16_384)
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)


class LLMRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: str
    brain: Literal["LIVE", "DAILY", "EVOLUTION"]
    prompt: str = Field(min_length=1, max_length=100_000)
    correlation_id: str | None = None


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invocation_id: str
    ok: bool
    route: str
    provider: str = ""
    model: str = ""
    content: dict[str, Any] | None = None
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    error_code: LLMErrorCode | None = None
    checked_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ProviderResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    content: dict[str, Any] | None = None
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    error_code: LLMErrorCode | None = None
    retryable: bool = False


class LiveAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    symbol: str
    action: Literal["LONG", "SHORT", "NO_TRADE", "WAIT"]
    market_regime: str = "UNKNOWN"
    strategy_selected: list[str] = Field(default_factory=list)
    thesis: str = ""
    position_size_request: float = 0.0
    leverage_request: float = 0.0
    raw_llm_confidence: float = 0.0
    reason_codes: list[str] = Field(default_factory=list)


class DailyReviewReasoning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    error_categories: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class LessonExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lessons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ResearchReasoningResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    evidence_refs: list[str] = Field(default_factory=list)
    proposals: list[str] = Field(default_factory=list)


class HypothesisReasoningResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis: str
    falsification_test: str
    evidence_refs: list[str] = Field(default_factory=list)


class CandidateReasoningResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rationale: str
    proposed_changes: list[str] = Field(default_factory=list)
    validation_requirements: list[str] = Field(default_factory=list)


REQUIRED_ROUTES = (
    "live_analysis",
    "daily_review",
    "daily_lesson_extraction",
    "evolution_research",
    "evolution_hypothesis",
    "evolution_candidate_reasoning",
)
