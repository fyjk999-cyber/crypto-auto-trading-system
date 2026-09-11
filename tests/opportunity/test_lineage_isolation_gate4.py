"""Gate 4 tests: evidence lineage + runtime isolation + authority boundaries."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from crypto_trader.llm.tools.registry import DynamicEvidencePackage, LLMToolRegistry, ToolEvidence
from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.factors import (
    FactorObservation,
    validate_no_direction_semantics,
)
from crypto_trader.market_data.opportunity.scanner import FactorScanner
from crypto_trader.market_data.opportunity.selection import (
    MarketSelectionOutput,
    parse_selection_payload,
)
from crypto_trader.market_data.opportunity.snapshot import (
    STATUS_COMPLETE,
    MarketObservationSnapshot,
)
from tests.conftest import make_paper_engine


# ------------------------------------------------------------------- lineage
def test_selection_scan_id_matches_snapshot_and_carries_no_direction():
    board = OpportunityBoard()
    now = datetime.now(UTC)
    snapshot = MarketObservationSnapshot(
        scan_id="scan-lineage",
        started_at=now,
        completed_at=now,
        expires_at=now + timedelta(seconds=180),
        status=STATUS_COMPLETE,
        observable_rows=(
            {
                "symbol": "BTCUSDT",
                "vol_usd_24h": 1e7,
                "funding_quality": "VALID",
                "ticker_quality": "VALID",
                "execution_supported": True,
            },
        ),
    )
    board.publish_snapshot(snapshot)
    output = parse_selection_payload(
        {"selection_state": "SELECTED", "selected_symbols": [{"symbol": "BTCUSDT"}]},
        selection_id="sel-1",
        scan_id="scan-lineage",
    )
    assert isinstance(output, MarketSelectionOutput)
    assert output.scan_id == snapshot.scan_id
    dumped = output.model_dump()
    for forbidden in ("action", "direction", "quantity", "leverage", "stop_loss", "order_type"):
        assert forbidden not in dumped
        assert forbidden not in dumped["selected_symbols"][0]


def test_tool_evidence_for_wrong_symbol_is_rejected_fail_closed():
    """A cached BTC calculation must never be presented as ETH evidence."""
    registry = LLMToolRegistry()

    async def btc_tool(symbol, context):
        return ToolEvidence(
            tool_name="cached_btc",
            symbol="BTCUSDT",  # wrong symbol for an ETH request
            timestamp=datetime.now(UTC),
            features={"momentum": 1.0},
            supporting_evidence=[],
            contrary_evidence=[],
            confidence_of_measurement=0.9,
            data_quality="VALID",
            source_refs=["market_history:BTCUSDT"],
        )

    registry.register("cached_btc", btc_tool, description="cached", version="v1")
    package = asyncio.run(
        registry.build_package(
            ["cached_btc"], "ETHUSDT", {}, now=datetime.now(UTC), timeout_seconds=1.0
        )
    )
    item = package.items[0]
    assert item.symbol == "ETHUSDT"
    assert item.data_quality == "UNAVAILABLE"
    assert "wrong symbol evidence rejected" in item.contrary_evidence
    assert item.finding == {}


def test_tool_timeout_is_unavailable_not_synthetic():
    registry = LLMToolRegistry()

    async def slow_tool(symbol, context):
        await asyncio.sleep(5)
        return None

    registry.register("slow", slow_tool, description="slow", version="v1")
    package = asyncio.run(
        registry.build_package(["slow"], "BTCUSDT", {}, now=datetime.now(UTC), timeout_seconds=0.1)
    )
    item = package.items[0]
    assert item.symbol == "BTCUSDT"
    assert item.data_quality == "UNAVAILABLE"
    assert item.confidence_of_measurement == 0.0
    assert item.finding == {}
    assert any("timeout" in text for text in item.contrary_evidence)


def test_decision_references_evidence_package_and_selection_lineage(database):
    from crypto_trader.llm_chief.decision import ChiefTraderDecision
    from crypto_trader.llm_chief.decision_store import LLMDecisionStore

    store = LLMDecisionStore(database.session_factory)
    decision = ChiefTraderDecision(
        decision_id="llm-lineage",
        symbol="ETHUSDT",
        action="NO_TRADE",
        market_regime="RANGE",
        thesis="lineage",
        model_provider="deepseek",
        model="deepseek-chat",
    )
    asyncio.run(
        store.save(
            decision,
            run_id="run-1",
            prompt_version="v1",
            tool_refs=["market_history"],
            opportunity_lineage={
                "candidate_source": "DEEPSEEK_SELECTION",
                "triggered_factors": [],
                "factor_evidence_present": False,
                "nominated_reason": "selected",
                "scan_id": "scan-42",
                "selection_id": "sel-42",
            },
            evidence_package={"symbol": "ETHUSDT", "items": [], "selected_tools": []},
        )
    )
    loaded = asyncio.run(store.get("llm-lineage"))
    assert loaded.evidence_package is not None
    assert loaded.evidence_package["symbol"] == "ETHUSDT"
    assert loaded.opportunity_source == "DEEPSEEK_SELECTION"
    assert loaded.scan_id == "scan-42"
    assert loaded.selection_id == "sel-42"


def test_evidence_package_symbol_matches_research_target():
    package = DynamicEvidencePackage(
        symbol="ETHUSDT",
        selected_tools=["market_regime"],
        items=[],
        tool_versions={"market_regime": "v1"},
    )
    assert package.symbol == "ETHUSDT"
    assert package.contract_version == "tool-round-v1"
    assert package.schema_version == "evidence-package-v1"


# ------------------------------------------------------------------- authority
def test_factor_scanner_cannot_emit_executable_direction():
    scanner = FactorScanner(factors=())
    observations = [
        FactorObservation(
            symbol="BTCUSDT", factor="MOMENTUM_EXPANSION", status="TRIGGERED", strength=0.9
        )
    ]
    # the scanner has no direction vocabulary at all
    validate_no_direction_semantics(observations)
    candidate = scanner.admit("BTCUSDT", observations)
    dumped = str(candidate.as_dict())
    for forbidden in ("LONG", "SHORT", "BUY", "SELL"):
        assert forbidden not in dumped
    for forbidden in ("quantity", "leverage", "stop_loss", "order_type"):
        assert forbidden not in dumped


def test_market_selection_authority_leak_is_rejected_at_schema_boundary():
    payloads = [
        {
            "selection_state": "SELECTED",
            "selected_symbols": [{"symbol": "BTCUSDT", "direction": "LONG"}],
        },
        {
            "selection_state": "SELECTED",
            "selected_symbols": [{"symbol": "BTCUSDT"}],
            "order_type": "MARKET",
        },
        {
            "selection_state": "SELECTED",
            "selected_symbols": [{"symbol": "BTCUSDT", "position_size": 5}],
        },
    ]
    for payload in payloads:
        parsed = parse_selection_payload(payload, selection_id="s", scan_id="sc")
        assert isinstance(parsed, str)
        assert parsed.startswith("AUTHORITY_LEAK")


# -------------------------------------------------------------- runtime isolation
async def test_slow_opportunity_scan_does_not_block_position_review(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    reviewed = asyncio.Event()

    class SlowOpportunityService:
        async def run_forever(self):
            while True:
                await asyncio.sleep(3600)

    class PositionManager:
        async def review(self, context, position):
            reviewed.set()
            return None

    engine.opportunity_service = SlowOpportunityService()
    engine.position_manager = PositionManager()
    engine.position_review_interval_seconds = 0.05
    await engine.start("run-slow-scan-isolation")
    try:
        engine.portfolio.get_positions = _positions()  # type: ignore[assignment]
        engine._strategy_context = _strategy_context()  # type: ignore[assignment]
        await asyncio.wait_for(reviewed.wait(), timeout=5)
        assert {"opportunity-scanner", "llm-position-reviews"} <= {
            task.get_name() for task in engine._tasks
        }
    finally:
        await engine.stop()


async def test_slow_market_selection_llm_does_not_block_position_review(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    selection_started = asyncio.Event()
    reviewed = asyncio.Event()

    class SlowSelectionService:
        last_record = None
        store = None

        async def maybe_select(self, *, existing_positions):
            selection_started.set()
            await asyncio.sleep(3600)
            raise AssertionError("unreachable in this test")

    class PositionManager:
        async def review(self, context, position):
            reviewed.set()
            return None

    engine.market_selection_service = SlowSelectionService()
    engine.market_selection_interval_seconds = 1.0
    engine.position_manager = PositionManager()
    engine.position_review_interval_seconds = 0.05
    await engine.start("run-slow-selection-isolation")
    try:
        engine.portfolio.get_positions = _positions()  # type: ignore[assignment]
        engine._strategy_context = _strategy_context()  # type: ignore[assignment]
        await asyncio.wait_for(selection_started.wait(), timeout=5)
        await asyncio.wait_for(reviewed.wait(), timeout=5)
        names = {task.get_name() for task in engine._tasks}
        assert "market-selection" in names
    finally:
        await engine.stop()


async def test_slow_research_tool_does_not_block_position_review(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    reviewed = asyncio.Event()

    class SlowToolChief:
        async def decide(self, ctx, *, tool_context, now):
            await asyncio.sleep(3600)

    class PositionManager:
        async def review(self, context, position):
            reviewed.set()
            return None

    engine.position_manager = PositionManager()
    engine.position_review_interval_seconds = 0.05
    await engine.start("run-slow-tool-isolation")
    try:
        engine.portfolio.get_positions = _positions()  # type: ignore[assignment]
        engine._strategy_context = _strategy_context()  # type: ignore[assignment]
        await asyncio.wait_for(reviewed.wait(), timeout=5)
    finally:
        await engine.stop()

def _positions():
    async def positions():
        return {"BTCUSDT": type("P", (), {"symbol": "BTCUSDT", "quantity": 1})()}

    return positions


def _strategy_context():
    async def strategy_context(symbol=None):
        return object()

    return strategy_context

