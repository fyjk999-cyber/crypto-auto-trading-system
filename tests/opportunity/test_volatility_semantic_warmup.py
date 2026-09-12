"""D5 sizing data-gap tests: same-semantic live ticker warm-up (VOLATILITY).

Contract under test (unchanged by this fix):

    realized_volatility = std-dev of consecutive OKX ticker-snapshot returns
    producer            = okx_public_feed._update_realized_volatility
    consumer            = StrategyContext.realized_volatility -> sizing
    fail-closed         = realized_volatility unavailable -> no TradePlan

The warm-up only makes the EXISTING factual ticker observations available
earlier. It never mixes closed candles into a ticker return series, never
synthesises/duplicates/back-dates a price, and never picks a direction.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from crypto_trader.domain.money import D, DecimalError
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.runtime_strategy import LiveLLMDecisionStrategy
from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.factors import FactorObservation
from crypto_trader.market_data.opportunity.scanner import FactorCandidate
from crypto_trader.market_data.opportunity.selection import (
    ST_SUCCESS,
    WARMING_FEED_NOT_WIRED,
    MarketSelectionService,
)
from crypto_trader.market_data.opportunity.snapshot import (
    STATUS_COMPLETE,
    MarketObservationSnapshot,
)
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.sizing.service import LiveEntrySizingService
from crypto_trader.strategy.base import StrategyContext

TARGET = 3


# --------------------------------------------------------------- fake producer
class FakeTickerFeed:
    """Minimal factual-ticker analogue of ``OKXPublicFeed``.

    Reproduces the two properties the fix depends on:

    * ``refresh`` appends exactly ONE factual price per call, and
    * a call inside the feed's own ``min_refresh_interval`` is a cache hit
      that appends NOTHING (so the warm-up must not spam the provider).
    """

    def __init__(self, *, fail: bool = False, prices: list[str] | None = None) -> None:
        self.min_refresh_interval = timedelta(seconds=1.0)
        self.fail = fail
        self._prices = deque(prices or ["100", "101", "102", "103", "104", "105"], maxlen=64)
        self._index = 0
        self._price_history: dict[str, deque] = {}
        self.calls: list[tuple[str, datetime]] = []
        self.refresh_attempts = 0

    def _next_price(self) -> str:
        price = self._prices[self._index % len(self._prices)]
        self._index += 1
        return price

    async def refresh(self, symbol: str, *, now: datetime | None = None):
        self.refresh_attempts += 1
        moment = now or datetime.now(UTC)
        self.calls.append((symbol, moment))
        history = self._price_history.setdefault(symbol, deque(maxlen=61))
        last = self.calls[-2] if len(self.calls) > 1 else None
        same_symbol_last = next(
            (t for s, t in reversed(self.calls[:-1]) if s == symbol), None
        )
        del last
        if same_symbol_last is not None:
            if moment - same_symbol_last < self.min_refresh_interval:
                return None  # cache hit: no factual observation consumed
        if self.fail:
            raise RuntimeError("ticker provider unavailable")
        history.append(Decimal(self._next_price()))
        return None

    def observations(self, symbol: str) -> list[Decimal]:
        return list(self._price_history.get(symbol) or ())


def _returns(prices: list[Decimal]) -> list[Decimal]:
    return [
        current / previous - Decimal("1")
        for previous, current in zip(prices, prices[1:], strict=False)
        if previous > 0
    ]


# ------------------------------------------------------------------- fake chief
class FakeSelectingChief:
    """Stand-in for the SAME canonical ChiefTrader selection phase."""

    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols
        self.calls = 0

    async def select_markets(
        self, context, *, timeout_seconds, selection_id, scan_id, known_symbols=None
    ):
        from crypto_trader.llm_chief.engine import MarketSelectionResult
        from crypto_trader.market_data.opportunity.selection import parse_selection_payload

        self.calls += 1
        payload = {
            "selection_state": "SELECTED",
            "selected_symbols": [
                {"symbol": symbol, "brief_reason": "test selection"}
                for symbol in self.symbols
            ],
        }
        parsed = parse_selection_payload(payload, selection_id=selection_id, scan_id=scan_id)
        assert not isinstance(parsed, str)
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


def _candidate(symbol: str) -> FactorCandidate:
    now = datetime.now(UTC)
    return FactorCandidate(
        symbol=symbol,
        triggered=[
            FactorObservation(
                symbol=symbol,
                factor="MOMENTUM_EXPANSION",
                status="TRIGGERED",
                strength=0.9,
                observed_at=now.isoformat(),
            )
        ],
        priority=0.9,
        scan_id="scan-warmup",
        created_at=now,
        expires_at=now + timedelta(seconds=180),
    )


def _row(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "last": 100.0,
        "price_change_24h_pct": 0.5,
        "vol_usd_24h": 5_000_000.0,
        "funding_rate": 0.0001,
        "funding_quality": "VALID",
        "open_interest": 1000.0,
        "oi_quality": "VALID",
        "ticker_quality": "VALID",
        "execution_supported": True,
        "eligible": True,
        "excluded_reasons": (),
    }


def _snapshot(*, candidates=(), rows=(), now: datetime | None = None):
    now = now or datetime.now(UTC)
    started = now - timedelta(seconds=1)
    return MarketObservationSnapshot(
        scan_id="scan-warmup",
        started_at=started,
        completed_at=started,
        expires_at=started + timedelta(seconds=180),
        status=STATUS_COMPLETE,
        discovered_count=len(rows),
        observable_count=len(rows),
        analysis_attempted_count=len(rows),
        analysis_success_count=len(rows),
        analysis_ready_count=len(rows),
        execution_supported_count=len(rows),
        factor_candidates=tuple(candidates),
        rotation_symbols=tuple(row["symbol"] for row in rows),
        observable_rows=tuple(rows),
    )


def _select(feed, *, symbols=("SOPHUSDT",), rows=(), candidates=(), **kwargs):
    board = OpportunityBoard()
    board.publish_snapshot(
        _snapshot(
            candidates=candidates or tuple(_candidate(s) for s in symbols),
            rows=rows or tuple(_row(s) for s in symbols),
        )
    )
    chief = FakeSelectingChief(list(symbols))
    service = MarketSelectionService(
        board=board,
        chief=chief,
        cooldown_seconds=300.0,
        ticker_feed=feed,
        ticker_warmup_target_samples=TARGET,
        **kwargs,
    )
    record = asyncio.run(service.maybe_select(now=datetime.now(UTC)))
    return service, record


# =============================================================== Test A / E / G
def test_A_unwarmed_symbol_reports_warming_and_consumes_nothing():
    """A: new symbol + insufficient observations -> not READY (fail-closed upstream)."""
    feed = FakeTickerFeed()
    service = MarketSelectionService(
        board=OpportunityBoard(), chief=FakeSelectingChief([]), ticker_feed=feed
    )
    assert service.ticker_warmup_readiness("NEWUSDT") == "WARMING"
    assert feed.observations("NEWUSDT") == []


def test_E_no_feed_is_reported_and_never_raises():
    """E: missing feed -> explicit readiness reason, selection still safe."""
    service = MarketSelectionService(
        board=OpportunityBoard(), chief=FakeSelectingChief([]), ticker_feed=None
    )
    assert service.ticker_warmup_readiness("ANYUSDT") == WARMING_FEED_NOT_WIRED
    asyncio.run(service._warm_ticker_observations(["ANYUSDT"]))
    assert service.ticker_warmup_status == {}


def test_G_zero_and_nan_follow_the_existing_decimal_contract():
    """G/F: a real 0 return is legal; NaN/Inf are rejected at the boundary."""
    flat = _returns([Decimal("100"), Decimal("100")])
    assert flat == [Decimal("0")]


    for bad in ("NaN", "nan", "Infinity", "-inf"):
        with pytest.raises(DecimalError):
            D(bad)


# =============================================================== Test B / C / H
def test_B_selection_reaches_factual_ticker_warmup_threshold():
    """B: after selection the symbol carries enough factual observations."""
    feed = FakeTickerFeed()
    service, record = _select(feed)

    assert record.status == ST_SUCCESS
    assert len(feed.observations("SOPHUSDT")) >= TARGET
    assert service.ticker_warmup_readiness("SOPHUSDT") == "READY"
    assert service.ticker_warmup_status["SOPHUSDT"]["status"] == "READY"


def test_C_observations_are_chronological_and_no_price_is_duplicated():
    """C: order preserved; each appended price is a distinct factual sample."""
    feed = FakeTickerFeed(prices=["100", "101", "102", "103"])
    _select(feed)
    observed = feed.observations("SOPHUSDT")
    assert observed == [Decimal("100"), Decimal("101"), Decimal("102")]
    assert len(observed) == len(set(observed))


def test_H_respects_provider_min_refresh_interval_no_spam():
    """§5: warm-up never issues a refresh faster than the feed's own interval."""
    feed = FakeTickerFeed()
    _select(feed)
    stamps = [t for _, t in feed.calls]
    gaps = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:], strict=False)]
    assert gaps, "warm-up must space its refreshes"
    assert min(gaps) >= feed.min_refresh_interval.total_seconds()


