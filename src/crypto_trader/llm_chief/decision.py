"""Chief trader decision schema."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PositionState(StrEnum):
    FLAT = "FLAT"
    OPEN = "OPEN"


class FlatAction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"
    WAIT = "WAIT"
    FAIL_CLOSED = "FAIL_CLOSED"


class OpenAction(StrEnum):
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    FAIL_CLOSED = "FAIL_CLOSED"


DecisionAction = FlatAction | OpenAction


class ChiefTraderDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    symbol: str
    position_state: PositionState = PositionState.FLAT
    action: DecisionAction
    market_regime: str
    strategy_selected: list[str] = Field(default_factory=list)
    thesis: str = ""
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    knowledge_refs: list[str] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    coin_profile_refs: list[str] = Field(default_factory=list)
    pattern_refs: list[str] = Field(default_factory=list)
    compressed_lessons: list[str] = Field(default_factory=list)
    expected_holding_period: str = ""
    entry_plan: str = ""
    position_size_request: float = Field(default=0.0, ge=0.0)
    leverage_request: float = Field(default=0.0, ge=0.0)
    stop_loss: float | None = None
    take_profit: float | None = None
    add_conditions: list[str] = Field(default_factory=list)
    reduce_conditions: list[str] = Field(default_factory=list)
    exit_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    raw_llm_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    expected_return: float = 0.0
    expected_risk: float = 0.0
    reason_codes: list[str] = Field(default_factory=list)
    model_version: str = "0"
    knowledge_version: str = "0"
    memory_version: str = "0"
    created_at: str = ""
    model_provider: str = "unknown"
    model: str = "unknown"

    @model_validator(mode="after")
    def validate_action_for_position_state(self) -> ChiefTraderDecision:
        valid = (
            set(FlatAction)
            if self.position_state == PositionState.FLAT
            else set(OpenAction)
        )
        if self.action not in valid:
            raise ValueError(
                f"{self.action} is not valid while position is {self.position_state}"
            )
        return self
