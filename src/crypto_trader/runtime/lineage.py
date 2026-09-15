"""Low-Risk V2 identity lineage (Phase 6).

Full trade lineage required by the SPEC:

    OpportunityID -> DecisionID -> PositionEpisodeID -> LegID ->
    TradePlanVersion -> IntentID -> ExecutionID -> ClientOrderID ->
    ExchangeOrderID -> FillIDs

This module is deterministic book-keeping: it builds/validates the chain so
every factual fill can be traced back to the decision and opportunity that
authorized it. It never submits or mutates an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LINEAGE_STAGES: tuple[str, ...] = (
    "opportunity_id",
    "decision_id",
    "position_episode_id",
    "leg_id",
    "trade_plan_version",
    "intent_id",
    "execution_id",
    "client_order_id",
    "exchange_order_id",
    "fill_ids",
)

# A decision may exist without an opportunity nomination; the remaining links
# become mandatory once a factual order/fill exists.
OPTIONAL_STAGES: frozenset[str] = frozenset({"opportunity_id", "position_episode_id", "leg_id"})


@dataclass
class LineageChain:
    values: dict = field(default_factory=dict)
    authority: str = "LINEAGE_ONLY"
    is_order: bool = False

    def missing(self) -> list[str]:
        missing = []
        for stage in LINEAGE_STAGES:
            value = self.values.get(stage)
            if value is None or value == "" or value == []:
                missing.append(stage)
        return missing

    @property
    def complete(self) -> bool:
        return not self.missing()

    def trade_complete(self) -> bool:
        """Completeness required once an order/fill exists."""
        return not [stage for stage in self.missing() if stage not in OPTIONAL_STAGES]

    def as_dict(self) -> dict:
        return {
            "stages": list(LINEAGE_STAGES),
            "values": {stage: self.values.get(stage) for stage in LINEAGE_STAGES},
            "missing": self.missing(),
            "complete": self.complete,
            "trade_complete": self.trade_complete(),
            "authority": self.authority,
            "is_order": self.is_order,
        }


def build_lineage(**values) -> LineageChain:
    return LineageChain(values=dict(values))


def validate_lineage(chain: LineageChain) -> dict:
    missing = chain.missing()
    return {
        "complete": not missing,
        "trade_complete": chain.trade_complete(),
        "missing": missing,
        "unexpected": [key for key in chain.values if key not in LINEAGE_STAGES],
        "stages": list(LINEAGE_STAGES),
        "authority": "LINEAGE_ONLY",
        "is_order": False,
    }
