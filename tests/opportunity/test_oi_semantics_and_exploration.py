"""P0/P1 convergence tests: OI contract semantics, snapshot status vs coverage,
and ChiefTrader-controlled directory exploration.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from crypto_trader.llm_chief.budget import (
    P4_MARKET_SELECTION,
    BudgetConfig,
    GlobalLLMBudget,
)
from crypto_trader.llm_chief.engine import MarketSelectionResult
from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.directory import MarketDirectory
from crypto_trader.market_data.opportunity.scanner import FactorScanner
from crypto_trader.market_data.opportunity.selection import (
    MarketSelectionService,
    parse_selection_payload,
)
from crypto_trader.market_data.opportunity.service import (
    OpportunityScannerService,
    ScannerConfig,
)
from crypto_trader.market_data.opportunity.snapshot import (
    STATUS_COMPLETE,
    STATUS_PARTIAL,
)
from crypto_trader.market_data.opportunity.universe import Instrument
from crypto_trader.market_data.quality import (
    MISSING,
    NOT_SAMPLED,
    REQUEST_FAILED,
    VALID,
)

SYMBOLS = ("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT", "EEEUSDT", "FFFUSDT")


class FakeUniverse:
    class _Snap:
        instruments = {
            symbol: Instrument(
                symbol=symbol,
                inst_id=f"{symbol[:-4]}-USDT-SWAP",
                state="live",
                settle_ccy="USDT",
                ct_val="1",
                list_time=None,
                raw={},
            )
            for symbol in SYMBOLS
        }
        size = len(SYMBOLS)

    async def refresh(self, force=False):
        return self._Snap()


def _inst(symbol: str) -> str:
    return f"{symbol[:-4]}-USDT-SWAP"


class OiClient:
    """Configurable fake OKX client focused on OI contract behaviour."""

    def __init__(
        self,
        *,
        oi_rows=None,
        oi_error: Exception | None = None,
        oi_ts: str | None = None,
        oi_value: str = "1234.5",
        candle_error_symbols=(),
        candles_ok: bool = True,
        fallback_enabled: bool = True,
    ) -> None:
        self.oi_error = oi_error
        self.oi_ts = oi_ts if oi_ts is not None else str(int(datetime.now(UTC).timestamp() * 1000))
        self.oi_value = oi_value
        self.oi_rows = oi_rows
        self.candle_error_symbols = set(candle_error_symbols)
        self.candles_ok = candles_ok
        self.fallback_enabled = fallback_enabled
        self.oi_calls = 0
        self.fallback_calls = 0

    async def get_tickers(self, inst_type):
        ts = str(int(datetime.now(UTC).timestamp() * 1000))
        return [
            {
                "instId": _inst(symbol),
                "last": "10",
                "open24h": "9",
                "bidPx": "9.99",
                "askPx": "10.01",
                "bidSz": "100",
                "askSz": "100",
                "vol24h": "1000",
                "volCcy24h": "1000000",  # 10M USD estimated turnover -> eligible
                "ts": ts,
            }
            for symbol in SYMBOLS
        ]

    async def get_open_interests(self, inst_type):
        self.oi_calls += 1
        if self.oi_error is not None:
            raise self.oi_error
        if self.oi_rows is not None:
            return self.oi_rows
        return [
            {
                "instId": _inst(symbol),
                "instType": "SWAP",
                "oi": self.oi_value,
                "oiCcy": self.oi_value,
                "oiUsd": "12345.6",
                "ts": self.oi_ts,
            }
            for symbol in SYMBOLS
        ]

    async def get_open_interest(self, inst_id):
        self.fallback_calls += 1
        if not self.fallback_enabled:
            raise RuntimeError("fallback disabled")
        return {
            "open_interest": self.oi_value,
            "open_interest_ccy": self.oi_value,
            "open_interest_usd": "12345.6",
            "source_timestamp": self.oi_ts,
        }

    async def get_funding_rates(self, inst_type):
        return [
            {"instId": _inst(symbol), "fundingRate": "0.0001"} for symbol in SYMBOLS
        ]

    async def get_funding_rate_fallback(self, inst_id):
        return {"fundingRate": "0.0001"}

    async def get_candles(self, inst_id, bar, limit):
        if inst_id in self.candle_error_symbols:
            raise RuntimeError("provider down")
        if not self.candles_ok:
            return []
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        return [
            [str(now_ms - index * 60_000), "10", "10.5", "9.5", "10", "100", "0", "0", "1"]
            for index in range(1, 61)
        ]


@pytest.fixture(autouse=True)
def _isolated_shared_cache():
    """Each test gets a clean canonical cache (the production one is shared)."""
    from crypto_trader.market_data.cache import reset_shared_market_data_cache

    reset_shared_market_data_cache()
    yield
    reset_shared_market_data_cache()


def _scan(client, **config_kwargs):
    from crypto_trader.market_data.cache import MarketDataCache

    board = OpportunityBoard()
    service = OpportunityScannerService(
        universe=FakeUniverse(),
        okx_client=client,
        board=board,
        scanner=FactorScanner(factors=()),
        config=ScannerConfig(candle_limit=120, **config_kwargs),
        cache=MarketDataCache(),
    )
    summary = asyncio.run(service.scan_once())
    return board, summary


# ------------------------------------------------------------------ OI contract
def test_broad_oi_response_maps_every_instrument_by_identity():
    board, summary = _scan(OiClient())
    snapshot = board.current_snapshot()
    rows = {row["symbol"]: row for row in snapshot.observable_rows}
    assert set(rows) == set(SYMBOLS)
    for symbol in SYMBOLS:
        assert rows[symbol]["oi_quality"] == VALID
        assert rows[symbol]["open_interest"] == pytest.approx(1234.5)
        assert rows[symbol]["open_interest_usd"] == pytest.approx(12345.6)
        assert rows[symbol]["oi_observed_at"] is not None
    assert summary["feature_coverage"]["oi_coverage_count"] == len(SYMBOLS)
    assert summary["feature_coverage"]["oi_coverage_ratio"] == 1.0
    assert snapshot.data_quality_summary["open_interest_collection"]["collected"] == len(SYMBOLS)


def test_broad_oi_endpoint_uses_one_request_not_per_instrument():
    client = OiClient()
    _scan(client)
    assert client.oi_calls == 1
    assert client.fallback_calls == 0


def test_valid_zero_oi_is_preserved_as_a_fact():
    board, _ = _scan(OiClient(oi_value="0"))
    row = board.current_snapshot().observable_rows[0]
    assert row["open_interest"] == 0.0
    assert row["oi_quality"] == VALID


def test_oi_request_failure_is_reported_not_zero():
    board, summary = _scan(OiClient(oi_error=RuntimeError("okx 500")))
    snapshot = board.current_snapshot()
    for row in snapshot.observable_rows:
        assert row["open_interest"] is None
        assert row["oi_quality"] == REQUEST_FAILED
    assert summary["status"] == STATUS_PARTIAL
    assert snapshot.data_quality_summary["batch"]["open_interest"] == REQUEST_FAILED


def test_oi_malformed_and_non_finite_values_are_rejected():
    client = OiClient(
        fallback_enabled=False,
        oi_rows=[
            {"instId": _inst("AAAUSDT"), "oi": "not-a-number", "ts": client_ts()},
            {"instId": _inst("BBBUSDT"), "oi": "NaN", "ts": client_ts()},
            {"instId": _inst("CCCUSDT"), "oi": "", "ts": client_ts()},
        ]
    )
    board, _ = _scan(client)
    rows = {row["symbol"]: row for row in board.current_snapshot().observable_rows}
    assert rows["AAAUSDT"]["open_interest"] is None
    assert rows["BBBUSDT"]["open_interest"] is None
    assert rows["CCCUSDT"]["open_interest"] is None
    # symbols absent from the response are NOT_SAMPLED, never UNSUPPORTED
    assert rows["DDDUSDT"]["oi_quality"] == NOT_SAMPLED


def test_oi_supported_but_missing_instrument_is_not_sampled_not_unsupported():
    client = OiClient(
        fallback_enabled=False,
        oi_rows=[{"instId": _inst("AAAUSDT"), "oi": "10", "ts": client_ts()}],
    )
    board, _ = _scan(client)
    rows = {row["symbol"]: row for row in board.current_snapshot().observable_rows}
    assert rows["AAAUSDT"]["oi_quality"] == VALID
    for symbol in ("BBBUSDT", "CCCUSDT", "DDDUSDT", "EEEUSDT", "FFFUSDT"):
        # the provider supports these instruments; we simply did not collect
        # them in this pass -> NOT_SAMPLED (coverage), never UNSUPPORTED
        assert rows[symbol]["oi_quality"] == NOT_SAMPLED
        assert rows[symbol]["oi_quality"] != "UNSUPPORTED"


def test_oi_future_timestamp_is_not_treated_as_valid():
    future = str(int((datetime.now(UTC) + timedelta(minutes=30)).timestamp() * 1000))
    board, _ = _scan(OiClient(oi_ts=future))
    row = board.current_snapshot().observable_rows[0]
    assert row["oi_quality"] != VALID
    assert row["open_interest"] is None


def test_oi_stale_timestamp_is_reported_stale():
    stale = str(int((datetime.now(UTC) - timedelta(hours=2)).timestamp() * 1000))
    board, _ = _scan(OiClient(oi_ts=stale))
    row = board.current_snapshot().observable_rows[0]
    assert row["oi_quality"] == "STALE"


def client_ts() -> str:
    return str(int(datetime.now(UTC).timestamp() * 1000))


# ------------------------------------------------- status vs feature coverage
def test_bounded_analysis_coverage_is_not_a_partial_scan():
    """Designed bounded coverage (active set << universe) => COMPLETE."""
    client = OiClient()
    board, summary = _scan(client, active_set_size=3, rotation_size=0)
    snapshot = board.current_snapshot()
    assert summary["status"] == STATUS_COMPLETE
    coverage = summary["feature_coverage"]
    assert coverage["analysis_attempted_count"] == 3
    assert coverage["universe_count"] == len(SYMBOLS)
    # partial FEATURE coverage while execution status stays COMPLETE
    assert coverage["ticker_coverage_ratio"] == 1.0
    assert coverage["funding_coverage_ratio"] == 1.0
    assert coverage["oi_coverage_ratio"] == 1.0
    assert snapshot.feature_coverage["analysis_attempted_count"] < len(SYMBOLS)
    assert snapshot.status == STATUS_COMPLETE


def test_unexpected_provider_failure_still_marks_the_scan_partial():
    client = OiClient(candle_error_symbols={_inst("AAAUSDT")})
    board, summary = _scan(client, active_set_size=3, rotation_size=0)
    snapshot = board.current_snapshot()
    assert summary["status"] == STATUS_PARTIAL
    assert snapshot.status == STATUS_PARTIAL
    assert any(
        note.startswith("candle_fetch_errors") for note in snapshot.data_quality_summary["notes"]
    )


def test_provider_failure_outranks_bounded_coverage_in_status():
    client = OiClient(oi_error=RuntimeError("down"))
    _, summary = _scan(client, active_set_size=3, rotation_size=0)
    assert summary["status"] == STATUS_PARTIAL
    assert summary["feature_coverage"]["analysis_attempted_count"] == 3


# -------------------------------------------------- active directory exploration
def _snapshot_rows(count: int = 60):
    rows = []
    for index in range(count):
        rows.append(
            {
                "symbol": f"S{index}USDT",
                "last": 100.0,
                "price_change_24h_pct": float(index),
                "vol_usd_24h": float(100_000 - index),
                "funding_rate": 0.0001,
                "funding_quality": VALID,
                "open_interest": 1000.0,
                "oi_quality": VALID,
                "ticker_quality": VALID,
                "execution_supported": True,
                "eligible": True,
                "excluded_reasons": (),
            }
        )
    return tuple(rows)


def _board_with_rows(count: int = 60) -> OpportunityBoard:
    board = OpportunityBoard()
    now = datetime.now(UTC)
    from crypto_trader.market_data.opportunity.snapshot import MarketObservationSnapshot

    board.publish_snapshot(
        MarketObservationSnapshot(
            scan_id="scan-explore",
            started_at=now,
            completed_at=now,
            expires_at=now + timedelta(seconds=180),
            status=STATUS_COMPLETE,
            discovered_count=count,
            observable_count=count,
            analysis_attempted_count=0,
            execution_supported_count=count,
            observable_rows=_snapshot_rows(count),
        )
    )
    return board


class PhasedChief:
    """Records every phase's context and returns scripted payloads."""

    def __init__(self, payloads) -> None:
        self.payloads = list(payloads)
        self.contexts: list[dict] = []

    async def select_markets(
        self, context, *, timeout_seconds, selection_id, scan_id, known_symbols=None
    ):
        self.contexts.append(context)
        payload = self.payloads[min(len(self.contexts) - 1, len(self.payloads) - 1)]
        parsed = parse_selection_payload(payload, selection_id=selection_id, scan_id=scan_id)
        if isinstance(parsed, str):
            return MarketSelectionResult(
                ok=False, status="INVALID_OUTPUT", error_code=parsed, provider="deepseek"
            )
        return MarketSelectionResult(
            ok=True,
            status="SUCCESS",
            output=parsed,
            provider="deepseek",
            model="deepseek-flash",
            latency_ms=10,
            input_tokens=100,
            output_tokens=20,
        )


