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
    ADD = "ADD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    CLOSE = "CLOSE"
    MODIFY_EXIT = "MODIFY_EXIT"
    HEDGE = "HEDGE"
    REVERSE = "REVERSE"
    FAIL_CLOSED = "FAIL_CLOSED"


class ShouldTrade(StrEnum):
    TRADE = "TRADE"
    WAIT = "WAIT"
    REJECT = "REJECT"


class ConditionType(StrEnum):
    PRICE = "PRICE"
    TIME = "TIME"
    INDICATOR = "INDICATOR"
    EVENT = "EVENT"


class ConditionPriority(StrEnum):
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class ReassessmentCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ConditionType
    value: str
    priority: ConditionPriority = ConditionPriority.NORMAL
    direction: str = ""


class NextReassessment(BaseModel):
    """Wake the Core LLM only; never an order or a stop."""

    model_config = ConfigDict(extra="forbid")

    logic: str = "OR"  # AND | OR
    conditions: list[ReassessmentCondition] = Field(default_factory=list)
    note: str = ""

    @model_validator(mode="after")
    def validate_logic(self) -> NextReassessment:
        if self.logic not in ("AND", "OR"):
            raise ValueError("NEXT_REASSESSMENT logic must be AND or OR")
        if not self.conditions:
            raise ValueError("NEXT_REASSESSMENT requires at least one condition")
        return self


class BaseExitPlan(BaseModel):
    """Mandatory deterministic exit for every new entry (V2 contract)."""

    model_config = ConfigDict(extra="forbid")

    type: ConditionType = ConditionType.PRICE
    trigger: str
    size_pct: float = Field(default=100.0, gt=0.0, le=100.0)
    reason_code: str = "BASE_EXIT"
    note: str = ""


class OrderContractV2(BaseModel):
    """LLM-owned sizing/leverage declaration for a new-risk child order."""

    model_config = ConfigDict(extra="forbid")

    strategy: str = ""
    capital_allocation_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    leverage: float = Field(default=0.0, ge=0.0)
    base_exit: BaseExitPlan | None = None
    expected_edge_bps: float | None = None
    expected_cost_bps: float | None = None
    position_plan_version: int = Field(default=1, ge=1)
    based_on_state_version: str | None = None
    partial_entry: bool = False
    reentry_policy: str = ""


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
    requested_exposure: float | None = Field(default=None, ge=0.0)
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
    # --- Low-Risk V2 contract (v2 when plan_contract_version >= 2) ---
    plan_contract_version: int = Field(default=1, ge=1)
    should_trade: ShouldTrade = ShouldTrade.TRADE
    strategy: str = ""
    capital_allocation_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    base_exit: BaseExitPlan | None = None
    exit_approach: str = ""
    adverse_trigger: dict | None = None
    thesis_invalidation: str = ""
    reassessment_rules: list[str] = Field(default_factory=list)
    next_reassessment: NextReassessment | None = None
    partial_entry: bool = False
    reentry_policy: str = ""
    position_plan_version: int = Field(default=1, ge=1)
    based_on_state_version: str | None = None
    expected_edge_bps: float | None = None
    expected_cost_bps: float | None = None
    order_contract: OrderContractV2 | None = None

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
        if self.action in {OpenAction.REDUCE, OpenAction.CLOSE} and self.position_size_request <= 0:
            raise ValueError("REDUCE/CLOSE requires a positive reduction quantity")
        if self.action in {OpenAction.ADD, OpenAction.HEDGE, OpenAction.REVERSE}:
            if self.position_size_request <= 0 and not (
                self.requested_exposure is not None and self.requested_exposure > 0
            ):
                raise ValueError(f"{self.action} requires positive size")
            if self.leverage_request <= 0:
                raise ValueError(f"{self.action} requires positive requested leverage")
        if self.action in {FlatAction.LONG, FlatAction.SHORT}:
            if not self.thesis.strip():
                raise ValueError("directional entry requires an explicit thesis")
            if self.position_size_request <= 0 and not (
                self.requested_exposure is not None and self.requested_exposure > 0
            ):
                raise ValueError(
                    "directional entry requires positive quantity or requested exposure"
                )
            if self.leverage_request <= 0:
                raise ValueError("directional entry requires positive requested leverage")
            if self.stop_loss is None or self.stop_loss <= 0:
                raise ValueError("directional entry requires a positive invalidation price")
        if self.plan_contract_version >= 2:
            self._validate_v2_contract()
        return self

    def _validate_v2_contract(self) -> None:
        """V2 structural contract. Execution still re-validates hard limits."""
        new_risk = self.action in {
            FlatAction.LONG,
            FlatAction.SHORT,
            OpenAction.ADD,
            OpenAction.HEDGE,
            OpenAction.REVERSE,
        }
        if not new_risk:
            return
        if self.capital_allocation_pct is None or not (
            0.0 < self.capital_allocation_pct <= 25.0
        ):
            raise ValueError(
                "V2 new-risk child requires capital_allocation_pct in (0, 25]"
            )
        if self.leverage_request <= 0 or self.leverage_request > 20.0:
            raise ValueError("V2 new-risk child requires leverage in (0, 20]")
        if self.base_exit is None:
            raise ValueError("V2 new entry requires a Base Exit plan")
        if not self.thesis.strip():
            raise ValueError("V2 new risk requires an explicit thesis")
        if self.expected_edge_bps is not None and self.expected_cost_bps is not None:
            if self.expected_edge_bps <= self.expected_cost_bps:
                raise ValueError(
                    "V2 expected edge must exceed all-in estimated cost"
                )
        if self.next_reassessment is not None and not isinstance(
            self.next_reassessment, NextReassessment
        ):
            raise ValueError("invalid NEXT_REASSESSMENT")

