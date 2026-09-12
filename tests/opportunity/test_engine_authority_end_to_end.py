"""END-TO-END research-attention authority tests through TradingEngine.tick().

These call the real production path:

    MarketSelection state
        -> LiveLLMDecisionStrategy.desired_symbol()
        -> TradingEngine.tick()
        -> strategy.on_market_data()

The defect being closed: ``desired_symbol() -> None`` previously still produced
``_strategy_context(None)``, which fell back to the strategy's default symbol and
ran an autonomous review anyway. Every blocked case below therefore has BOTH a
board candidate and a default strategy symbol available, so any hidden fallback
would be observable as an ``on_market_data`` invocation.

Position review is checked separately to prove NO_RESEARCH stops only NEW
autonomous research.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from crypto_trader.llm_chief.runtime_strategy import LiveLLMDecisionStrategy
from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.factors import FactorObservation
from crypto_trader.market_data.opportunity.scanner import FactorCandidate
from crypto_trader.market_data.opportunity.selection import MarketSelectionRecord
from crypto_trader.market_data.opportunity.snapshot import (
    STATUS_COMPLETE,
    MarketObservationSnapshot,
)
from crypto_trader.persistence.models import LLMDecisionORM, TradePlanORM
from tests.conftest import make_paper_engine


# Snapshot freshness is judged against REAL wall time (OpportunityBoard uses
# time.time() internally), so a module-level constant captured at import would
# drift by the length of the whole suite and make expiry assertions
# non-deterministic. Read the clock at CALL time instead.
def NOW() -> datetime:
    return datetime.now(UTC)

DEFAULT_SYMBOL = "BTCUSDT"
BOARD_CANDIDATE = "PROGRAMUSDT"


# --------------------------------------------------------------------- fixtures
def _candidate(symbol: str = BOARD_CANDIDATE) -> FactorCandidate:
    return FactorCandidate(
        symbol=symbol,
        triggered=[
            FactorObservation(
                symbol=symbol,
                factor="MOMENTUM_EXPANSION",
                status="TRIGGERED",
                strength=0.9,
                observed_at=NOW().isoformat(),
            )
        ],
        priority=0.9,
        scan_id="scan-1",
        created_at=NOW(),
        expires_at=NOW() + timedelta(seconds=180),
    )


def _board(*, scan_id: str = "scan-1", now: datetime | None = None) -> OpportunityBoard:
    now = now or NOW()
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
            factor_candidates=(_candidate(),),
            rotation_symbols=("ROTATIONUSDT",),
        )
    )
    return board


class CountingSelectionService:
    """Exposes ``last_record`` like the real service; records no LLM calls."""

    def __init__(self, record: MarketSelectionRecord | None) -> None:
        self.last_record = record


class CountingStrategy(LiveLLMDecisionStrategy):
    """Canonical strategy with call counting for the production tick path."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.invocations: list[str] = []

    async def on_market_data(self, ctx):
        self.invocations.append(ctx.symbol)
        return []


def _record(
    *,
    status: str,
    scan_id: str = "scan-1",
    symbols: tuple[str, ...] = (),
    selection_state: str = "",
) -> MarketSelectionRecord:
    return MarketSelectionRecord(
        selection_id=f"mkt_sel_{status}_{'_'.join(symbols) or 'none'}",
        scan_id=scan_id,
        status=status,
        selection_state=selection_state or ("NO_RESEARCH" if not symbols else "SELECT"),
        selected_symbols=[{"symbol": s} for s in symbols],
        requested_at=NOW(),
        completed_at=NOW(),
    )


def _install_context_spy(engine, strategy):
    """Record which symbol the engine asks a context for.

    The synthetic PAPER adapter has no market for arbitrary symbols, so the real
    ``_strategy_context`` would simply return None and mask the routing decision
    under test. The spy mirrors the engine's documented default behavior
    (``strategies[0].symbol or "BTCUSDT"`` when called with no symbol) while
    recording every requested symbol.
    """
    requested: list[str | None] = []

    async def spy(symbol=None):
        requested.append(symbol)
        resolved = symbol or (getattr(engine.strategies[0], "symbol", None) or DEFAULT_SYMBOL)
        return type("Ctx", (), {"symbol": resolved})()

    engine._strategy_context = spy  # type: ignore[assignment]
    return requested


def _build(database, record: MarketSelectionRecord | None, *, board=None):
    board = board if board is not None else _board()
    strategy = CountingStrategy(
        evidence_engine=type("E", (), {"symbol": DEFAULT_SYMBOL})(),
        chief=None,
        planner=None,
        decisions=None,
        audit=None,
        opportunity_board=board,
        selection_service=CountingSelectionService(record),
        attempt_clock=lambda: NOW(),
    )
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.strategies = [strategy]
    context_requests = _install_context_spy(engine, strategy)
    return engine, strategy, board, context_requests


async def _count_new_artifacts(database) -> tuple[int, int]:
    async with database.session_factory() as session:
        decisions = len((await session.scalars(select(LLMDecisionORM))).all())
        plans = len((await session.scalars(select(TradePlanORM))).all())
    return decisions, plans