def test_request_directory_is_a_bounded_read_only_lookup():
    board = _board_with_rows()
    directory = MarketDirectory(board=board, page_size=20, max_pages=2)
    chief = PhasedChief(
        [
            {
                "selection_state": "REQUEST_DIRECTORY",
                "directory_query": {"sort": "abs_move", "page": 1},
            },
            {"selection_state": "NO_RESEARCH", "selected_symbols": []},
        ]
    )
    service = MarketSelectionService(board=board, chief=chief, directory=directory)
    record = asyncio.run(service.maybe_select(now=datetime.now(UTC)))
    assert record.status == "NO_RESEARCH"
    assert record.exploration_rounds == 1
    assert len(record.directory_query_refs) == 2  # <=2 pages, hard cap
    pages = chief.contexts[1]["market_directory"]["pages"]
    assert len(pages) == 2
    assert all(page["page_size"] <= 25 for page in pages)
    assert all(page["read_only"] is True for page in pages)
    # the exploration result went to the SAME chief instance
    assert len(chief.contexts) == 2
    assert chief.contexts[1]["phase"] == "DIRECTORY_EXPLORATION"


def test_directory_exploration_is_terminal_no_third_phase():
    board = _board_with_rows()
    directory = MarketDirectory(board=board, page_size=20, max_pages=2)
    chief = PhasedChief(
        [
            {"selection_state": "REQUEST_DIRECTORY", "directory_query": {"page": 1}},
            {"selection_state": "REQUEST_DIRECTORY", "directory_query": {"page": 2}},
        ]
    )
    service = MarketSelectionService(board=board, chief=chief, directory=directory)
    record = asyncio.run(service.maybe_select(now=datetime.now(UTC)))
    assert record.status == "INVALID_OUTPUT"
    assert record.error_code == "NO_THIRD_EXPLORATION_PHASE"
    assert len(chief.contexts) == 2  # never a third model call


