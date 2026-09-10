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
    symbol: str = "BTC-USDT-SWAP"
    trade_plan_id: str = "plan-p7"


class FakePlans:
    def __init__(self, opened_at=OPENED):
        self.opened_at = opened_at

    async def get_active_for_symbol(self, symbol):
        return FakePlan(self.opened_at, symbol=symbol)

    async def latest_for_symbol(self, symbol):
        return FakePlan(self.opened_at, symbol=symbol)

    async def lifecycles_overlapping(self, start, end):
        return [FakePlan(self.opened_at, symbol="BTC-USDT-SWAP")]


class FakeOrderManager:
    async def historical_quantity_at(
        self, *, account_id, symbol, at, currency="USDT"
    ):
        from crypto_trader.order.provenance import (
            HistoricalQuantityProvenance,
            HistoricalQuantityStatus,
        )

        return HistoricalQuantityProvenance(
            account_id=account_id,
            instrument_id=symbol,
            settlement_timestamp=at,
            status=HistoricalQuantityStatus.PROVEN_VALUE,
            quantity=Decimal("1"),
            source="FAKE_VERIFIED_FILLS",
        )

    async def signed_quantity_at(self, symbol, at):
        return Decimal("1")


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
            # 07:00 closes at 08:00; 09:00 closes at 10:00 (no lookahead).
            for hour, close in ((7, "100"), (9, "110"))
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
        ledger=ledger,
        order_manager=FakeOrderManager(),
        instruments_provider=lambda: {},
        lookback_hours=24,
    )
    first = await supervisor.run_once(now=NOW)
    second = await supervisor.run_once(now=NOW)
    assert first.settled == 1  # event exactly at opened_at is not funded
    assert second.settled == 0  # durable resolution dedupes the replay
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
    assert len(transactions) == 1
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


async def test_supervisor_uses_historical_fill_quantity_per_settlement(database):
    from crypto_trader.domain.enums import OrderSide, TradingMode
    from crypto_trader.domain.models import OrderIntent
    from crypto_trader.order.manager import OrderManager
    from crypto_trader.perpetual.funding_coverage import FundingCoverage
    from crypto_trader.persistence.models import FillORM

    order_manager = OrderManager(database.session_factory)
    order = await order_manager.create_from_intent(
        OrderIntent(
            client_order_id="p0_hist_order",
            symbol="BTC-USDT-SWAP",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("100"),
            strategy_id="p0-history",
        ),
        trading_mode=TradingMode.PAPER,
    )
    async with database.session_factory() as session:
        session.add(
            FillORM(
                fill_id="p0_hist_fill_buy",
                order_id=order.internal_order_id,
                symbol="BTC-USDT-SWAP",
                side="BUY",
                price=Decimal("100"),
                quantity=Decimal("1"),
                fee=Decimal("0"),
                timestamp=datetime(2026, 9, 10, 7, tzinfo=UTC),
            )
        )
        session.add(
            FillORM(
                fill_id="p0_hist_fill_sell",
                order_id=order.internal_order_id,
                symbol="BTC-USDT-SWAP",
                side="SELL",
                price=Decimal("105"),
                quantity=Decimal("0.6"),
                fee=Decimal("0"),
                timestamp=datetime(2026, 9, 10, 9, 30, tzinfo=UTC),
            )
        )
        await session.commit()

    from crypto_trader.domain.enums import LedgerDirection, LedgerEntryType
    from crypto_trader.domain.money import D as _D
    from crypto_trader.ledger.service import LedgerPosting, LedgerService

    ledger = LedgerService(database.session_factory)
    for fill_id, stamp in (
        ("p0_hist_fill_buy", datetime(2026, 9, 10, 7, tzinfo=UTC)),
        ("p0_hist_fill_sell", datetime(2026, 9, 10, 9, 30, tzinfo=UTC)),
    ):
        await ledger.record(
            LedgerEntryType.TRADE,
            [
                LedgerPosting("CASH", LedgerDirection.DEBIT, _D("1")),
                LedgerPosting("REALIZED_PNL", LedgerDirection.CREDIT, _D("1")),
            ],
            account_id="default",
            instrument_id="BTC-USDT-SWAP",
            fill_id=fill_id,
            transaction_id=f"txn_{fill_id}",
            created_at=stamp,
        )

    class CaptureIngestor:
        async def ingest(self, adapter, **kwargs):
            return FundingCoverage(
                instrument_id=kwargs["instrument_id"],
                window_start=kwargs["window_start"],
                window_end=kwargs["window_end"],
                coverage_status="KNOWN_VALUE",
                pagination_complete=True,
                event_manifest_hash="sha256:test",
                gaps=[],
                rule_version="v1",
                boundary_proof=True,
                fetched_count=2,
                window_event_count=2,
                window_events=(
                    PublicFactualAdapter._event(8, "0.001"),
                    PublicFactualAdapter._event(10, "0.002"),
                ),
            )

    class CaptureSettlement:
        def __init__(self):
            self.calls = []

        async def settle(self, **kwargs):
            self.calls.append(kwargs)
            return Decimal("0.001")

    settlement = CaptureSettlement()
    supervisor = FundingAccountingSupervisor(
        adapter=PublicFactualAdapter(),
        ingestor=CaptureIngestor(),
        settlement_service=settlement,
        portfolio=FakePortfolio(),
        trade_plans=FakePlans(
            opened_at=datetime(2026, 9, 10, 7, 30, tzinfo=UTC)
        ),
        ledger=ledger,
        order_manager=order_manager,
        instruments_provider=lambda: {},
        lookback_hours=24,
    )
    report = await supervisor.run_once(now=NOW)
    assert report.settled == 2
    quantities = {
        call["settlement_timestamp"].hour: call["signed_quantity"]
        for call in settlement.calls
    }
    assert quantities == {8: Decimal("1"), 10: Decimal("0.4")}
