"""Versioned PAPER funding settlement derivation (research/accounting only)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class PaperFundingSettlement:
    account_id: str
    instrument_id: str
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
    # Business identity excludes rule_version: a rule upgrade must not charge
    # the same account/instrument/settlement a second time.
    key = f"{account_id}|{instrument_id}|{settlement_timestamp.isoformat()}"
    return PaperFundingSettlement(
        account_id=account_id,
        instrument_id=instrument_id,
        settlement_timestamp=settlement_timestamp,
        signed_amount=signed_amount,
        currency=currency,
        rule_version=rule_version,
        idempotency_key=key,
    )


class FundingSettlementService:
    """Reuse canonical ledger for idempotent PAPER funding settlement."""

    def __init__(self, ledger) -> None:
        self.ledger = ledger

    async def settle(
        self,
        *,
        account_id: str,
        instrument_id: str,
        settlement_timestamp: datetime,
        signed_quantity: Decimal,
        mark_price: Decimal,
        funding_rate: Decimal,
        contract_size: Decimal,
        contract_multiplier: Decimal,
        currency: str = "USDT",
        rule_version: str = "v1",
    ) -> Decimal:
        settlement = compute_paper_funding(
            settlement_timestamp=settlement_timestamp,
            signed_quantity=signed_quantity,
            mark_price=mark_price,
            funding_rate=funding_rate,
            contract_size=contract_size,
            contract_multiplier=contract_multiplier,
            currency=currency,
            account_id=account_id,
            instrument_id=instrument_id,
            rule_version=rule_version,
        )
        return await self.ledger.apply_paper_funding_settlement(settlement)
