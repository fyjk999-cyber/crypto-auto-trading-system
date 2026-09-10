"""Explicit provenance for historical signed position quantity.

A bare Decimal cannot distinguish a factual flat position from missing or
unattributable fill history. Funding settlement must fail closed unless the
quantity at the settlement instant is proven for the exact account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class HistoricalQuantityStatus(StrEnum):
    PROVEN_VALUE = "PROVEN_VALUE"
    PROVEN_ZERO = "PROVEN_ZERO"
    UNPROVEN = "UNPROVEN"


@dataclass(frozen=True)
class HistoricalQuantityProvenance:
    account_id: str
    instrument_id: str
    settlement_timestamp: datetime
    status: HistoricalQuantityStatus
    quantity: Decimal | None
    source: str
    fill_ids: tuple[str, ...] = ()
    watermark: str | None = None
    reason: str | None = None

    @property
    def proven(self) -> bool:
        return self.status in {
            HistoricalQuantityStatus.PROVEN_VALUE,
            HistoricalQuantityStatus.PROVEN_ZERO,
        }
