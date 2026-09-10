"""P7: formal funding supervisor uses factual marks and PAPER_DERIVED settlement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.models import Position
from crypto_trader.perpetual.funding_coverage import FundingCoverage
from crypto_trader.perpetual.funding_runtime import FundingAccountingSupervisor

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)
OPENED = datetime(2026, 9, 10, 8, tzinfo=UTC)


@dataclass
class FakePlan:
    opened_at: datetime


class FakePlans:
    def __init__(self, opened_at=OPENED):
        self.opened_at = opened_at

    async def get_active_for_symbol(self, symbol):
        return FakePlan(self.opened_at) if self.opened_at else None

    async def latest_for_symbol(self, symbol):
        return FakePlan(self.opened_at) if self.opened_at else None


class FakeOrderManager:
    def __init__(self, quantity_at=None):
        self.quantity_at = quantity_at or (lambda _symbol, _at: Decimal("1"))
        self.calls = []

    async def signed_quantity_at(self, symbol, at):
        self.calls.append((symbol, at))
        return self.quantity_at(symbol, at)


class FakePortfolio:
    def __init__(self, position):
        self.position = position

    async def get_positions(self):
        return {"BTC-USDT-SWAP": self.position}


class FakeIngestor:
    def __init__(self, events, status="KNOWN_VALUE"):
        self.events = events
        self.status = status
        self.calls = []

    async def ingest(self, adapter, **kwargs):
        self.calls.append(kwargs)
        return FundingCoverage(
            instrument_id=kwargs["instrument_id"],
            window_start=kwargs["window_start"],
            window_end=kwargs["window_end"],
            coverage_status=self.status,
            pagination_complete=True,
            event_manifest_hash="sha256:test",
            gaps=[],
            rule_version="v1",
            fetched_count=len(self.events),
            window_event_count=len(self.events),
            boundary_proof=True,
            window_events=tuple(self.events),
        )


class FakeSettlement:
    def __init__(self):
        self.calls = []

    async def settle(self, **kwargs):
        self.calls.append(kwargs)
        return Decimal("0.001")


class FakeAdapter:
    def __init__(self, candles):
        self.candles = candles
        self.candle_calls = []

    async def get_candles(self, symbol, bar="1H", limit=100):
        self.candle_calls.append((symbol, bar, limit))
        return self.candles


def _position() -> Position:
    return Position(
        symbol="BTC-USDT-SWAP",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("1"),
        avg_entry_price=Decimal("100"),
        instrument_type="LINEAR_PERP",
        contract_size=Decimal("0.01"),
        contract_multiplier=Decimal("1"),
    )


def _event(hour: int, rate: str = "0.001") -> dict:
    return {
        "fundingTime": str(
            int(datetime(2026, 9, 10, hour, tzinfo=UTC).timestamp() * 1000)
        ),
        "realizedRate": rate,
    }


def _supervisor(
    *, events, candles, opened_at=OPENED, status="KNOWN_VALUE", quantity_at=None
):
    adapter = FakeAdapter(candles)
    ingestor = FakeIngestor(events, status=status)
    settlement = FakeSettlement()
    order_manager = FakeOrderManager(quantity_at=quantity_at)
    supervisor = FundingAccountingSupervisor(
        adapter=adapter,
        ingestor=ingestor,
        settlement_service=settlement,
        portfolio=FakePortfolio(_position()),
        trade_plans=FakePlans(opened_at),
        order_manager=order_manager,
        instruments_provider=lambda: {},
        lookback_hours=24,
    )
    return supervisor, ingestor, settlement, adapter


async def test_supervisor_settles_only_post_open_events_with_factual_mark():
    def candle(hour: int, close: str) -> list[str]:
        return [
            str(int(datetime(2026, 9, 10, hour, tzinfo=UTC).timestamp() * 1000)),
            "1",
            "1",
            "1",
            close,
        ]

    # The candle opening at 09:00 closes exactly at the 10:00 settlement.
    candles = [candle(8, "123.5"), candle(9, "124.5")]
    supervisor, ingestor, settlement, adapter = _supervisor(
        events=[_event(6), _event(10)], candles=candles
    )
    report = await supervisor.run_once(now=NOW)
    assert report.evaluated_instruments == ["BTC-USDT-SWAP"]
    assert report.coverage_status["BTC-USDT-SWAP"] == "KNOWN_VALUE"
    assert report.settled == 1
    assert len(settlement.calls) == 1
    call = settlement.calls[0]
    assert call["settlement_timestamp"] == datetime(2026, 9, 10, 10, tzinfo=UTC)
    assert call["mark_price"] == Decimal("124.5")
    assert call["signed_quantity"] == Decimal("1")
    assert adapter.candle_calls
    # The lookback window never starts before the factual position opened.
    assert ingestor.calls[0]["window_start"] == OPENED


async def test_historical_quantity_is_used_for_each_settlement():
    def candle(hour: int, close: str) -> list[str]:
        return [
            str(int(datetime(2026, 9, 10, hour, tzinfo=UTC).timestamp() * 1000)),
            "1",
            "1",
            "1",
            close,
        ]

    def quantity_at(_symbol, at):
        return Decimal("1") if at.hour == 8 else Decimal("0.4")

    candles = [candle(7, "100"), candle(9, "110")]
    supervisor, _, settlement, _ = _supervisor(
        events=[_event(8), _event(10)],
        candles=candles,
        quantity_at=quantity_at,
    )
    report = await supervisor.run_once(now=NOW)
    assert report.settled == 2
    quantities = {
        call["settlement_timestamp"].hour: call["signed_quantity"]
        for call in settlement.calls
    }
    # The 10:00 event uses the position held then, not the current/latest one.
    assert quantities == {8: Decimal("1"), 10: Decimal("0.4")}


async def test_settlement_never_uses_lookahead_candle():
    def candle(hour: int, close: str) -> list[str]:
        return [
            str(int(datetime(2026, 9, 10, hour, tzinfo=UTC).timestamp() * 1000)),
            "1",
            "1",
            "1",
            close,
        ]

    # Only a candle still open at 10:00 is available; it must not be used.
    supervisor, _, settlement, _ = _supervisor(
        events=[_event(10)], candles=[candle(10, "999")]
    )
    report = await supervisor.run_once(now=NOW)
    assert settlement.calls == []
    assert report.settled == 0
    assert any("SETTLEMENT_MARK_UNAVAILABLE" in item for item in report.skipped)


async def test_supervisor_skips_when_settlement_mark_is_unavailable():
    supervisor, _, settlement, _ = _supervisor(events=[_event(10)], candles=[])
    report = await supervisor.run_once(now=NOW)
    assert settlement.calls == []
    assert report.settled == 0
    assert any("SETTLEMENT_MARK_UNAVAILABLE" in item for item in report.skipped)


async def test_supervisor_skips_without_proven_position_open_time():
    supervisor, ingestor, settlement, _ = _supervisor(
        events=[_event(10)], candles=[], opened_at=None
    )
    report = await supervisor.run_once(now=NOW)
    assert ingestor.calls  # coverage may still be fetched...
    assert settlement.calls == []  # ...but no settlement without proven open time
    assert any("POSITION_OPEN_TIME_UNPROVEN" in item for item in report.skipped)


async def test_supervisor_does_not_settle_unknown_coverage():
    supervisor, _, settlement, _ = _supervisor(
        events=[_event(10)], candles=[], status="UNKNOWN"
    )
    report = await supervisor.run_once(now=NOW)
    assert settlement.calls == []
    assert any("FUNDING_COVERAGE_UNKNOWN" in item for item in report.skipped)


class FakeLedgerActivity:
    def __init__(self, instruments):
        self.instruments = set(instruments)

    async def activity_instruments(self, start, *, account_id, currency, end=None):
        return set(self.instruments)


class EmptyPortfolio:
    async def get_positions(self):
        return {}


async def test_closed_activity_instrument_receives_coverage_without_settlement():
    adapter = FakeAdapter([])
    ingestor = FakeIngestor([])
    settlement = FakeSettlement()
    supervisor = FundingAccountingSupervisor(
        adapter=adapter,
        ingestor=ingestor,
        settlement_service=settlement,
        portfolio=EmptyPortfolio(),
        trade_plans=FakePlans(OPENED),
        ledger=FakeLedgerActivity({"SOL-USDT-SWAP"}),
        order_manager=FakeOrderManager(),
        instruments_provider=lambda: {},
        lookback_hours=24,
    )
    report = await supervisor.run_once(now=NOW)
    assert report.evaluated_instruments == ["SOL-USDT-SWAP"]
    assert report.coverage_status["SOL-USDT-SWAP"] == "KNOWN_VALUE"
    assert settlement.calls == []
    assert ingestor.calls
