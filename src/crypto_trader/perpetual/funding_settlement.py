"""Versioned PAPER funding settlement derivation (research/accounting only)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class PaperFundingSettlement:
    settlement_timestamp: datetime
    signed_amount: Decimal
    currency: str
    rule_version: str
    idempotency_key: str


def compute_paper_funding(
    *,
    settlement_timestamp: datetime,
    signed_quantity: Decimal,
    mark_price: Decimal,
    funding_rate: Decimal,
    contract_size: Decimal,
    contract_multiplier: Decimal,
    currency: str = "USDT",
    account_id: str = "default",
    instrument_id: str,
    rule_version: str = "v1",
) -> PaperFundingSettlement:
    """Positive amount = credit; negative = debit.

    LONG with positive rate pays; SHORT with positive rate receives.
    """
    signed_amount = (
        -signed_quantity
        * mark_price
        * contract_size
        * contract_multiplier
        * funding_rate
    )
    key = (
        f"{account_id}|{instrument_id}|{settlement_timestamp.isoformat()}|{rule_version}"
    )
    return PaperFundingSettlement(
        settlement_timestamp=settlement_timestamp,
        signed_amount=signed_amount,
        currency=currency,
        rule_version=rule_version,
        idempotency_key=key,
    )