def test_directory_exploration_consumes_p4_budget_and_fails_closed():
    board = _board_with_rows()
    directory = MarketDirectory(board=board, page_size=20, max_pages=2)
    chief = PhasedChief(
        [
            {"selection_state": "REQUEST_DIRECTORY", "directory_query": {"page": 1}},
            {"selection_state": "NO_RESEARCH", "selected_symbols": []},
        ]
    )
    # P4 ceiling = 1 -> phase 1 consumes it, exploration must fail closed
    budget = GlobalLLMBudget(
        BudgetConfig(
            window_seconds=60,
            max_calls_per_window=4,
            reserved_fraction_for_higher={P4_MARKET_SELECTION: 0.75},
        )
    )
    service = MarketSelectionService(
        board=board, chief=chief, directory=directory, budget=budget
    )
    record = asyncio.run(service.maybe_select(now=datetime.now(UTC)))
    assert record.status == "DEFERRED"
    assert record.error_code == "SKIPPED_BUDGET"
    assert len(chief.contexts) == 1  # only phase 1 ran
    assert budget.snapshot()["skipped_by_priority"][P4_MARKET_SELECTION] == 1


def test_directory_query_cannot_smuggle_authority_fields():
    for query in (
        {"sort": "abs_move", "direction": "LONG"},
        {"sort": "abs_move", "quantity": 1},
        {"sort": "abs_move", "url": "https://evil"},
        {"sort": "abs_move", "stop_loss": 1},
    ):
        parsed = parse_selection_payload(
            {"selection_state": "REQUEST_DIRECTORY", "directory_query": query},
            selection_id="s",
            scan_id="sc",
        )
        assert isinstance(parsed, str)
        assert parsed.startswith(("AUTHORITY_LEAK", "INVALID_DIRECTORY_QUERY"))


