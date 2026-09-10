"""Immutable single-source valuation truth consumed by Sizing/Risk/API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

VALUATION_QUALITY_HEALTHY = "HEALTHY"
VALUATION_QUALITY_UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ValuationBatch:
    """The one factual valuation snapshot for one account/currency instant.

    Every consumer (Sizing, Risk, Portfolio, API, Frontend) must reference
    ``valuation_id`` instead of recomputing equity from a different source.
    """

    valuation_id: str
    account_id: str
    currency: str
    quality: str
    raw_mtm_equity: Decimal | None
    available_margin: Decimal | None
    adjusted_equity: Decimal | None = None
    peak_adjusted_equity: Decimal | None = None
    drawdown_amount: Decimal | None = None
    drawdown_ratio: Decimal | None = None
    market_as_of: datetime | None = None
    valuation_as_of: datetime | None = None
    ledger_watermark: str | None = None
    position_snapshot_ref: str | None = None
    missing_marks: tuple[str, ...] = field(default_factory=tuple)
    stale_marks: tuple[str, ...] = field(default_factory=tuple)
    components: tuple[dict, ...] = field(default_factory=tuple)
    solvency: str | None = None
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def usable_for_new_risk(self) -> bool:
        return (
            self.quality == VALUATION_QUALITY_HEALTHY
            and self.raw_mtm_equity is not None
        )

    def to_evidence(self) -> dict:
        return {
            "valuation_id": self.valuation_id,
            "account_id": self.account_id,
            "currency": self.currency,
            "quality": self.quality,
            "raw_mtm_equity": _str_or_none(self.raw_mtm_equity),
            "available_margin": _str_or_none(self.available_margin),
            "adjusted_equity": _str_or_none(self.adjusted_equity),
            "peak_adjusted_equity": _str_or_none(self.peak_adjusted_equity),
            "drawdown_amount": _str_or_none(self.drawdown_amount),
            "drawdown_ratio": _str_or_none(self.drawdown_ratio),
            "market_as_of": self.market_as_of.isoformat() if self.market_as_of else None,
            "valuation_as_of": self.valuation_as_of.isoformat()
            if self.valuation_as_of
            else None,
            "ledger_watermark": self.ledger_watermark,
            "position_snapshot_ref": self.position_snapshot_ref,
            "missing_marks": list(self.missing_marks),
            "stale_marks": list(self.stale_marks),
            "components": list(self.components),
            "solvency": self.solvency,
            "reason_codes": list(self.reason_codes),
        }


def _str_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
