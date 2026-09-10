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
        )


class FakeAdapter:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def get_funding_rate_history(self, symbol, *, before=None, after=None, limit=100):
        self.calls.append(before)
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
