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


def lineage_from_order(
    *,
    metadata: dict | None,
    client_order_id: str | None,
    exchange_order_id: str | None = None,
    fill_id: str | None = None,
) -> LineageChain:
    """Assemble the factual lineage of an order/fill from canonical metadata.

    Fallbacks keep the chain traceable even for legacy orders: intent_id falls
    back to the client order id and execution linkage to the exchange order id.
    """
    meta = metadata or {}
    fill_ids = list(meta.get("fill_ids") or [])
    if fill_id:
        fill_ids.append(fill_id)
    return build_lineage(
        opportunity_id=meta.get("opportunity_id") or meta.get("candidate_source"),
        decision_id=meta.get("decision_id") or meta.get("entry_decision_id"),
        position_episode_id=meta.get("position_episode_id") or meta.get("trade_episode_id"),
        leg_id=meta.get("leg_id"),
        trade_plan_version=meta.get("plan_version") or meta.get("plan_contract_version"),
        intent_id=meta.get("intent_id") or client_order_id,
        execution_id=meta.get("execution_id") or exchange_order_id,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        fill_ids=fill_ids,
    )