# =============================================================== Test D / I
def test_D_no_future_dated_observation_is_consumed():
    """D: warm-up only ever consumes observations stamped at 'now'."""
    feed = FakeTickerFeed()
    before = datetime.now(UTC)
    _select(feed)
    after = datetime.now(UTC)
    for symbol, stamp in feed.calls:
        assert before - timedelta(seconds=1) <= stamp <= after + timedelta(seconds=1), symbol


def test_I_returns_become_computable_after_warmup():
    """I: the EXISTING producer formula now has enough data (>=2 returns)."""
    feed = FakeTickerFeed()
    _select(feed)
    returns = _returns(feed.observations("SOPHUSDT"))
    assert len(returns) >= 2
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = sum(((value - mean) ** 2 for value in returns), Decimal("0")) / Decimal(
        len(returns)
    )
    assert variance.sqrt() >= 0


def test_provider_failure_degrades_to_warming_without_breaking_selection():
    """A provider fault must never fail the selection lifecycle."""
    feed = FakeTickerFeed(fail=True)
    service, record = _select(feed)

    assert record.status == ST_SUCCESS
    assert service.ticker_warmup_readiness("SOPHUSDT") == "WARMING"
    assert service.ticker_warmup_status["SOPHUSDT"]["status"] == "WARMING"
    assert service.ticker_warmup_status["SOPHUSDT"]["reason"] != ""


