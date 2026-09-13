"""ADD intent contract (§78) and the campaign identity rules (§90).

The LLM may request an ADD. It may never decide the ADD quantity:

    LLM   -> SHOULD_WE_ADD?  (direction, conviction, trigger, thesis status)
    Sizer -> HOW MUCH?       (deterministic, capital- and risk-capped)
    Risk  -> may reject      (final hard gate)
    Exec  -> may fill less   (and, in this round, does not run at all)

``requested_quantity`` / ``requested_exposure`` remain on the contract for
audit only: ``ADD_LLM_QUANTITY_AUTHORITY = NO``.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from crypto_trader.domain.money import D

#: §90 — every ADD order carries a durable, decision-scoped identity.
SCALE_IN_CLIENT_ORDER_ID_PREFIX = "live_llm_position_add_"
#: §90 — exactly one effective order creation per ADD decision, across restarts.
MAX_EFFECTIVE_ADD_ORDER_CREATIONS = 1
#: §116 — ADD is its own order purpose, never a plain ENTRY.
SCALE_IN_STRATEGY_ID = "live_llm_position_add"


def scale_in_client_order_id(position_decision_id: str) -> str:
    """Deterministic §90 identity for one ADD decision.

    Deterministic derivation is what makes "max 1 effective order creation per
    ADD decision" durable across a restart: the same decision always maps to the
    same order identity, so an order-identity uniqueness guard (F4) refuses a
    duplicate without any extra bookkeeping.
    """
    decision_id = str(position_decision_id or "").strip()
    if not decision_id:
        raise ValueError("scale-in requires a non-empty position_decision_id")
    return f"{SCALE_IN_CLIENT_ORDER_ID_PREFIX}{decision_id}"


class ScaleInTrigger(StrEnum):
    """§80 — a NEW decision-relevant reason to add."""

    BREAKOUT_CONFIRMATION = "BREAKOUT_CONFIRMATION"
    TREND_CONTINUATION = "TREND_CONTINUATION"
    PULLBACK_CONFIRMATION = "PULLBACK_CONFIRMATION"
    REGIME_STRENGTHENING = "REGIME_STRENGTHENING"
    OTHER = "OTHER"


class ThesisStatus(StrEnum):
    """§81 — the original thesis must still be VALID to add."""

    VALID = "VALID"
    STRENGTHENED = "STRENGTHENED"
    WEAKENED = "WEAKENED"
    INVALIDATED = "INVALIDATED"


class RequestedRiskIntent(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


#: §80 — reasons that may NEVER justify an ADD on their own.
FORBIDDEN_ADD_ONLY_REASONS = (
    "PRICE_LOWER_THAN_ENTRY",
    "POSITION_CURRENTLY_LOSING",
    "REDUCE_AVERAGE_COST",
    "PREVIOUS_ORDER_UNDERFILLED",
    "UNUSED_MARGIN_AVAILABLE",
    "ACCOUNT_BALANCE_LARGE",
)


class ScaleInIntent(BaseModel):
    """The ADD request as the LLM may express it. Quantity is advisory only."""

    model_config = ConfigDict(extra="forbid")

    position_decision_id: str
    symbol: str
    direction: Literal["LONG", "SHORT"]
    conviction: float = Field(ge=0.0, le=1.0)
    trigger: ScaleInTrigger
    thesis_status: ThesisStatus
    stop_loss: float = Field(gt=0.0)
    expected_holding_period: str = ""
    requested_risk_intent: RequestedRiskIntent = RequestedRiskIntent.NORMAL
    reason_codes: list[str] = Field(default_factory=list)

    #: §83/§93 — ADD requires NEW decision-relevant evidence.
    material_change: bool = False
    material_change_reasons: list[str] = Field(default_factory=list)

    #: Advisory only (§78). Recorded for audit, never a quantity authority.
    requested_quantity: float | None = Field(default=None, ge=0.0)
    requested_exposure: float | None = Field(default=None, ge=0.0)

    @property
    def llm_quantity_authority(self) -> str:
        return "ADVISORY_ONLY"

    @property
    def client_order_id(self) -> str:
        return scale_in_client_order_id(self.position_decision_id)

    @property
    def stop_loss_value(self) -> Decimal:
        """Adapter-boundary conversion: the core forbids binary floats."""
        return _decimal(self.stop_loss)

    @property
    def conviction_value(self) -> Decimal:
        return _decimal(self.conviction)

    @model_validator(mode="after")
    def validate_add_contract(self) -> ScaleInIntent:
        if not self.position_decision_id.strip():
            raise ValueError("ADD requires a position_decision_id")
        if not self.symbol.strip():
            raise ValueError("ADD requires a symbol")
        if not self.reason_codes:
            raise ValueError("ADD requires explicit reason_codes")
        if self.material_change and not self.material_change_reasons:
            raise ValueError("material_change requires material_change_reasons")
        # §80 — no ADD may rest only on the forbidden reasons.
        if self.reason_codes and all(
            code in FORBIDDEN_ADD_ONLY_REASONS for code in self.reason_codes
        ):
            raise ValueError(
                "ADD cannot be justified by price/pnl/margin reasons alone"
            )
        return self

    def to_evidence(self) -> dict:
        return {
            "position_decision_id": self.position_decision_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "conviction": str(self.conviction),
            "trigger": self.trigger.value,
            "thesis_status": self.thesis_status.value,
            "stop_loss": str(self.stop_loss),
            "expected_holding_period": self.expected_holding_period,
            "requested_risk_intent": self.requested_risk_intent.value,
            "reason_codes": list(self.reason_codes),
            "material_change": self.material_change,
            "material_change_reasons": list(self.material_change_reasons),
            "requested_quantity_from_llm": _s(self.requested_quantity),
            "requested_exposure_from_llm": _s(self.requested_exposure),
            "llm_quantity_authority": self.llm_quantity_authority,
            "client_order_id": self.client_order_id,
        }


def _s(value: float | None) -> str | None:
    return None if value is None else str(value)


def _decimal(value) -> Decimal:
    """Convert an LLM float into the Decimal core at the adapter boundary."""
    try:
        parsed = D(str(value))
    except Exception:  # noqa: BLE001 - an unparseable number is not a fact
        return Decimal("0")
    return parsed if parsed.is_finite() else Decimal("0")
