"""P7: formal build_system funding chain, PAPER_DERIVED accounting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.config import Settings
from crypto_trader.domain.models import Position
from crypto_trader.ledger.service import LedgerService
from crypto_trader.perpetual.funding_coverage import (
    FundingCoverageService,
    FundingHistoryIngestor,
)
from crypto_trader.perpetual.funding_runtime import FundingAccountingSupervisor
from crypto_trader.perpetual.funding_settlement import FundingSettlementService
from crypto_trader.persistence.models import FundingCoverageORM, LedgerTransactionORM
from crypto_trader.runtime.bootstrap import build_system

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)
OPENED = datetime(2026, 9, 10, 8, tzinfo=UTC)


@dataclass
class FakePlan:
    opened_at: datetime


class FakePlans:
    async def get_active_for_symbol(self, symbol):
        return FakePlan(OPENED)


class FakePortfolio:
    async def get_positions(self):
        return {
            "BTC-USDT-SWAP": Position(
                symbol="BTC-USDT-SWAP",
                base_asset="BTC",
                quote_asset="USDT",
                quantity=Decimal("1"),
                avg_entry_price=Decimal("100"),
                instrument_type="LINEAR_PERP",
                contract_size=Decimal("0.01"),
                contract_multiplier=Decimal("1"),
            )
        }


class PublicFactualAdapter:
    def __init__(self):
        self.events = [
            self._event(8, "0.001"),
            self._event(10, "0.002"),
        ]
        self.history_calls = 0

    @staticmethod
    def _event(hour: int, rate: str) -> dict:
        return {
            "fundingTime": str(
                int(datetime(2026, 9, 10, hour, tzinfo=UTC).timestamp() * 1000)
            ),
            "realizedRate": rate,
        }

    async def get_funding_rate_history(self, symbol, *, before=None, after=None, limit=100):
        self.history_calls += 1
        # Same factual page on every run, like a real exchange feed.
        return list(self.events)

    async def get_candles(self, symbol, bar="1H", limit=100):
        return [
            [
                str(int(datetime(2026, 9, 10, hour, tzinfo=UTC).timestamp() * 1000)),
                "1",
                "1",
                "1",
                close,
            ]
            for hour, close in ((8, "100"), (10, "110"))
        ]


async def test_build_system_wires_formal_funding_and_valuation_services(database):
    settings = Settings(
        _env_file=None,
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        database_url=database.url,
        auto_start_runtime=False,
        paper_mode="PAPER_SYNTHETIC",
    )
    bundle = await build_system(settings)
    try:
        engine = bundle.engine
        assert engine.funding_supervisor is not None
        assert isinstance(engine.funding_supervisor.ingestor, FundingHistoryIngestor)
        assert isinstance(
            engine.funding_supervisor.settlement_service, FundingSettlementService
        )
        assert isinstance(engine.funding_coverage, FundingCoverageService)
        assert engine.funding_supervisor.ingestor.coverage_service is engine.funding_coverage
        assert engine.valuations is not None
    finally:
        await bundle.database.close()


async def test_supervisor_real_chain_settles_once_and_marks_paper_derived(database):
    ledger = LedgerService(database.session_factory)
    coverage_service = FundingCoverageService(database.session_factory)
    ingestor = FundingHistoryIngestor(coverage_service)
    settlement = FundingSettlementService(ledger)
    adapter = PublicFactualAdapter()
    supervisor = FundingAccountingSupervisor(
        adapter=adapter,
        ingestor=ingestor,
        settlement_service=settlement,
        portfolio=FakePortfolio(),
        trade_plans=FakePlans(),
        instruments_provider=lambda: {},
        lookback_hours=24,
    )
    first = await supervisor.run_once(now=NOW)
    second = await supervisor.run_once(now=NOW)
    assert first.settled == 2
    assert second.settled == 2  # replayed, but ledger identity dedupes
    async with database.session_factory() as session:
        transactions = (
            await session.execute(
                select(LedgerTransactionORM).where(
                    LedgerTransactionORM.entry_type.in_(
                        ("FUNDING_RECEIPT", "FUNDING_PAYMENT")
                    )
                )
            )
        ).scalars().all()
        coverage_rows = (
            await session.execute(select(FundingCoverageORM))
        ).scalars().all()
    assert len(transactions) == 2
    assert all(txn.metadata_json["source"] == "PAPER_DERIVED" for txn in transactions)
    assert all(txn.account_id == "default" for txn in transactions)
    assert all(txn.instrument_id == "BTC-USDT-SWAP" for txn in transactions)
    assert all(txn.ownership_status == "VERIFIED" for txn in transactions)
    assert len(coverage_rows) == 1
    coverage = coverage_rows[0]
    assert coverage.pagination_complete is True
    assert coverage.boundary_proof is True
    assert coverage.coverage_status == "KNOWN_VALUE"
    assert coverage.event_manifest_hash.startswith("sha256:")
    # Every posting is dated at the factual settlement instant, not run time.
    assert {txn.created_at.strftime("%H:%M") for txn in transactions} == {
        "08:00",
        "10:00",
    }


async def test_active_position_funding_window_matches_supervisor(database):
    """P0 provenance and P7 supervisor use the same opened_at-aligned window."""
    ledger = LedgerService(database.session_factory)
    coverage_service = FundingCoverageService(database.session_factory)
    await coverage_service.record(
        instrument_id="BTC-USDT-SWAP",
        window_start=OPENED,
        window_end=NOW,
        coverage_status="KNOWN_VALUE",
        pagination_complete=True,
        boundary_proof=True,
        event_manifest_hash="sha256:test",
        fetched_count=1,
        window_event_count=1,
    )
    settlement = FundingSettlementService(ledger)
    await settlement.settle(
        account_id="default",
        instrument_id="BTC-USDT-SWAP",
        settlement_timestamp=datetime(2026, 9, 10, 10, tzinfo=UTC),
        signed_quantity=Decimal("1"),
        mark_price=Decimal("110"),
        funding_rate=Decimal("0.002"),
        contract_size=Decimal("0.01"),
        contract_multiplier=Decimal("1"),
    )
    daily_start = datetime(2026, 9, 10, 0, tzinfo=UTC)
    provenance = await ledger.net_pnl_provenance_since(
        daily_start,
        account_id="default",
        currency="USDT",
        instrument_ids=["BTC-USDT-SWAP"],
        end=NOW,
        coverage_status_by_instrument={"BTC-USDT-SWAP": "KNOWN_VALUE"},
        instrument_window_starts={"BTC-USDT-SWAP": OPENED},
    )
    assert provenance.complete is True
    assert provenance.funding_status == "KNOWN_VALUE"
    assert provenance.funding_amount == Decimal("-0.0022")
