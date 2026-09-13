"""POSITION_CAMPAIGN: the durable shape of one position's whole lifecycle (§89).

A campaign is the initial entry plus every ADD, sharing ONE risk budget and ONE
500% position ceiling:

    ProjectedPositionNotional = CurrentPositionNotional + AddNotional
    ProjectedPositionNotional <= Equity x 5            (§84)
    ProjectedGrossExposure    <= Equity x 5            (§85)
    ProjectedMaxLossAtStop    <= TotalAllowedPositionRisk  (§86)

Value object only: this round defines the model and its arithmetic. Durable
persistence (a table, a migration, API surfacing) is a follow-up mission, so no
schema is introduced here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal

from crypto_trader.domain.money import D

#: §89 — lineage fields, all factual.
CAMPAIGN_ID_PREFIX = "campaign_"


@dataclass(frozen=True)
class PositionCampaign:
    """One position's initial entry plus its ADDs, with cumulative accounting."""

    campaign_id: str
    symbol: str
    direction: str
    original_trade_plan_id: str | None = None
    initial_entry_decision_id: str | None = None
    scale_in_decision_ids: tuple[str, ...] = ()
    scale_in_order_ids: tuple[str, ...] = ()
    scale_in_fill_ids: tuple[str, ...] = ()
    current_total_qty: Decimal = Decimal("0")
    weighted_average_entry: Decimal | None = None
    current_stop: Decimal | None = None
    total_notional: Decimal = Decimal("0")
    #: §86 — risk of the WHOLE campaign at the current stop, not just one leg.
    total_risk_at_stop: Decimal = Decimal("0")
    add_count: int = 0
    max_add_count: int = 0
    opened_at: datetime | None = None
    last_add_at: datetime | None = None
    scale_in_fill_quantities: tuple[Decimal, ...] = field(default=())
    reason_codes: tuple[str, ...] = ()

    # ---------------------------------------------------------------- derived
    @property
    def add_layers_used(self) -> int:
        return int(self.add_count)

    @property
    def add_layers_remaining(self) -> int:
        return max(0, int(self.max_add_count) - int(self.add_count))

    @property
    def is_open(self) -> bool:
        return D(self.current_total_qty) != 0

    def remaining_campaign_risk(self, campaign_risk_budget: Decimal) -> Decimal:
        """§104 — campaign risk left to spend, never negative."""
        remaining = D(campaign_risk_budget) - D(self.total_risk_at_stop)
        return remaining if remaining > 0 else Decimal("0")

    def register_add(
        self,
        *,
        decision_id: str,
        order_id: str | None,
        fill_quantity: Decimal,
        fill_notional: Decimal,
        total_risk_at_stop: Decimal,
        current_stop: Decimal | None,
        occurred_at: datetime | None,
    ) -> PositionCampaign:
        """Return a new campaign state after one factual ADD fill.

        Only FACTUAL fills move the campaign: a target quantity never does, so a
        partial ADD is accounted for exactly as it settled (§113).
        """
        fill_quantity = D(fill_quantity)
        if fill_quantity < 0:
            raise ValueError("scale-in fill quantity must be non-negative")
        new_total = D(self.current_total_qty) + fill_quantity
        if new_total <= 0:
            raise ValueError("scale-in fill would leave a non-positive position")
        if fill_quantity > 0 and self.weighted_average_entry is not None:
            prior_notional = D(self.weighted_average_entry) * D(self.current_total_qty)
            weighted = (prior_notional + D(fill_notional)) / new_total
        elif fill_quantity > 0:
            weighted = (
                D(fill_notional) / fill_quantity if fill_quantity > 0 else None
            )
        else:
            weighted = self.weighted_average_entry
        return replace(
            self,
            scale_in_decision_ids=(*self.scale_in_decision_ids, decision_id),
            scale_in_order_ids=(
                (*self.scale_in_order_ids, order_id) if order_id else self.scale_in_order_ids
            ),
            scale_in_fill_quantities=(*self.scale_in_fill_quantities, fill_quantity),
            current_total_qty=new_total,
            weighted_average_entry=weighted,
            current_stop=current_stop,
            total_notional=D(self.total_notional) + D(fill_notional),
            total_risk_at_stop=D(total_risk_at_stop),
            add_count=int(self.add_count) + 1,
            last_add_at=occurred_at,
        )

    def to_evidence(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "original_trade_plan_id": self.original_trade_plan_id,
            "initial_entry_decision_id": self.initial_entry_decision_id,
            "scale_in_decision_ids": list(self.scale_in_decision_ids),
            "scale_in_order_ids": list(self.scale_in_order_ids),
            "scale_in_fill_ids": list(self.scale_in_fill_ids),
            "current_total_qty": str(self.current_total_qty),
            "weighted_average_entry": _s(self.weighted_average_entry),
            "current_stop": _s(self.current_stop),
            "total_notional": str(self.total_notional),
            "total_risk_at_stop": str(self.total_risk_at_stop),
            "add_count": self.add_count,
            "max_add_count": self.max_add_count,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "last_add_at": self.last_add_at.isoformat() if self.last_add_at else None,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class CampaignProjection:
    """What the campaign would look like after a proposed ADD (§84-§86)."""

    add_quantity: Decimal
    add_notional: Decimal
    projected_total_qty: Decimal
    projected_position_notional: Decimal
    projected_gross_exposure: Decimal
    projected_total_risk_at_stop: Decimal
    position_notional_ceiling: Decimal
    gross_exposure_ceiling: Decimal
    campaign_risk_budget: Decimal
    add_number: int

    @property
    def within_position_ceiling(self) -> bool:
        return self.projected_position_notional <= self.position_notional_ceiling

    @property
    def within_gross_ceiling(self) -> bool:
        return self.projected_gross_exposure <= self.gross_exposure_ceiling

    @property
    def within_campaign_risk(self) -> bool:
        return self.projected_total_risk_at_stop <= self.campaign_risk_budget

    @property
    def allowed(self) -> bool:
        return (
            self.within_position_ceiling
            and self.within_gross_ceiling
            and self.within_campaign_risk
        )

    def to_evidence(self) -> dict:
        return {
            "add_quantity": str(self.add_quantity),
            "add_notional": str(self.add_notional),
            "projected_total_qty": str(self.projected_total_qty),
            "projected_position_notional": str(self.projected_position_notional),
            "projected_gross_exposure": str(self.projected_gross_exposure),
            "projected_total_risk_at_stop": str(self.projected_total_risk_at_stop),
            "position_notional_ceiling": str(self.position_notional_ceiling),
            "gross_exposure_ceiling": str(self.gross_exposure_ceiling),
            "campaign_risk_budget": str(self.campaign_risk_budget),
            "add_number": self.add_number,
            "within_position_ceiling": self.within_position_ceiling,
            "within_gross_ceiling": self.within_gross_ceiling,
            "within_campaign_risk": self.within_campaign_risk,
        }


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
