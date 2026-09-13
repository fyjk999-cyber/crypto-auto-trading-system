"""POSITION SIZING V2 PATCH — future LLM automatic scale-in (ADD).

Architecture ready, execution deliberately DISABLED:

    AUTO_SCALE_IN_ARCHITECTURE_READY     = YES
    AUTO_SCALE_IN_EXECUTION_ENABLED      = NO

The LLM may request an ADD (``contract.ScaleInIntent``); it never decides the
ADD quantity. :class:`service.ScaleInService` applies the deterministic gates
and then the :class:`sizer.ScaleInSizer` caps. Nothing in this package can
create an order.
"""

from crypto_trader.scale_in.campaign import (
    CampaignProjection,
    PositionCampaign,
)
from crypto_trader.scale_in.contract import (
    FORBIDDEN_ADD_ONLY_REASONS,
    MAX_EFFECTIVE_ADD_ORDER_CREATIONS,
    SCALE_IN_CLIENT_ORDER_ID_PREFIX,
    SCALE_IN_STRATEGY_ID,
    RequestedRiskIntent,
    ScaleInIntent,
    ScaleInTrigger,
    ThesisStatus,
    scale_in_client_order_id,
)
from crypto_trader.scale_in.gates import (
    ADD_EXECUTION_DISABLED,
    ScaleInGateInputs,
    ScaleInGateResult,
    evaluate_scale_in_gates,
)
from crypto_trader.scale_in.policy import (
    DRAWDOWN_BANDS,
    HARD_MAX_SCALE_IN_COUNT,
    SCALE_IN_EXECUTION_WIRED_IN_RUNTIME,
    ScaleInPolicy,
)
from crypto_trader.scale_in.service import (
    ADD_EXECUTION_ENABLED,
    ScaleInDecision,
    ScaleInFacts,
    ScaleInService,
)
from crypto_trader.scale_in.sizer import (
    ADD_BELOW_ECONOMIC_NOTIONAL,
    ScaleInSize,
    ScaleInSizer,
)

__all__ = [
    "ADD_BELOW_ECONOMIC_NOTIONAL",
    "ADD_EXECUTION_DISABLED",
    "ADD_EXECUTION_ENABLED",
    "DRAWDOWN_BANDS",
    "FORBIDDEN_ADD_ONLY_REASONS",
    "HARD_MAX_SCALE_IN_COUNT",
    "MAX_EFFECTIVE_ADD_ORDER_CREATIONS",
    "SCALE_IN_CLIENT_ORDER_ID_PREFIX",
    "SCALE_IN_EXECUTION_WIRED_IN_RUNTIME",
    "SCALE_IN_STRATEGY_ID",
    "CampaignProjection",
    "PositionCampaign",
    "RequestedRiskIntent",
    "ScaleInDecision",
    "ScaleInFacts",
    "ScaleInGateInputs",
    "ScaleInGateResult",
    "ScaleInIntent",
    "ScaleInPolicy",
    "ScaleInService",
    "ScaleInSize",
    "ScaleInSizer",
    "ScaleInTrigger",
    "ThesisStatus",
    "evaluate_scale_in_gates",
    "scale_in_client_order_id",
]