def test_pool_native_selection_has_no_directory_provenance():
    board = _board_with_rows()
    directory = MarketDirectory(board=board, page_size=20, max_pages=2)
    chief = PhasedChief(
        [
            {"selection_state": "SELECT", "selected_symbols": [{"symbol": "S0USDT"}]},
        ]
    )
    service = MarketSelectionService(board=board, chief=chief, directory=directory)
    record = asyncio.run(service.maybe_select(now=datetime.now(UTC)))
    entry = record.selected_symbols[0]
    assert entry["from_initial_pool"] is True
    assert entry["discovered_via_directory"] is False
    assert "directory_page_ref" not in entry
    assert record.exploration_rounds == 0

# ------------------------------------------------- OI missing vs zero (client)
def _adapter_with_payload(payload):
    """OKXAdapter whose public request returns one fixed OI row."""
    from crypto_trader.exchange.okx import OKXAdapter

    client = OKXAdapter(base_url="https://www.okx.com", demo=False)

    async def fake_public_request(method, path, params=None):
        return {"code": "0", "data": [payload]}

    client._public_request = fake_public_request  # type: ignore[assignment]
    return client


def test_provider_oi_zero_stays_a_valid_zero():
    client = _adapter_with_payload({"instId": "BTC-USDT-SWAP", "oi": "0", "oiCcy": "0",
                                    "oiUsd": "0", "ts": client_ts()})
    payload = asyncio.run(client.get_open_interest("BTC-USDT-SWAP"))
    assert payload["open_interest"] == "0"

    board, _ = _scan(OiClient(oi_value="0"))
    row = board.current_snapshot().observable_rows[0]
    assert row["open_interest"] == 0.0
    assert row["oi_quality"] == VALID


