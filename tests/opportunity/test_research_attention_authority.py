"""Research-attention authority tests against the CANONICAL production path.

These tests call ``LiveLLMDecisionStrategy.desired_symbol()`` — the method the
runtime actually uses to decide which symbol receives autonomous NEW research.

Core rule under test: when ChiefTrader MarketSelection is enabled
(``selection_service`` wired), it is the ONLY authority over new autonomous
research attention. NO_RESEARCH, selection failure, stale selection, an
exhausted selection queue and budget deferral ALL return ``None`` — they must
never fall back to the programmatic OpportunityBoard agenda.

Every "must not fall back" case deliberately publishes a board candidate (and a
rotation symbol) so a hidden fallback would return a value and fail the test.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from crypto_trader.llm_chief.runtime_strategy import LiveLLMDecisionStrategy
from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.factors import FactorObservation
from crypto_trader.market_data.opportunity.scanner import FactorCandidate
from crypto_trader.market_data.opportunity.selection import MarketSelectionRecord
from crypto_trader.market_data.opportunity.snapshot import (
    STATUS_COMPLETE,
    MarketObservationSnapshot,
)


# Snapshot freshness is judged against REAL wall time (OpportunityBoard uses
# time.time() internally), so a module-level constant captured at import would
# drift by the length of the whole suite and make expiry assertions
# non-deterministic. Read the clock at CALL time instead.
def NOW() -> datetime:
    return datetime.now(UTC)



def _candidate(symbol: str, strength: float = 0.9) -> FactorCandidate:
    return FactorCandidate(
        symbol=symbol,
        triggered=[
            FactorObservation(
                symbol=symbol,
                factor="MOMENTUM_EXPANSION",
                status="TRIGGERED",
                strength=strength,
                observed_at=NOW().isoformat(),
            )
        ],
        priority=strength,
        scan_id="scan-1",
        created_at=NOW(),
        expires_at=NOW() + timedelta(seconds=180),
    )


def _board(*, scan_id: str = "scan-1", now: datetime | None = None) -> OpportunityBoard:
    now = now or NOW()
    """A board that ALWAYS has a programmatic candidate + rotation symbol."""
    board = OpportunityBoard()
    board.publish_snapshot(
        MarketObservationSnapshot(
            scan_id=scan_id,
            started_at=now,
            completed_at=now,
            expires_at=now + timedelta(seconds=180),
            status=STATUS_COMPLETE,
            discovered_count=10,
            observable_count=10,
            analysis_attempted_count=2,
            execution_supported_count=10,
            factor_candidates=(_candidate("PROGRAMUSDT"),),
            rotation_symbols=("ROTATIONUSDT",),
        )
    )
    return board


class FakeSelectionService:
    """Minimal stand-in exposing ``last_record`` like the real service."""

    def __init__(self, record: MarketSelectionRecord | None) -> None:
        self.last_record = record


def _record(
    *,
    status: str,
    scan_id: str = "scan-1",
    symbols: tuple[str, ...] = (),
    selection_state: str = "",
) -> MarketSelectionRecord:
    return MarketSelectionRecord(
        selection_id="mkt_sel_test",
        scan_id=scan_id,
        status=status,
        selection_state=selection_state or ("NO_RESEARCH" if not symbols else "SELECT"),
        selected_symbols=[{"symbol": s} for s in symbols],
        requested_at=NOW(),
        completed_at=NOW(),
    )


def _strategy(board: OpportunityBoard, service=None) -> LiveLLMDecisionStrategy:
    return LiveLLMDecisionStrategy(
        evidence_engine=type("E", (), {"symbol": "BTCUSDT"})(),
        chief=None,
        planner=None,
        decisions=None,
        audit=None,
        opportunity_board=board,
        selection_service=service,
        attempt_clock=lambda: NOW(),
    )


def test_programmatic_agenda_available_when_selection_disabled():
    """Legacy mode: selection_service is None -> board agenda still works."""
    board = _board()
    strategy = _strategy(board, service=None)
    assert strategy.desired_symbol() == "PROGRAMUSDT"


def test_selected_symbol_is_returned():
    board = _board()
    service = FakeSelectionService(_record(status="SUCCESS", symbols=("ETHUSDT",)))
    strategy = _strategy(board, service)
    assert strategy.desired_symbol() == "ETHUSDT"


def test_only_selected_symbols_are_consumed_then_none():
    """SUCCESS with 3 symbols: exactly those are consumed, then None."""
    board = _board()
    service = FakeSelectionService(
        _record(status="SUCCESS", symbols=("AAAUSDT", "BBBUSDT", "CCCUSDT"))
    )
    strategy = _strategy(board, service)
    consumed = [strategy.desired_symbol() for _ in range(3)]
    assert consumed == ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    # queue exhausted: the board candidate/rotation MUST NOT be consumed
    assert board.next_agenda_symbol() == "PROGRAMUSDT"  # board fallback exists...
    assert strategy.desired_symbol() is None  # ...but the runtime never uses it


def test_queue_exhausted_does_not_fall_back_to_board():
    board = _board()
    service = FakeSelectionService(_record(status="SUCCESS", symbols=("AAAUSDT",)))
    strategy = _strategy(board, service)
    assert strategy.desired_symbol() == "AAAUSDT"
    for _ in range(3):
        assert strategy.desired_symbol() is None
        assert board.next_agenda_symbol() is not None  # hidden fallback would fail


def test_no_research_does_not_fall_back_to_board():
    board = _board()
    service = FakeSelectionService(
        _record(status="NO_RESEARCH", symbols=(), selection_state="NO_RESEARCH")
    )
    strategy = _strategy(board, service)
    for _ in range(3):
        assert strategy.desired_symbol() is None
        assert board.next_agenda_symbol() is not None


@pytest.mark.parametrize("status", ["LLM_UNAVAILABLE", "TIMEOUT", "FAILED"])
def test_selection_failure_does_not_fall_back_to_board(status):
    board = _board()
    service = FakeSelectionService(_record(status=status, symbols=()))
    strategy = _strategy(board, service)
    assert strategy.desired_symbol() is None
    assert board.next_agenda_symbol() is not None


@pytest.mark.parametrize("status", ["SKIPPED_BUDGET", "DEFERRED"])
def test_selection_budget_deferral_does_not_fall_back_to_board(status):
    board = _board()
    service = FakeSelectionService(_record(status=status, symbols=()))
    strategy = _strategy(board, service)
    assert strategy.desired_symbol() is None
    assert board.next_agenda_symbol() is not None


def test_expired_selection_does_not_fall_back_to_board():
    board = _board(now=NOW() - timedelta(seconds=600))
    service = FakeSelectionService(_record(status="SUCCESS", symbols=("AAAUSDT",)))
    strategy = _strategy(board, service)
    assert strategy.desired_symbol() is None
    assert board.next_agenda_symbol() is not None


def test_scan_id_mismatch_does_not_fall_back_to_board():
    """A selection from an older scan must never drive research."""
    board = _board(scan_id="scan-2")
    service = FakeSelectionService(
        _record(status="SUCCESS", scan_id="scan-1", symbols=("AAAUSDT",))
    )
    strategy = _strategy(board, service)
    assert strategy.desired_symbol() is None
    assert board.next_agenda_symbol() is not None


def test_no_selection_record_at_all_stays_none():
    board = _board()
    service = FakeSelectionService(None)
    strategy = _strategy(board, service)
    assert strategy.desired_symbol() is None
    assert board.next_agenda_symbol() is not None