# ------------------------------------------------------------------- the cases
async def test_blocked_selection_states_never_invoke_strategy(database):
    """Cases 1-3, 5: no default-symbol review for blocked selection states."""
    for case, record in (
        ("NO_RESEARCH", _record(status="NO_RESEARCH", selection_state="NO_RESEARCH")),
        ("LLM_UNAVAILABLE", _record(status="LLM_UNAVAILABLE")),
        ("TIMEOUT", _record(status="TIMEOUT")),
        ("FAILED", _record(status="FAILED")),
        ("SKIPPED_BUDGET", _record(status="SKIPPED_BUDGET")),
        ("DEFERRED", _record(status="DEFERRED")),
        ("NO_RECORD", None),
    ):
        engine, strategy, board, requests = _build(database, record)
        # both fallback targets exist and are available
        assert board.next_agenda_symbol() == BOARD_CANDIDATE
        assert strategy.symbol == DEFAULT_SYMBOL

        await engine.tick(include_position_reviews=False)

        assert strategy.invocations == [], f"{case} invoked on_market_data {strategy.invocations}"
        # and the engine never even asked for a context (no default substitute)
        assert requests == [], f"{case} requested context for {requests}"
        decisions, plans = await _count_new_artifacts(database)
        assert decisions == 0 and plans == 0


async def test_expired_and_mismatched_selections_never_invoke_strategy(database):
    """Case 5: expired snapshot and scan_id mismatch."""
    stale_board = _board(now=NOW() - timedelta(seconds=600))
    engine, strategy, _, requests = _build(
        database, _record(status="SUCCESS", symbols=("ETHUSDT",)), board=stale_board
    )
    await engine.tick(include_position_reviews=False)
    assert strategy.invocations == []
    assert requests == []

    mismatched_board = _board(scan_id="scan-2")
    engine, strategy, _, requests = _build(
        database,
        _record(status="SUCCESS", scan_id="scan-1", symbols=("ETHUSDT",)),
        board=mismatched_board,
    )
    await engine.tick(include_position_reviews=False)
    assert strategy.invocations == []
    assert requests == []


async def test_queue_exhaustion_does_not_review_board_candidate(database):
    """Case 4: one selected symbol is consumed once, then nothing else."""
    engine, strategy, board, requests = _build(
        database, _record(status="SUCCESS", symbols=("ETHUSDT",))
    )
    engine.position_review_interval_seconds = 999  # keep the tick focused

    await engine.tick(include_position_reviews=False)
    assert strategy.invocations == ["ETHUSDT"]
    assert requests == ["ETHUSDT"]

    # second tick: queue exhausted, board candidate still available
    assert board.next_agenda_symbol() == BOARD_CANDIDATE
    await engine.tick(include_position_reviews=False)
    assert strategy.invocations == ["ETHUSDT"]
    assert requests == ["ETHUSDT"]  # no second context request at all
    assert BOARD_CANDIDATE not in strategy.invocations
    assert DEFAULT_SYMBOL not in strategy.invocations


async def test_valid_selection_routes_the_exact_symbol(database):
    """Case 6: the selected symbol reaches the strategy unchanged."""
    engine, strategy, _, requests = _build(
        database, _record(status="SUCCESS", symbols=("ETHUSDT",))
    )
    await engine.tick(include_position_reviews=False)
    assert strategy.invocations == ["ETHUSDT"]
    assert requests == ["ETHUSDT"]


async def test_legacy_strategy_without_scheduler_still_runs(database):
    """Case 7: a strategy with no desired_symbol() keeps legacy behavior."""

    class LegacyStrategy:
        name = "legacy"
        symbol = DEFAULT_SYMBOL

        def __init__(self) -> None:
            self.invocations: list[str] = []

        async def on_market_data(self, ctx):
            self.invocations.append(ctx.symbol)
            return []

    strategy = LegacyStrategy()
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.strategies = [strategy]
    requests = _install_context_spy(engine, strategy)
    await engine.tick(include_position_reviews=False)
    assert strategy.invocations == [DEFAULT_SYMBOL]
    assert requests == [None]  # legacy path: no scheduled symbol


async def test_scheduler_failure_fails_closed_without_crashing(database):
    """Case D: desired_symbol() raising must not fall back to a default symbol."""

    class RaisingStrategy(CountingStrategy):
        def desired_symbol(self):
            raise RuntimeError("scheduler exploded")

    board = _board()
    strategy = RaisingStrategy(
        evidence_engine=type("E", (), {"symbol": DEFAULT_SYMBOL})(),
        chief=None,
        planner=None,
        decisions=None,
        audit=None,
        opportunity_board=board,
        selection_service=CountingSelectionService(_record(status="SUCCESS", symbols=("ETHUSDT",))),
        attempt_clock=lambda: NOW(),
    )
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.strategies = [strategy]
    requests = _install_context_spy(engine, strategy)

    # must not raise, must not run the strategy with a default symbol
    await engine.tick(include_position_reviews=False)
    assert strategy.invocations == []
    assert requests == []
    assert engine.health.snapshot()["components"]["strategy:live_llm"]["ok"] is False


async def test_no_research_does_not_stop_position_review(database):
    """Case: NO_RESEARCH stops only NEW research, never position safety."""
    engine, strategy, board, requests = _build(
        database, _record(status="NO_RESEARCH", selection_state="NO_RESEARCH")
    )
    reviewed: list[str] = []

    class PositionManager:
        async def review(self, context, position):
            reviewed.append(position.symbol)
            return None

    engine.position_manager = PositionManager()

    async def positions():
        return {
            "BTCUSDT": type(
                "P",
                (),
                {
                    "symbol": "BTCUSDT",
                    "quantity": 1,
                    "avg_entry_price": None,
                    "contract_size": 1,
                    "contract_multiplier": 1,
                },
            )()
        }

    async def strategy_context(symbol=None):
        return object()

    engine.portfolio.get_positions = positions  # type: ignore[assignment]
    engine._strategy_context = strategy_context  # type: ignore[assignment]

    await engine.tick(include_position_reviews=True)

    assert strategy.invocations == []          # no NEW autonomous research
    assert reviewed == ["BTCUSDT"]             # position review still ran