def test_provider_missing_oi_is_not_a_fake_zero():
    """A row without ``oi`` must NOT become the string "0" / a VALID zero."""
    client = _adapter_with_payload({"instId": "BTC-USDT-SWAP", "ts": client_ts()})
    payload = asyncio.run(client.get_open_interest("BTC-USDT-SWAP"))
    assert payload["open_interest"] is None
    assert payload["open_interest_ccy"] is None
    assert payload["open_interest"] != "0"


def test_fallback_missing_oi_maps_to_missing_not_valid_zero():
    client = OiClient(fallback_enabled=False, oi_rows=[])
    # broad response succeeds with no rows; the bounded fallback yields no value
    client.oi_rows = []
    board, _ = _scan(client)
    rows = {row["symbol"]: row for row in board.current_snapshot().observable_rows}
    for row in rows.values():
        assert row["open_interest"] is None
        assert row["oi_quality"] != VALID
        assert row["oi_quality"] in (NOT_SAMPLED, MISSING, REQUEST_FAILED)


def test_malformed_and_negative_oi_never_become_valid_zero():
    client = OiClient(
        fallback_enabled=False,
        oi_rows=[
            {"instId": _inst("AAAUSDT"), "oi": "abc", "ts": client_ts()},
            {"instId": _inst("BBBUSDT"), "oi": "-5", "ts": client_ts()},
            {"instId": _inst("CCCUSDT"), "oi": "NaN", "ts": client_ts()},
            {"instId": _inst("DDDUSDT"), "oi": "Infinity", "ts": client_ts()},
        ],
    )
    board, _ = _scan(client)
    rows = {row["symbol"]: row for row in board.current_snapshot().observable_rows}
    for symbol in ("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"):
        assert rows[symbol]["open_interest"] is None
        assert rows[symbol]["oi_quality"] != VALID


