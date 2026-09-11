"""Gate 3 tests: ChiefTrader ACTIVE market selection (research attention only)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from crypto_trader.llm_chief.budget import (
    P0_POSITION_SAFETY,
    P4_MARKET_SELECTION,
    BudgetConfig,
    GlobalLLMBudget,
)
from crypto_trader.llm_chief.engine import ChiefTraderEngine, MarketSelectionResult
from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.directory import (
    MAX_DIRECTORY_PAGES_PER_ROUND,
    MarketDirectory,
)
from crypto_trader.market_data.opportunity.factors import FactorObservation
from crypto_trader.market_data.opportunity.scanner import (
    CANDIDATE_SOURCE_DEEPSEEK_SELECTION,
    FactorCandidate,
)
from crypto_trader.market_data.opportunity.selection import (
    MAX_SELECTED_SYMBOLS,
    ST_DEFERRED,
    ST_FAILED,
    ST_INVALID_OUTPUT,
    ST_LLM_UNAVAILABLE,
    ST_NO_RESEARCH,
    ST_SKIPPED_BUDGET,
    ST_STALE_SCAN,
    ST_SUCCESS,
    STATE_NO_RESEARCH,
    MarketSelectionService,
    parse_selection_payload,
)
from crypto_trader.market_data.opportunity.snapshot import (
    STATUS_COMPLETE,
    MarketObservationSnapshot,
)


# --------------------------------------------------------------------- helpers
def _snapshot(
    *,
    scan_id: str = "scan-1",
    now: datetime | None = None,
    candidates: tuple = (),
    rotation: tuple = (),
    rows: tuple = (),
    age_seconds: float = 1.0,
    status: str = STATUS_COMPLETE,
) -> MarketObservationSnapshot:
    now = now or datetime.now(UTC)
    started = now - timedelta(seconds=age_seconds)
    return MarketObservationSnapshot(
        scan_id=scan_id,
        started_at=started,
        completed_at=started,
        expires_at=started + timedelta(seconds=180),
        status=status,
        discovered_count=len(rows),
        observable_count=len(rows),
        analysis_attempted_count=len(rows),
        analysis_success_count=len(rows),
        analysis_ready_count=len(rows),
        execution_supported_count=len(rows),
        factor_candidates=candidates,
        rotation_symbols=rotation,
        observable_rows=rows,
    )


def _row(symbol: str, *, turnover: float = 5_000_000.0, move: float = 0.5) -> dict:
    return {
        "symbol": symbol,
        "last": 100.0,
        "price_change_24h_pct": move,
        "vol_usd_24h": turnover,
        "funding_rate": 0.0001,
        "funding_quality": "VALID",
        "open_interest": 1000.0,
        "oi_quality": "VALID",
        "ticker_quality": "VALID",
        "execution_supported": True,
        "eligible": True,
        "excluded_reasons": (),
    }


def _candidate(symbol: str, *, strength: float = 0.9, scan_id: str = "scan-1") -> FactorCandidate:
    now = datetime.now(UTC)
    return FactorCandidate(
        symbol=symbol,
        triggered=[
            FactorObservation(
                symbol=symbol,
                factor="MOMENTUM_EXPANSION",
                status="TRIGGERED",
                strength=strength,
                observed_at=now.isoformat(),
            )
        ],
        priority=strength,
        scan_id=scan_id,
        created_at=now,
        expires_at=now + timedelta(seconds=180),
    )


class FakeSelectingChief:
    """Stand-in for the SAME canonical ChiefTrader selection phase."""

    def __init__(self, payload=None, *, error: str | None = None, raise_exc=None) -> None:
        self.payload = payload
        self.error = error
        self.raise_exc = raise_exc
        self.calls = 0
        self.last_context: dict | None = None

    async def select_markets(
        self, context, *, timeout_seconds, selection_id, scan_id, known_symbols=None
    ):
        self.calls += 1
        self.last_context = context
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.error is not None:
            return MarketSelectionResult(
                ok=False,
                status=ST_LLM_UNAVAILABLE,
                error_code=self.error,
                provider="deepseek",
                model="deepseek-chat",
            )
        parsed = parse_selection_payload(
            self.payload, selection_id=selection_id, scan_id=scan_id
        )
        if isinstance(parsed, str):
            return MarketSelectionResult(
                ok=False, status=ST_INVALID_OUTPUT, error_code=parsed, provider="deepseek"
            )
        return MarketSelectionResult(
            ok=True,
            status=ST_SUCCESS,
            output=parsed,
            provider="deepseek",
            model="deepseek-chat",
            latency_ms=42,
            input_tokens=100,
            output_tokens=20,
        )


def _service(board, chief, **kwargs) -> MarketSelectionService:
    kwargs.setdefault("cooldown_seconds", 300.0)
    return MarketSelectionService(board=board, chief=chief, **kwargs)


def _select(payload, *, board, **kwargs):
    chief = FakeSelectingChief(payload)
    service = _service(board, chief, **kwargs)
    record = asyncio.run(service.maybe_select(now=datetime.now(UTC)))
    return service, chief, record


# ------------------------------------------------------------------ selection
def test_chief_can_select_a_factor_candidate():
    board = OpportunityBoard()
    board.publish_snapshot(
        _snapshot(
            candidates=(_candidate("BTCUSDT"),),
            rows=(_row("BTCUSDT"), _row("ETHUSDT")),
        )
    )
    service, chief, record = _select(
        {
            "selection_state": "SELECTED",
            "selected_symbols": [{"symbol": "BTCUSDT", "brief_reason": "strong momentum"}],
        },
        board=board,
    )
    assert record.status == ST_SUCCESS
    assert record.selection_state == "SELECTED"
    assert record.selected_symbol_names == ["BTCUSDT"]
    assert record.scan_id == "scan-1"
    assert chief.calls == 1
    reasons = record.selected_symbols[0]["pool_reasons"]
    assert "factor candidate" in reasons
    assert record.selected_symbols[0]["selection_source"] == CANDIDATE_SOURCE_DEEPSEEK_SELECTION
    # per-symbol fairness clock advanced for LLM research exposure
    assert board.coverage.as_dict("BTCUSDT")["last_llm_research_at"] is not None


def test_chief_can_select_a_non_factor_rotation_symbol():
    board = OpportunityBoard()
    board.publish_snapshot(
        _snapshot(
            rotation=("ROTUSDT",),
            rows=(_row("BTCUSDT", turnover=9_000_000.0), _row("ROTUSDT", turnover=200.0)),
        )
    )
    _, _, record = _select(
        {"selection_state": "SELECTED", "selected_symbols": [{"symbol": "ROTUSDT"}]},
        board=board,
    )
    assert record.status == ST_SUCCESS
    assert "fair rotation" in record.selected_symbols[0]["pool_reasons"]
    assert board.market_sets.as_dict()["research_selected_count"] == 1
    assert board.coverage.as_dict("ROTUSDT")["last_llm_research_at"] is not None


def test_chief_can_select_an_active_anomaly_symbol():
    board = OpportunityBoard()
    board.publish_snapshot(
        _snapshot(
            rows=(
                _row("BIGMOVEUSDT", move=25.0),
                _row("QUIETUSDT", move=0.1, turnover=1_000.0),
            )
        )
    )
    _, _, record = _select(
        {"selection_state": "SELECTED", "selected_symbols": [{"symbol": "BIGMOVEUSDT"}]},
        board=board,
    )
    assert record.status == ST_SUCCESS
    assert "large absolute move" in record.selected_symbols[0]["pool_reasons"]
    assert board.market_sets.as_dict()["research_selected_count"] == 1


def test_chief_can_return_no_research():
    board = OpportunityBoard()
    board.publish_snapshot(_snapshot(rows=(_row("BTCUSDT"),)))
    service, chief, record = _select(
        {"selection_state": "NO_RESEARCH", "selected_symbols": []}, board=board
    )
    assert record.status == ST_NO_RESEARCH
    assert record.selection_state == STATE_NO_RESEARCH
    assert record.selected_symbols == []
    assert chief.calls == 1
    assert board.market_sets.as_dict()["research_pool_count"] >= 1


def test_chief_can_select_a_market_directory_symbol():
    board = OpportunityBoard()
    rows = tuple(_row(f"S{i}USDT", turnover=float(1000 - i)) for i in range(60))
    board.publish_snapshot(_snapshot(rows=rows))
    directory = MarketDirectory(board=board, page_size=20, max_pages=2)
    _, _, record = _select(
        {"selection_state": "SELECTED", "selected_symbols": [{"symbol": "S59USDT"}]},
        board=board,
        directory=directory,
    )
    # S59USDT falls outside the 30-symbol pool but is reachable via the directory
    assert record.status == ST_SUCCESS
    assert record.selected_symbols[0]["selection_source"] == CANDIDATE_SOURCE_DEEPSEEK_SELECTION
    assert len(record.directory_query_refs) == MAX_DIRECTORY_PAGES_PER_ROUND
    assert "market directory" in record.selected_symbols[0]["pool_reasons"]


def test_too_many_selected_symbols_is_rejected():
    board = OpportunityBoard()
    board.publish_snapshot(
        _snapshot(rows=(_row("AUSDT"), _row("BUSDT"), _row("CUSDT"), _row("DUSDT")))
    )
    service, _, record = _select(
        {
            "selection_state": "SELECTED",
            "selected_symbols": [{"symbol": s} for s in ("AUSDT", "BUSDT", "CUSDT", "DUSDT")],
        },
        board=board,
    )
    assert record.status == ST_INVALID_OUTPUT
    assert MAX_SELECTED_SYMBOLS == 3


def test_same_scan_id_cannot_generate_duplicate_autonomous_selection():
    board = OpportunityBoard()
    board.publish_snapshot(_snapshot(rows=(_row("BTCUSDT"),)))
    chief = FakeSelectingChief(
        {"selection_state": "SELECTED", "selected_symbols": [{"symbol": "BTCUSDT"}]}
    )
    service = _service(board, chief)
    first = asyncio.run(service.maybe_select(now=datetime.now(UTC)))
    second = asyncio.run(service.maybe_select(now=datetime.now(UTC)))
    assert first.status == ST_SUCCESS
    assert second.selection_id == first.selection_id
    assert chief.calls == 1  # the LLM was not called twice for the same scan


def test_stale_scan_is_rejected():
    board = OpportunityBoard()
    board.publish_snapshot(_snapshot(rows=(_row("BTCUSDT"),), age_seconds=400))
    chief = FakeSelectingChief({"selection_state": "NO_RESEARCH", "selected_symbols": []})
    service = _service(board, chief)
    record = asyncio.run(service.maybe_select(now=datetime.now(UTC)))
    assert record.status == ST_STALE_SCAN
    assert record.error_code == "SNAPSHOT_EXPIRED"
    assert chief.calls == 0


def test_selection_output_with_trading_authority_is_rejected():
    for leak in (
        {
            "selection_state": "SELECTED",
            "selected_symbols": [{"symbol": "BTCUSDT", "action": "LONG"}],
        },
        {
            "selection_state": "SELECTED",
            "selected_symbols": [{"symbol": "BTCUSDT", "quantity": 1}],
        },
        {
            "selection_state": "SELECTED",
            "selected_symbols": [{"symbol": "BTCUSDT", "stop_loss": 1}],
        },
        {
            "selection_state": "SELECTED",
            "selected_symbols": [{"symbol": "BTCUSDT", "leverage": 3}],
        },
        {
            "selection_state": "SELECTED",
            "selected_symbols": [{"symbol": "BTCUSDT"}],
            "direction": "SHORT",
        },
    ):
        parsed = parse_selection_payload(leak, selection_id="s", scan_id="sc")
        assert isinstance(parsed, str)
        assert parsed.startswith("AUTHORITY_LEAK")

    board = OpportunityBoard()
    board.publish_snapshot(_snapshot(rows=(_row("BTCUSDT"),)))
    _, _, record = _select(
        {
            "selection_state": "SELECTED",
            "selected_symbols": [{"symbol": "BTCUSDT", "side": "SHORT"}],
        },
        board=board,
    )
    assert record.status == ST_INVALID_OUTPUT
    assert record.error_code.startswith("AUTHORITY_LEAK")


def test_selection_cooldown_defers_without_calling_the_model():
    board = OpportunityBoard()
    board.publish_snapshot(_snapshot(rows=(_row("BTCUSDT"),)))
    chief = FakeSelectingChief({"selection_state": "NO_RESEARCH", "selected_symbols": []})
    service = _service(board, chief, cooldown_seconds=300.0)
    now = datetime.now(UTC)
    first = asyncio.run(service.maybe_select(now=now))
    assert first.status == ST_NO_RESEARCH
    board.publish_snapshot(
        _snapshot(scan_id="scan-2", rows=(_row("BTCUSDT"),))
    )
    cooldown_record = asyncio.run(service.maybe_select(now=now + timedelta(seconds=10)))
    assert cooldown_record.status == ST_DEFERRED
    assert cooldown_record.error_code == "SELECTION_COOLDOWN_ACTIVE"
    assert chief.calls == 1
    later = now + timedelta(seconds=301)
    # a fresh immutable snapshot is required for the post-cooldown round
    board.publish_snapshot(_snapshot(scan_id="scan-3", rows=(_row("BTCUSDT"),), now=later))
    after = asyncio.run(service.maybe_select(now=later))
    assert after.status == ST_NO_RESEARCH
    assert chief.calls == 2


def test_llm_unavailable_pauses_selection_and_observation_continues():
    board = OpportunityBoard()
    board.publish_snapshot(_snapshot(rows=(_row("BTCUSDT"),)))
    chief = FakeSelectingChief(error="LLM_TIMEOUT")
    service = _service(board, chief)
    record = asyncio.run(service.maybe_select(now=datetime.now(UTC)))
    assert record.status == ST_LLM_UNAVAILABLE
    assert record.error_code == "LLM_TIMEOUT"
    # observation state is untouched: the snapshot is still current
    assert board.current_snapshot().scan_id == "scan-1"
    assert board.current_snapshot().status == STATUS_COMPLETE


def test_empty_research_pool_is_an_error_not_no_research():
    board = OpportunityBoard()
    board.publish_snapshot(_snapshot(rows=()))
    chief = FakeSelectingChief({"selection_state": "NO_RESEARCH", "selected_symbols": []})
    service = _service(board, chief)
    record = asyncio.run(service.maybe_select(now=datetime.now(UTC)))
    assert record.status == ST_FAILED
    assert record.error_code == "EMPTY_RESEARCH_POOL"
    assert chief.calls == 0


def test_budget_exhaustion_skips_market_selection_without_engine_failure():
    board = OpportunityBoard()
    board.publish_snapshot(_snapshot(rows=(_row("BTCUSDT"),)))
    # a full reservation for higher priorities means market selection may never
    # spend in this window: it must skip explicitly, not fail the engine
    budget = GlobalLLMBudget(
        BudgetConfig(
            window_seconds=3600,
            max_calls_per_window=2,
            reserved_fraction_for_higher={P0_POSITION_SAFETY: 0.0, P4_MARKET_SELECTION: 1.0},
        )
    )
    chief = FakeSelectingChief({"selection_state": "NO_RESEARCH", "selected_symbols": []})
    service = _service(board, chief, budget=budget)
    record = asyncio.run(service.maybe_select(now=datetime.now(UTC)))
    assert record.status == ST_SKIPPED_BUDGET
    assert record.error_code == "LLM_BUDGET_RESERVED_FOR_HIGHER_PRIORITY"
    assert chief.calls == 0
    assert budget.snapshot()["skipped_by_priority"][P4_MARKET_SELECTION] == 1


def test_selection_token_and_latency_are_recorded_when_available():
    board = OpportunityBoard()
    board.publish_snapshot(_snapshot(rows=(_row("BTCUSDT"),)))
    _, _, record = _select(
        {"selection_state": "SELECTED", "selected_symbols": [{"symbol": "BTCUSDT"}]},
        board=board,
    )
    assert record.provider == "deepseek"
    assert record.model == "deepseek-chat"
    assert record.latency_ms == 42
    assert record.input_tokens == 100
    assert record.output_tokens == 20


def test_selection_context_is_bounded_and_authority_explicit():
    board = OpportunityBoard()
    rows = tuple(_row(f"S{i}USDT") for i in range(80))
    board.publish_snapshot(_snapshot(rows=rows))
    directory = MarketDirectory(board=board, page_size=20, max_pages=2)
    chief = FakeSelectingChief({"selection_state": "NO_RESEARCH", "selected_symbols": []})
    service = _service(board, chief, directory=directory)
    asyncio.run(service.maybe_select(now=datetime.now(UTC)))
    context = chief.last_context
    assert context["scan_id"] == "scan-1"
    assert context["snapshot_age_seconds"] >= 0
    assert len(context["candidate_pool"]) <= 30
    assert context["market_directory"]["pages"][0]["page_size"] == 20
    assert len(context["market_directory"]["pages"]) == 2
    assert "no trade direction" in context["authority_note"]
    assert context["output_contract"]["maximum_selected_symbols"] == 3


def test_selection_persistence_round_trip(database):
    from crypto_trader.market_data.opportunity.selection_store import MarketSelectionStore

    board = OpportunityBoard()
    board.publish_snapshot(
        _snapshot(candidates=(_candidate("ETHUSDT"),), rows=(_row("ETHUSDT"),))
    )
    store = MarketSelectionStore(database.session_factory)
    chief = FakeSelectingChief(
        {"selection_state": "SELECTED", "selected_symbols": [{"symbol": "ETHUSDT"}]}
    )
    service = _service(board, chief, store=store)
    record = asyncio.run(service.maybe_select(now=datetime.now(UTC)))
    assert record.status == ST_SUCCESS

    loaded = asyncio.run(store.load_for_scan("scan-1"))
    assert loaded is not None
    assert loaded.selection_id == record.selection_id
    assert loaded.scan_id == "scan-1"
    assert loaded.selected_symbol_names == ["ETHUSDT"]
    assert loaded.provider == "deepseek"
    latest = asyncio.run(store.load_latest())
    assert latest.selection_id == record.selection_id


def test_store_rehydrates_duplicate_guard_after_restart(database):
    from crypto_trader.market_data.opportunity.selection_store import MarketSelectionStore

    board = OpportunityBoard()
    board.publish_snapshot(_snapshot(rows=(_row("BTCUSDT"),)))
    store = MarketSelectionStore(database.session_factory)
    chief = FakeSelectingChief({"selection_state": "NO_RESEARCH", "selected_symbols": []})
    asyncio.run(_service(board, chief, store=store).maybe_select(now=datetime.now(UTC)))

    fresh_store = MarketSelectionStore(database.session_factory)
    assert asyncio.run(fresh_store.restore_duplicate_guard()) == 1
    restarted_chief = FakeSelectingChief({"selection_state": "NO_RESEARCH", "selected_symbols": []})
    record = asyncio.run(
        _service(board, restarted_chief, store=fresh_store).maybe_select(now=datetime.now(UTC))
    )
    assert record.status == ST_NO_RESEARCH
    assert restarted_chief.calls == 0  # duplicate scan_id refused after restart


# ------------------------------------------------------------------- directory
def test_directory_is_paginated_bounded_and_read_only():
    board = OpportunityBoard()
    rows = tuple(_row(f"S{i}USDT", turnover=float(10_000 - i)) for i in range(100))
    board.publish_snapshot(_snapshot(rows=rows))
    directory = MarketDirectory(board=board, page_size=20, max_pages=2)
    page = directory.page(page=1)
    assert page["read_only"] is True
    assert len(page["rows"]) == 20
    assert page["page_count"] == 2
    assert page["total_rows"] == 100
    second = directory.page(page=2)
    assert len(second["rows"]) == 20
    assert second["rows"][0]["symbol"] != page["rows"][0]["symbol"]
    # hard caps cannot be raised by configuration
    forced = MarketDirectory(board=board, page_size=1000, max_pages=99)
    assert forced.page_size == 25
    assert forced.max_pages == 2
    assert "direction" not in str(page).lower() or "no" in str(page).lower()


def test_engine_select_markets_validates_and_fails_closed():
    """The canonical ChiefTrader phase parses strictly and fails closed."""
    engine = ChiefTraderEngine(provider=None)
    result = asyncio.run(
        engine.select_markets({}, selection_id="s", scan_id="sc")
    )
    assert result.ok is False
    assert result.status == ST_LLM_UNAVAILABLE