def test_warmup_status_never_exposes_a_direction():
    """Readiness is prerequisite-only; it must not carry any direction field."""
    service = MarketSelectionService(
        board=OpportunityBoard(), chief=FakeSelectingChief([]), ticker_feed=FakeTickerFeed()
    )
    service.ticker_warmup_status["X"] = {"status": "WARMING", "samples": 1}
    payload = repr(service.ticker_warmup_status).lower()
    for forbidden in ("long", "short", "buy", "sell", "direction", "action"):
        assert forbidden not in payload


# =============================================================== Test J (unit)
class _FakeEvidence:
    name = "quant_evidence_only"
    symbol = "SOPHUSDT"

    def analyze_evidence(self, _ctx):
        return {"regime": {"regime": "BULL"}, "signals": [], "data_quality": "FACTUAL"}


class _FakeAudit:
    def __init__(self, events):
        self.events = events

    async def log(self, action, **kwargs):
        self.events.append((action, kwargs))
        return "audit_1"


class _RecordingPlanner:
    def __init__(self):
        self.calls = 0
        self.last_execution_metadata = None
        self.last_quantity = None

    async def create_entry_signal(self, decision, **kwargs):
        self.calls += 1
        self.last_quantity = kwargs.get("quantity")
        self.last_execution_metadata = kwargs.get("execution_metadata")
        from types import SimpleNamespace

        return SimpleNamespace(trade_plan_id="plan_warmup_1"), SimpleNamespace(
            signal_id=decision.decision_id
        )


class _FixedChief:
    def __init__(self, action: str, size: float = 10.0):
        self.action = action
        self.size = size

    async def decide(self, ctx):
        return ChiefTraderDecision(
            decision_id="llm_warmup_j",
            symbol=ctx.symbol,
            action=self.action,
            market_regime="BULL",
            thesis="factual LLM thesis",
            position_size_request=self.size,
            leverage_request=2.0,
            stop_loss=99.0 if self.action == "LONG" else 102.0,
        )


def _ctx(*, realized_volatility: Decimal | None):
    now = datetime.now(UTC)
    book = OrderBook(symbol="SOPHUSDT", exchange="OKX")
    book.apply_snapshot(
        1, [(Decimal("100"), Decimal("1"))], [(Decimal("101"), Decimal("1"))], now=now
    )
    from crypto_trader.domain.models import Account, Instrument

    return StrategyContext(
        symbol="SOPHUSDT",
        book=book,
        account=Account(equity=Decimal("10000")),
        positions={},
        clock_time=now,
        run_id="run_warmup",
        mark_price=Decimal("100.5"),
        realized_volatility=realized_volatility,
        instrument=Instrument(
            symbol="SOPHUSDT", base_asset="SOP", quote_asset="USDT", step_size="0.00001"
        ),
    )


def _strategy(events, planner, chief, database):
    return LiveLLMDecisionStrategy(
        evidence_engine=_FakeEvidence(),
        chief=chief,
        planner=planner,
        decisions=LLMDecisionStore(database.session_factory),
        audit=_FakeAudit(events),
        sizer=LiveEntrySizingService(risk_fraction=Decimal("0.001")),
    )


def test_J_warmup_supplies_the_volatility_the_consumer_requires(database):
    """J: the volatility produced after warm-up is the one sizing propagates.

    Uses the PRODUCER's own formula on the WARM-UP's observations, then feeds
    that value through the real sizing path. No synthetic volatility is used.
    """
    feed = FakeTickerFeed()
    service, record = _select(feed)
    assert record.status == ST_SUCCESS

    observed = feed.observations("SOPHUSDT")
    returns = _returns(observed)
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = sum(((value - mean) ** 2 for value in returns), Decimal("0")) / Decimal(
        len(returns)
    )
    produced = variance.sqrt()

    events: list = []
    planner = _RecordingPlanner()
    strategy = _strategy(events, planner, _FixedChief("LONG"), database)

    signals = asyncio.run(strategy.on_market_data(_ctx(realized_volatility=produced)))

    assert planner.calls == 1
    assert signals, "a valid volatility must allow the plan path to proceed"
    assert planner.last_execution_metadata["volatility"] == str(produced)


def test_J_missing_volatility_still_fails_closed(database):
    """Fail-closed must survive the fix: no volatility -> no TradePlan."""
    events: list = []
    planner = _RecordingPlanner()
    strategy = _strategy(events, planner, _FixedChief("LONG"), database)

    signals = asyncio.run(strategy.on_market_data(_ctx(realized_volatility=None)))

    assert signals == []
    assert planner.calls == 0
    assert any(action == "LIVE_LLM_SIZING_UNAVAILABLE" for action, _ in events)
