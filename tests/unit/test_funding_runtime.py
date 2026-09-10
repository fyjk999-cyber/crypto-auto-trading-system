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


def _supervisor(*, events, candles, opened_at=OPENED, status="KNOWN_VALUE"):
    adapter = FakeAdapter(candles)
    ingestor = FakeIngestor(events, status=status)
    settlement = FakeSettlement()
    supervisor = FundingAccountingSupervisor(
        adapter=adapter,
        ingestor=ingestor,
        settlement_service=settlement,
        portfolio=FakePortfolio(_position()),
        trade_plans=FakePlans(opened_at),
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

    candles = [candle(8, "123.5"), candle(10, "124.5")]
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
    assert ingestor.calls == []
    assert settlement.calls == []
    assert any("POSITION_OPEN_TIME_UNPROVEN" in item for item in report.skipped)


async def test_supervisor_does_not_settle_unknown_coverage():
    supervisor, _, settlement, _ = _supervisor(
        events=[_event(10)], candles=[], status="UNKNOWN"
    )
    report = await supervisor.run_once(now=NOW)
    assert settlement.calls == []
    assert any("FUNDING_COVERAGE_UNKNOWN" in item for item in report.skipped)
