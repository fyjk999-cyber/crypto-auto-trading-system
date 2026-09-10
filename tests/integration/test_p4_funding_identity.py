"""P4: one economic settlement has exactly one ledger identity across offsets."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from crypto_trader.ledger.service import LedgerService
from crypto_trader.perpetual.funding_settlement import (
    PaperFundingSettlement,
    compute_paper_funding,
)
from crypto_trader.persistence.models import LedgerTransactionORM


@pytest.fixture
def ledger(database):
    return LedgerService(database.session_factory)


def _settlement(timestamp: datetime, *, rule_version: str = "v1") -> PaperFundingSettlement:
    return compute_paper_funding(
        settlement_timestamp=timestamp,
        signed_quantity=Decimal("-1"),
        mark_price=Decimal("100"),
        funding_rate=Decimal("0.001"),
        contract_size=Decimal("0.01"),
        contract_multiplier=Decimal("1"),
        instrument_id="BTC-USDT-SWAP",
        rule_version=rule_version,
    )


async def _funding_transaction_count(database) -> int:
    async with database.session_factory() as session:
        rows = (
            await session.execute(
                select(LedgerTransactionORM).where(
                    LedgerTransactionORM.entry_type.in_(
                        ("FUNDING_RECEIPT", "FUNDING_PAYMENT")
                    )
                )
            )
        ).scalars().all()
    return len(rows)


async def test_equivalent_offsets_charge_once(ledger, database):
    instants = [
        datetime(2026, 9, 10, 8, tzinfo=UTC),
        datetime(2026, 9, 10, 16, tzinfo=timezone(timedelta(hours=8))),
        datetime(2026, 9, 10, 3, tzinfo=timezone(timedelta(hours=-5))),
    ]
    results = [
        await ledger.apply_paper_funding_settlement(_settlement(instant))
        for instant in instants
    ]
    assert results == [Decimal("0.001")] * 3
    assert await _funding_transaction_count(database) == 1


async def test_rule_version_cannot_duplicate_economic_settlement(ledger, database):
    timestamp = datetime(2026, 9, 10, 8, tzinfo=UTC)
    await ledger.apply_paper_funding_settlement(_settlement(timestamp, rule_version="v1"))
    await ledger.apply_paper_funding_settlement(_settlement(timestamp, rule_version="v2"))
    assert await _funding_transaction_count(database) == 1


async def test_caller_key_is_recanonicalized_before_write(ledger, database):
    timestamp = datetime(2026, 9, 10, 8, tzinfo=UTC)
    canonical = _settlement(timestamp)
    forged = PaperFundingSettlement(
        account_id=canonical.account_id,
        instrument_id=canonical.instrument_id,
        settlement_timestamp=canonical.settlement_timestamp,
        signed_amount=canonical.signed_amount,
        currency=canonical.currency,
        rule_version="forged",
        idempotency_key="bogus-key-from-caller",
    )
    await ledger.apply_paper_funding_settlement(canonical)
    await ledger.apply_paper_funding_settlement(forged)
    assert await _funding_transaction_count(database) == 1
    async with database.session_factory() as session:
        row = (await session.execute(select(LedgerTransactionORM))).scalar_one()
    assert row.event_id == "default|BTC-USDT-SWAP|2026-09-10T08:00:00Z"
    assert row.metadata_json["settlement_timestamp"] == "2026-09-10T08:00:00Z"
    assert row.created_at.replace(tzinfo=UTC) == timestamp
