from datetime import UTC, datetime, timedelta, timezone
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


def test_equivalent_offsets_produce_one_canonical_identity():
    instants = [
        datetime(2026, 9, 10, 8, tzinfo=UTC),
        datetime(2026, 9, 10, 16, tzinfo=timezone(timedelta(hours=8))),
        datetime(2026, 9, 10, 3, tzinfo=timezone(timedelta(hours=-5))),
    ]
    settlements = [
        compute_paper_funding(
            settlement_timestamp=instant,
            signed_quantity=Decimal("-1"),
            mark_price=Decimal("100"),
            funding_rate=Decimal("0.001"),
            contract_size=Decimal("0.01"),
            contract_multiplier=Decimal("1"),
            instrument_id="BTC-USDT-SWAP",
        )
        for instant in instants
    ]
    keys = {settlement.idempotency_key for settlement in settlements}
    assert len(keys) == 1
    assert keys.pop() == "default|BTC-USDT-SWAP|2026-09-10T08:00:00Z"
    assert all(
        settlement.settlement_timestamp == datetime(2026, 9, 10, 8, tzinfo=UTC)
        for settlement in settlements
    )


def test_rule_version_does_not_change_business_identity():
    first = compute_paper_funding(
        settlement_timestamp=TS,
        signed_quantity=Decimal("-1"),
        mark_price=Decimal("100"),
        funding_rate=Decimal("0.001"),
        contract_size=Decimal("0.01"),
        contract_multiplier=Decimal("1"),
        instrument_id="BTC-USDT-SWAP",
        rule_version="v1",
    )
    second = compute_paper_funding(
        settlement_timestamp=TS,
        signed_quantity=Decimal("-1"),
        mark_price=Decimal("100"),
        funding_rate=Decimal("0.001"),
        contract_size=Decimal("0.01"),
        contract_multiplier=Decimal("1"),
        instrument_id="BTC-USDT-SWAP",
        rule_version="v2",
    )
    assert first.idempotency_key == second.idempotency_key


def test_account_and_instrument_isolate_identity():
    def identity(account: str, instrument: str) -> str:
        return compute_paper_funding(
            settlement_timestamp=TS,
            signed_quantity=Decimal("-1"),
            mark_price=Decimal("100"),
            funding_rate=Decimal("0.001"),
            contract_size=Decimal("0.01"),
            contract_multiplier=Decimal("1"),
            account_id=account,
            instrument_id=instrument,
        ).idempotency_key

    a_btc = identity("account-a", "BTC-USDT-SWAP")
    b_btc = identity("account-b", "BTC-USDT-SWAP")
    a_sol = identity("account-a", "SOL-USDT-SWAP")
    assert len({a_btc, b_btc, a_sol}) == 3


def test_naive_settlement_timestamp_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        compute_paper_funding(
            settlement_timestamp=datetime(2026, 9, 10, 8),
            signed_quantity=Decimal("-1"),
            mark_price=Decimal("100"),
            funding_rate=Decimal("0.001"),
            contract_size=Decimal("0.01"),
            contract_multiplier=Decimal("1"),
            instrument_id="BTC-USDT-SWAP",
        )
