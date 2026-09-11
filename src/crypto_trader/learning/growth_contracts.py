"""Pydantic contracts for the in-system structured review (G02).

Design rules enforced here:

* evidence references are validated against the **allowed input set** for this
  attempt; schema-valid alone is not enough;
* the model may not emit an authoritative PnL or a risk-rule mutation: the
  schema forbids extra fields and requires ``risk_rule_changes == []``;
* no field carries an "experience count" as if it were a win probability;
  confidence dimensions are separate categorical axes;
* input/prompt/schema fingerprints are stable so retries are idempotent.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROMPT_VERSION = "growth-review-prompt-v1"
SCHEMA_VERSION = "growth-structured-review-v1"
REVIEW_PROFILE_VERSION = "growth-review-profile-v1"
MAX_TEXT = 2000
MAX_REFS = 200

ConfidenceAxis = Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"]
SupportGrade = Literal["INSUFFICIENT", "WEAK", "SUPPORTED", "CONTESTED", "REFUTED"]


class ToolEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1, max_length=64)
    source_refs: list[str] = Field(default_factory=list, max_length=MAX_REFS)
    finding: dict[str, Any] = Field(default_factory=dict)
    data_quality: str = Field(default="UNKNOWN", max_length=32)
    timestamp: datetime | None = None


class EpisodeReviewInput(BaseModel):
    """Raw, factual inputs for one episode.  The LLM only explains; it never
    writes the canonical PnL or alters risk."""

    model_config = ConfigDict(extra="forbid")

    episode_id: str = Field(min_length=1, max_length=64)
    account_id: str = Field(min_length=1, max_length=64)
    mode: str = Field(min_length=1, max_length=16)
    symbol: str = Field(min_length=1, max_length=32)
    direction: str = Field(min_length=1, max_length=8)
    currency: str = Field(default="USDT", max_length=16)
    entry_decision_id: str | None = Field(default=None, max_length=64)
    exit_decision_id: str | None = Field(default=None, max_length=64)
    order_refs: list[str] = Field(default_factory=list, max_length=MAX_REFS)
    fill_refs: list[str] = Field(default_factory=list, max_length=MAX_REFS)
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    leverage: Decimal
    fees: Decimal
    funding_pnl: Decimal | None = None
    funding_provenance: Literal["PROVEN", "UNKNOWN"] = "UNKNOWN"
    gross_pnl: Decimal
    net_pnl: Decimal | None = None
    opened_at: datetime
    closed_at: datetime
    entry_market_regime: str = Field(max_length=64)
    terminal_reason: str = Field(max_length=255)
    thesis: str = Field(default="", max_length=MAX_TEXT)
    selected_tools: list[ToolEvidenceInput] = Field(default_factory=list, max_length=32)
    trade_plan: dict[str, Any] = Field(default_factory=dict)
    risk_adjustments: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    position_actions: list[dict[str, Any]] = Field(default_factory=list, max_length=64)
    market_changes: list[dict[str, Any]] = Field(default_factory=list, max_length=64)
    missing_evidence: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("direction")
    @classmethod
    def _direction(cls, value: str) -> str:
        upper = value.upper()
        if upper not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        return upper

    def derived_refs(self) -> set[str]:
        refs = {f"episode:{self.episode_id}"}
        if self.entry_decision_id:
            refs.add(f"decision:{self.entry_decision_id}")
        if self.exit_decision_id:
            refs.add(f"decision:{self.exit_decision_id}")
        refs.update(f"order:{ref}" for ref in self.order_refs)
        refs.update(f"fill:{ref}" for ref in self.fill_refs)
        for tool in self.selected_tools:
            refs.update(tool.source_refs)
            refs.add(f"tool:{tool.tool_name}")
        return refs


class ObservationFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, max_length=MAX_TEXT)
    evidence_refs: list[str] = Field(min_length=1, max_length=MAX_REFS)


class CandidateExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explanation: str = Field(min_length=1, max_length=MAX_TEXT)
    confidence: ConfidenceAxis = "UNKNOWN"
    supporting_refs: list[str] = Field(default_factory=list, max_length=MAX_REFS)
    contrary_refs: list[str] = Field(default_factory=list, max_length=MAX_REFS)
    uncertainty: str = Field(default="", max_length=MAX_TEXT)


class TestableLesson(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, max_length=MAX_TEXT)
    testable_prediction: str = Field(min_length=1, max_length=MAX_TEXT)
    scope: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(min_length=1, max_length=MAX_REFS)
    contrary_refs: list[str] = Field(default_factory=list, max_length=MAX_REFS)
    uncertainty: str = Field(default="", max_length=MAX_TEXT)
    confidence: ConfidenceAxis = "UNKNOWN"


class StructuredReview(BaseModel):
    """Output contract.  No PnL, no risk veto, no executable rule fields."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    episode_id: str = Field(min_length=1, max_length=64)
    observation_facts: list[ObservationFact] = Field(min_length=1, max_length=64)
    candidate_explanations: list[CandidateExplanation] = Field(default_factory=list, max_length=32)
    testable_lessons: list[TestableLesson] = Field(default_factory=list, max_length=32)
    applicability_scope: dict[str, Any] = Field(default_factory=dict)
    uncertainty: str = Field(default="", max_length=MAX_TEXT)
    data_gaps: list[str] = Field(default_factory=list, max_length=32)
    # A structured review must never mutate live risk rules.  The field exists
    # so an attempted mutation is visible and rejected by validation, not
    # silently dropped.
    risk_rule_changes: list[Any] = Field(default_factory=list, max_length=0)

    def all_refs(self) -> list[str]:
        refs: list[str] = []
        for fact in self.observation_facts:
            refs.extend(fact.evidence_refs)
        for explanation in self.candidate_explanations:
            refs.extend(explanation.supporting_refs)
            refs.extend(explanation.contrary_refs)
        for lesson in self.testable_lessons:
            refs.extend(lesson.evidence_refs)
            refs.extend(lesson.contrary_refs)
        return refs


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported canonical JSON type: {type(value).__name__}")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def input_fingerprint(payload: EpisodeReviewInput) -> str:
    return sha256_text(canonical_json(payload.model_dump(mode="json")))


def schema_fingerprint() -> str:
    return sha256_text(canonical_json(StructuredReview.model_json_schema()))


def prompt_fingerprint(prompt: str) -> str:
    return sha256_text(prompt)


class ReferenceValidationError(ValueError):
    def __init__(self, invalid_refs: list[str]) -> None:
        self.invalid_refs = sorted(set(invalid_refs))
        super().__init__(f"evidence refs outside allowed input set: {self.invalid_refs}")


def validate_review(
    review: StructuredReview,
    *,
    allowed_refs: set[str],
    expected_episode_id: str,
) -> None:
    if review.episode_id != expected_episode_id:
        raise ValueError(
            f"review episode_id {review.episode_id!r} != input {expected_episode_id!r}"
        )
    invalid = [ref for ref in review.all_refs() if ref not in allowed_refs]
    if invalid:
        raise ReferenceValidationError(invalid)
    if review.risk_rule_changes:
        raise ValueError("structured review may not propose live risk-rule changes")


_SAFE_REF = re.compile(r"^[A-Za-z0-9_.:/-]{1,200}$")


def sanitize_refs(refs: list[str]) -> list[str]:
    return [ref for ref in refs if isinstance(ref, str) and _SAFE_REF.match(ref)]


def bounded_text(value: str, limit: int = MAX_TEXT) -> str:
    cleaned = "".join(ch for ch in str(value) if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return cleaned[:limit]
