"""Chief trader decision schema."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ChiefTraderDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    symbol: str
    action: str  # LONG | SHORT | NO_TRADE | WAIT | ADD | REDUCE | EXIT | HEDGE
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
    position_size_request: float = 0.0
    leverage_request: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    add_conditions: list[str] = Field(default_factory=list)
    reduce_conditions: list[str] = Field(default_factory=list)
    exit_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    raw_llm_confidence: float = 0.0
    expected_return: float = 0.0
    expected_risk: float = 0.0
    reason_codes: list[str] = Field(default_factory=list)
    llm_invocation_id: str = ""
    selected_strategy: str = ""
    strategy_version: str = ""
    strategy_fit_score: float = 0.0
    secondary_strategies: list[str] = Field(default_factory=list)
    supporting_factors: list[str] = Field(default_factory=list)
    contradicting_factors: list[str] = Field(default_factory=list)
    dominant_factor: str = ""
    evidence_adjusted_confidence: float = 0.0
    # Exploration policy record (PAPER): NORMAL (high-confidence) vs
    # EXPLORATION (learning sample) vs NO_TRADE. An exploration trade is
    # never presented as a high-confidence trade.
    decision_class: str = ""
    exploration_mode: bool = False
    factor_snapshot_id: str = ""
    factor_set_version: str = ""
    model_version: str = "0"
    knowledge_version: str = "0"
    memory_version: str = "0"
    created_at: str = ""
