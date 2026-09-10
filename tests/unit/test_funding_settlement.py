from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.perpetual.funding_settlement import compute_paper_funding

TS = datetime(2026, 9, 10, 8, tzinfo=UTC)


def _compute(qty: str, rate: str):
    return compute_paper_funding(
        settlement_timestamp=TS,
        signed_quantity=Decimal(qty),
        mark_price=Decimal("100"),
        funding_rate=Decimal(rate),
        contract_size=Decimal("0.01"),
        contract_multiplier=Decimal("1"),
        instrument_id="BTC-USDT-SWAP",
    )


def test_paper_funding_signs_and_idempotency_key():
    long_positive = _compute("1", "0.001")
    short_positive = _compute("-1", "0.001")
    zero = _compute("1", "0")
    assert long_positive.signed_amount == Decimal("-0.001")
    assert short_positive.signed_amount == Decimal("0.001")
    assert zero.signed_amount == Decimal("0")
    assert "|v1" not in long_positive.idempotency_key
    assert long_positive.idempotency_key.startswith("default|BTC-USDT-SWAP|")


async def test_funding_settlement_service_is_idempotent():
    from crypto_trader.perpetual.funding_settlement import FundingSettlementService

    class FakeLedger:
        def __init__(self):
            self.calls = []

        async def apply_paper_funding_settlement(self, settlement):
            self.calls.append(settlement.idempotency_key)
            return settlement.signed_amount

    ledger = FakeLedger()
    service = FundingSettlementService(ledger)
    kwargs = dict(
        account_id="default",
        instrument_id="BTC-USDT-SWAP",
        settlement_timestamp=TS,
        signed_quantity=Decimal("-1"),
        mark_price=Decimal("100"),
        funding_rate=Decimal("0.001"),
        contract_size=Decimal("0.01"),
        contract_multiplier=Decimal("1"),
    )
    assert await service.settle(**kwargs) == Decimal("0.001")
    assert await service.settle(**kwargs) == Decimal("0.001")
    assert len(ledger.calls) == 2
    assert ledger.calls[0] == ledger.calls[1]