# ------------------------------------------------------- OI source provenance
def test_oi_time_series_source_is_the_real_endpoint():
    from crypto_trader.market_data.opportunity import oi as oi_module
    from crypto_trader.market_data.opportunity.oi import OiSample, OiTimeSeries

    assert oi_module.OiSample.__dataclass_fields__["source"].default == (
        "OKX /api/v5/public/open-interest"
    )

    series = OiTimeSeries()
    sample = OiSample(symbol="BTCUSDT", open_interest=1.0, observed_at=datetime.now(UTC))
    series.record(sample)
    exported = series.export_state()["BTCUSDT"][0]
    assert exported["source"] == "OKX /api/v5/public/open-interest"
    assert "open-interests" not in exported["source"]

    # import path must default to the real endpoint too
    restored = OiTimeSeries()
    restored.import_state({"BTCUSDT": [{"symbol": "BTCUSDT", "open_interest": 1.0,
                                        "observed_at": datetime.now(UTC).isoformat()}]})
    assert "open-interests" not in restored.export_state()["BTCUSDT"][0]["source"]


def test_service_oi_source_constant_and_snapshot_provenance_are_consistent():
    from crypto_trader.market_data.opportunity.service import OI_SOURCE

    assert OI_SOURCE == "OKX /api/v5/public/open-interest"
    board, _ = _scan(OiClient())
    snapshot = board.current_snapshot()
    for row in snapshot.observable_rows:
        assert row["oi_quality"] == VALID
    assert snapshot.data_quality_summary["open_interest_collection"]["collected"] == len(SYMBOLS)


# --------------------------------------------------- directory page semantics
def test_directory_requested_page_is_factual():
    board = _board_with_rows(100)
    directory = MarketDirectory(board=board, page_size=20, max_pages=2)
    first = directory.query_pages({"page": 1}, scan_id="scan-explore")
    second = directory.query_pages({"page": 2}, scan_id="scan-explore")
    pages_1, refs_1, map_1 = first
    pages_2, refs_2, map_2 = second
    assert [page["page"] for page in pages_1] == [1, 2]
    # asking for page 2 starts there and does not silently re-serve page 1
    assert [page["page"] for page in pages_2] == [2]
    assert all("page=2" in ref for ref in refs_2)
    rows_page_1 = {row["symbol"] for row in pages_1[0]["rows"]}
    rows_page_2 = {row["symbol"] for row in pages_2[0]["rows"]}
    assert rows_page_1.isdisjoint(rows_page_2)  # genuinely different page windows
    assert all(page_number == 1 for page_number in map_1.values() if page_number == 1)
    # hard caps are enforced regardless of the requested page
    assert len(pages_1) <= 2 and len(pages_2) <= 2
    assert all(page["page_size"] <= 25 for page in pages_1 + pages_2)
