from datetime import UTC, datetime, timedelta

from crypto_trader.perpetual.funding_coverage import (
    FundingCoverage,
    FundingHistoryIngestor,
)

START = datetime(2026, 9, 10, 0, tzinfo=UTC)
END = datetime(2026, 9, 10, 8, tzinfo=UTC)


class FakeCoverage:
    def __init__(self):
        self.recorded = None

    async def record(self, **kwargs):
        self.recorded = kwargs
        return FundingCoverage(
            instrument_id=kwargs["instrument_id"],
            window_start=kwargs["window_start"],
            window_end=kwargs["window_end"],
            coverage_status=kwargs["coverage_status"],
            pagination_complete=kwargs["pagination_complete"],
            event_manifest_hash=kwargs.get("event_manifest_hash"),
            gaps=list(kwargs.get("gaps") or []),
            rule_version=kwargs.get("rule_version", "v1"),
            fetched_count=kwargs.get("fetched_count", 0),
            window_event_count=kwargs.get("window_event_count", 0),
            boundary_proof=kwargs.get("boundary_proof", False),
        )


class FakeAdapter:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []
        self.afters = []

    async def get_funding_rate_history(self, symbol, *, before=None, after=None, limit=100):
        self.calls.append(before)
        self.afters.append(after)
        return self.pages.pop(0)


def _row(ts, rate):
    return {"fundingTime": str(int(ts.timestamp() * 1000)), "realizedRate": rate}


async def test_ingest_complete_history_is_known_value():
    coverage = FakeCoverage()
    rows = [
        _row(START, "0.0001"),
        _row(START + timedelta(hours=4), "0.0002"),
        _row(START + timedelta(hours=8), "0.0001"),
    ]
    adapter = FakeAdapter([list(reversed(rows)), []])
    result = await FundingHistoryIngestor(coverage).ingest(
        adapter, instrument_id="BTC-USDT-SWAP", window_start=START, window_end=END
    )
    assert result.coverage_status == "KNOWN_VALUE"
    assert result.pagination_complete is True
    assert result.gaps == []


async def test_ingest_detects_unexpected_gap_as_unknown():
    coverage = FakeCoverage()
    rows = [
        _row(START, "0.0001"),
        _row(START + timedelta(hours=1), "0.0001"),
        _row(START + timedelta(hours=7), "0.0001"),
    ]
    adapter = FakeAdapter([list(reversed(rows)), []])
    result = await FundingHistoryIngestor(coverage).ingest(
        adapter, instrument_id="BTC-USDT-SWAP", window_start=START, window_end=END
    )
    assert result.coverage_status == "UNKNOWN"
    assert result.gaps


async def test_empty_unproven_window_is_unknown_not_zero():
    coverage = FakeCoverage()
    adapter = FakeAdapter([[]])
    result = await FundingHistoryIngestor(coverage).ingest(
        adapter, instrument_id="BTC-USDT-SWAP", window_start=START, window_end=END
    )
    assert result.coverage_status == "UNKNOWN"
    assert result.pagination_complete is False


async def test_missing_realized_rate_is_unknown():
    coverage = FakeCoverage()
    rows = [
        {"fundingTime": str(int(START.timestamp() * 1000)), "realizedRate": ""},
    ]
    adapter = FakeAdapter([rows])
    result = await FundingHistoryIngestor(coverage).ingest(
        adapter, instrument_id="BTC-USDT-SWAP", window_start=START, window_end=END
    )
    assert result.coverage_status == "UNKNOWN"


async def test_boundary_crossing_raw_page_proves_completion():
    coverage = FakeCoverage()
    # Non-settlement window boundary (02:00). The raw page contains a record
    # before window_start AND an in-window record. Filtering before evaluating
    # completion would lose the lower-bound proof.
    rows = [
        _row(datetime(2026, 9, 10, 4, tzinfo=UTC), "0.0002"),
        _row(datetime(2026, 9, 10, 0, tzinfo=UTC), "0.0001"),
    ]
    adapter = FakeAdapter([rows])
    result = await FundingHistoryIngestor(coverage).ingest(
        adapter,
        instrument_id="BTC-USDT-SWAP",
        window_start=datetime(2026, 9, 10, 2, tzinfo=UTC),
        window_end=END,
    )
    assert result.coverage_status == "KNOWN_VALUE"
    assert result.pagination_complete is True
    assert result.boundary_proof is True
    assert result.fetched_count == 2
    assert result.window_event_count == 1
    assert result.event_manifest_hash is not None
    assert result.event_manifest_hash.startswith("sha256:")


async def test_boundary_crossing_page_without_window_events_is_known_zero():
    coverage = FakeCoverage()
    rows = [_row(datetime(2026, 9, 10, 0, tzinfo=UTC), "0.0001")]
    adapter = FakeAdapter([rows])
    result = await FundingHistoryIngestor(coverage).ingest(
        adapter,
        instrument_id="BTC-USDT-SWAP",
        window_start=datetime(2026, 9, 10, 2, tzinfo=UTC),
        window_end=END,
    )
    assert result.coverage_status == "KNOWN_ZERO"
    assert result.pagination_complete is True
    assert result.boundary_proof is True
    assert result.window_event_count == 0


async def test_exhausted_max_pages_is_unknown_not_zero():
    coverage = FakeCoverage()
    rows = [_row(datetime(2026, 9, 10, 4, tzinfo=UTC), "0.0001")]
    adapter = FakeAdapter([rows])
    result = await FundingHistoryIngestor(coverage).ingest(
        adapter,
        instrument_id="BTC-USDT-SWAP",
        window_start=START,
        window_end=END,
        max_pages=1,
    )
    assert result.coverage_status == "UNKNOWN"
    assert result.pagination_complete is False
    assert result.boundary_proof is False
    # The cursor used for the next page is the oldest RAW record.
    assert adapter.afters == [str(int(END.timestamp() * 1000))]
