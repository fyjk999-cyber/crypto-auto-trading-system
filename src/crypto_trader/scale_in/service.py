"""ScaleInService: gates + sizer, producing a DECISION and never an order.

§136/§137/§138 — this round delivers the architecture, the contract, the
campaign risk model and the sizer interface, with ADD EXECUTION DISABLED.
``order_created`` is therefore always ``False`` in this build: the ADD path has
no way to reach ExecutionAuthority, whatever the feature flag says.

The service still computes the full, capped ADD size so the architecture is
provable and testable — an ADD that the gates allow and the sizer caps is
reported as ``allowed`` together with ``order_created=False``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from crypto_trader.domain.models import Instrument
from crypto_trader.scale_in.campaign import PositionCampaign
from crypto_trader.scale_in.contract import ScaleInIntent, scale_in_client_order_id
from crypto_trader.scale_in.gates import (
    ADD_EXECUTION_DISABLED,
    VERDICT_ALLOWED,
    VERDICT_COALESCED,
    VERDICT_REJECTED,
    ScaleInGateInputs,
    evaluate_scale_in_gates,
)
from crypto_trader.scale_in.policy import (
    SCALE_IN_EXECUTION_WIRED_IN_RUNTIME,
    ScaleInPolicy,
)
from crypto_trader.scale_in.sizer import ScaleInSize, ScaleInSizer
from crypto_trader.sizing.policy import PositionSizingPolicy

#: §137 — reported alongside every ADD decision so no caller can mistake a
#: risk verdict for permission to trade.
ADD_EXECUTION_ENABLED = SCALE_IN_EXECUTION_WIRED_IN_RUNTIME


@dataclass(frozen=True)
class ScaleInFacts:
    """Fresh, factual inputs required before any ADD (§83).

    Every ADD is a NEW risk event, so nothing here may be reused from the
    initial entry: fresh valuation equity, fresh margin, fresh liquidity, fresh
    exposure, fresh stop distance, fresh risk budget.
    """

    equity: object | None
    available_margin: object | None
    price: object
    liquidity_depth_qty: object | None
    positions: dict | None = None
    volatility: object | None = None
    liquidity: object = "1"
    drawdown_ratio: object | None = None
    regime_multiplier: object = "1"
    requested_leverage: object = "1"
    portfolio_gross_exposure: object | None = None


@dataclass(frozen=True)
class ScaleInDecision:
    """The outcome of one ADD evaluation. It is a decision, not an order."""

    verdict: str
    allowed: bool
    reason_codes: tuple[str, ...]
    add_number: int
    execution_enabled: bool
    order_created: bool
    execution_block_reason: str | None
    client_order_id: str | None
    size: ScaleInSize | None
    gate_evidence: dict
    campaign_evidence: dict
    decided_at: datetime | None = None

    @property
    def approved_quantity(self):
        return self.size.approved_quantity if self.size is not None else None

    @property
    def approved_notional(self):
        return self.size.approved_notional if self.size is not None else None

    @property
    def binding_cap(self) -> str | None:
        return self.size.binding_cap if self.size is not None else None

    def to_evidence(self) -> dict:
        return {
            "verdict": self.verdict,
            "allowed": self.allowed,
            "reason_codes": list(self.reason_codes),
            "add_number": self.add_number,
            "execution_enabled": self.execution_enabled,
            "order_created": self.order_created,
            "execution_block_reason": self.execution_block_reason,
            "client_order_id": self.client_order_id,
            "sizing": self.size.to_evidence() if self.size is not None else None,
            "gates": self.gate_evidence,
            "campaign": self.campaign_evidence,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "llm_quantity_authority": "ADVISORY_ONLY",
            "sizer_quantity_authority": True,
        }


class ScaleInService:
    """Evaluate an ADD request: gates, then the deterministic ScaleInSizer."""

    def __init__(
        self,
        *,
        policy: PositionSizingPolicy | None = None,
        scale_in_policy: ScaleInPolicy | None = None,
    ) -> None:
        self.policy = policy or PositionSizingPolicy()
        self.scale_in_policy = scale_in_policy or ScaleInPolicy()
        self.sizer = ScaleInSizer(
            policy=self.policy, scale_in_policy=self.scale_in_policy
        )

    def evaluate(
        self,
        *,
        intent: ScaleInIntent,
        campaign: PositionCampaign,
        facts: ScaleInFacts,
        instrument: Instrument,
        gate_inputs: ScaleInGateInputs | None = None,
        now: datetime | None = None,
        size: bool = True,
    ) -> ScaleInDecision:
        """Return the ADD decision. This method cannot create an order.

        ``size=False`` stops after the gates, for callers that only need the
        admission verdict.
        """
        if gate_inputs is None:
            raise ValueError("scale-in evaluation requires explicit gate inputs")
        gate_result = evaluate_scale_in_gates(
            intent, gate_inputs, self.scale_in_policy
        )
        add_number = int(campaign.add_count) + 1

        if not gate_result.allowed:
            verdict = (
                VERDICT_COALESCED
                if gate_result.verdict == VERDICT_COALESCED
                else VERDICT_REJECTED
            )
            return ScaleInDecision(
                verdict=verdict,
                allowed=False,
                reason_codes=gate_result.reason_codes,
                add_number=add_number,
                execution_enabled=ADD_EXECUTION_ENABLED,
                order_created=False,
                execution_block_reason=ADD_EXECUTION_DISABLED,
                client_order_id=scale_in_client_order_id(
                    intent.position_decision_id
                ),
                size=None,
                gate_evidence=gate_result.to_evidence(),
                campaign_evidence=campaign.to_evidence(),
                decided_at=now,
            )

        sized = (
            self.sizer.size(
                campaign=campaign,
                instrument=instrument,
                price=facts.price,
                stop_loss=intent.stop_loss_value,
                conviction=intent.conviction_value,
                liquidity_depth_qty=facts.liquidity_depth_qty,
                equity=facts.equity,
                available_margin=facts.available_margin,
                requested_leverage=facts.requested_leverage,
                positions=facts.positions,
                volatility=facts.volatility,
                liquidity=facts.liquidity,
                regime_multiplier=facts.regime_multiplier,
                drawdown_multiplier=gate_result.drawdown_multiplier,
                # The SAME budget the gates decided against (§86).
                campaign_risk_budget=gate_inputs.campaign_risk_budget,
            )
            if size
            else None
        )
        if sized is not None and sized.rejected:
            return ScaleInDecision(
                verdict=VERDICT_REJECTED,
                allowed=False,
                reason_codes=sized.reason_codes,
                add_number=add_number,
                execution_enabled=ADD_EXECUTION_ENABLED,
                order_created=False,
                execution_block_reason=ADD_EXECUTION_DISABLED,
                client_order_id=scale_in_client_order_id(
                    intent.position_decision_id
                ),
                size=sized,
                gate_evidence=gate_result.to_evidence(),
                campaign_evidence=campaign.to_evidence(),
                decided_at=now,
            )

        # Gates allow it and the Sizer capped it — but this build still does not
        # trade it. ADD execution is not wired into the runtime (§136/§138).
        return ScaleInDecision(
            verdict=VERDICT_ALLOWED,
            allowed=True,
            reason_codes=gate_result.reason_codes,
            add_number=add_number,
            execution_enabled=ADD_EXECUTION_ENABLED,
            order_created=False,
            execution_block_reason=ADD_EXECUTION_DISABLED,
            client_order_id=scale_in_client_order_id(intent.position_decision_id),
            size=sized,
            gate_evidence=gate_result.to_evidence(),
            campaign_evidence=campaign.to_evidence(),
            decided_at=now,
        )
