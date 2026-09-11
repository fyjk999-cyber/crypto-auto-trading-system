"""Gate 2 tests: scanner correctness, fairness, snapshots, expiry, cadence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.coverage import (
    CoverageLedger,
    MarketSetCounts,
)
from crypto_trader.market_data.opportunity.factors import (
    FactorObservation,
    SymbolFacts,
)
from crypto_trader.market_data.opportunity.pool import (
    REASON_FAIR_ROTATION,
    REASON_OLDEST_UNRESEARCHED,
    build_research_pool,
)
from crypto_trader.market_data.opportunity.scanner import (
    FactorCandidate,
    FactorScanner,
    RotationScheduler,
)
from crypto_trader.market_data.opportunity.service import (
    OpportunityScannerService,
    ScannerConfig,
)
from crypto_trader.market_data.opportunity.snapshot import (
    DEFAULT_CANDIDATE_TTL_SECONDS,
    STATUS_FAILED,
    STATUS_PARTIAL,
    SnapshotExpired,
    require_usable_snapshot,
    snapshot_expiry,
)
from crypto_trader.market_data.opportunity.universe import Instrument


# ------------------------------------------------------------- priority ranking
class _StubDetector:
    """Emits one fixed-strength observation regardless of declaration order."""

    def __init__(self, name: str, strength: float) -> None:
        self.name = name
        self._strength = strength

    def evaluate(self, facts: SymbolFacts) -> FactorObservation:
        return FactorObservation(
            symbol=facts.symbol,
            factor=self.name,
            status="TRIGGERED",
            strength=self._strength,
            observed_at="2026-01-01T00:00:00+00:00",
        )


def _facts(symbol: str, *, turnover: float = 1_000_000.0) -> SymbolFacts:
    # funding_rate=0.0 keeps the symbol scannable (a VALID factual zero) while
    # the stub detectors provide the strength values under test.
    return SymbolFacts(
        symbol=symbol,
        candles=[],
        volume_24h_usd=turnover,
        funding_rate=0.0,
        funding_quality="VALID",
    )


def test_factor_declaration_order_does_not_change_ranking():
    """§6.1: ranking uses the priority contract, not ``triggered[0]``."""
    weak = _StubDetector("WEAK_FIRST", 0.10)
    strong = _StubDetector("STRONG_SECOND", 0.90)
    scanner_a = FactorScanner(factors=(weak, strong))
    candidates_a = scanner_a.scan({"AAAUSDT": _facts("AAAUSDT"), "BBBUSDT": _facts("BBBUSDT")})

    # declaration order reversed, same factual strengths
    strong_reversed = _StubDetector("STRONG_SECOND", 0.90)
    weak_reversed = _StubDetector("WEAK_FIRST", 0.10)
    scanner_b = FactorScanner(factors=(strong_reversed, weak_reversed))
    candidates_b = scanner_b.scan({"AAAUSDT": _facts("AAAUSDT"), "BBBUSDT": _facts("BBBUSDT")})

    assert [c.symbol for c in candidates_a] == [c.symbol for c in candidates_b]
    for candidate in candidates_a:
        assert candidate.priority == pytest.approx(0.90)
        assert candidate.strongest_strength == pytest.approx(0.90)
        assert candidate.strongest_factor == "STRONG_SECOND"


def test_ranking_prefers_strongest_not_first():
    first_weak = _StubDetector("FIRST", 0.20)
    later_strong = _StubDetector("LAST", 0.95)
    scanner = FactorScanner(factors=(first_weak, later_strong))
    candidates = scanner.scan(
        {"UNIFORMUSDT": _facts("UNIFORMUSDT")}
    )
    assert candidates[0].strongest_strength == pytest.approx(0.95)
    assert candidates[0].strongest_factor == "LAST"


# ------------------------------------------------------------------- rotation
def test_rotation_cursor_progresses_and_does_not_repeat_forever():
    rotation = RotationScheduler()
    universe = [f"S{i}USDT" for i in range(9)]
    rotation.sync(universe)
    first_batch = rotation.next_batch(exclude=set(), size=3)
    second_batch = rotation.next_batch(exclude=set(), size=3)
    third_batch = rotation.next_batch(exclude=set(), size=3)
    assert first_batch[0] != second_batch[0] != third_batch[0]
    assert set(first_batch + second_batch + third_batch) == set(universe)


def test_rotation_orders_by_oldest_analysis_clock():
    ledger = CoverageLedger()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    rotation = RotationScheduler()
    rotation.sync(["AUSDT", "BUSDT", "CUSDT"])
    ledger.mark_analysis_attempt("AUSDT", now - timedelta(seconds=10), success=True)
    ledger.mark_analysis_attempt("BUSDT", now - timedelta(seconds=500), success=True)
    # CUSDT has never been analysed -> must come first
    batch = rotation.next_batch(exclude=set(), size=3, ledger=ledger, now=now)
    assert batch[0] == "CUSDT"
    assert batch[1] == "BUSDT"
    assert batch[2] == "AUSDT"


def test_rotation_state_survives_restart():
    rotation = RotationScheduler()
    rotation.sync(["AUSDT", "BUSDT", "CUSDT"])
    rotation.next_batch(exclude=set(), size=1)
    state = rotation.export_state()
    restored = RotationScheduler()
    assert restored.import_state(state) is True
    assert restored.next_batch(exclude=set(), size=1) == rotation.next_batch(exclude=set(), size=1)


def test_persistent_hot_candidates_do_not_starve_fair_rotation():
    """§6.3: factor candidates are capped so rotation capacity is reserved."""
    ledger = CoverageLedger()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    rotation = RotationScheduler()
    non_factors = [f"N{i}USDT" for i in range(12)]
    rotation.sync(non_factors)

    def snapshot(scan_index: int):
        hot = tuple(
            FactorCandidate(
                symbol=f"HOT{i}USDT",
                triggered=[
                    FactorObservation(
                        symbol=f"HOT{i}USDT",
                        factor="MOMENTUM_EXPANSION",
                        status="TRIGGERED",
                        strength=0.9,
                        observed_at=now.isoformat(),
                    )
                ],
                priority=0.9,
                scan_id=f"scan{scan_index}",
                expires_at=now + timedelta(seconds=180),
            )
            for i in range(12)
        )

        class _Snap:
            pass

        snap = _Snap()
        snap.scan_id = f"scan{scan_index}"
        snap.factor_candidates = hot
        snap.rotation_symbols = tuple(
            rotation.next_batch(exclude={c.symbol for c in hot}, size=5, ledger=ledger, now=now)
        )
        snap.observable_rows = tuple(
            {
                "symbol": candidate_symbol,
                "vol_usd_24h": 1_000_000.0,
                "funding_quality": "VALID",
                "ticker_quality": "VALID",
                "execution_supported": True,
            }
            for candidate_symbol in non_factors
        )
        return snap

    exposed: set[str] = set()
    for index in range(4):
        pool = build_research_pool(snapshot=snapshot(index), ledger=ledger, now=now)
        exposed.update(
            entry.symbol for entry in pool if REASON_FAIR_ROTATION in entry.reasons
        )
        # simulate the analysed symbols advancing their analysis clock
        for analysed in [e.symbol for e in pool if REASON_FAIR_ROTATION in e.reasons]:
            ledger.mark_analysis_attempt(analysed, now, success=True)

    assert len(exposed) >= 8, exposed
    assert len(exposed) > 5  # the same first rotation symbol is not returned forever


def test_pool_is_capped_and_reason_labelled():
    ledger = CoverageLedger()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    rows = tuple(
        {
            "symbol": f"S{i}USDT",
            "vol_usd_24h": float(1_000_000 - i),
            "price_change_24h_pct": float(i),
            "funding_quality": "VALID",
            "ticker_quality": "VALID",
            "execution_supported": True,
        }
        for i in range(60)
    )

    class _Snap:
        scan_id = "scan-x"
        factor_candidates = ()
        rotation_symbols = ()
        observable_rows = rows

    pool = build_research_pool(snapshot=_Snap(), ledger=ledger, now=now)
    assert len(pool) == 30
    assert all(entry.reasons for entry in pool)
    assert any(REASON_OLDEST_UNRESEARCHED in e.reasons for e in pool)


# ---------------------------------------------------------------- expiry/state
def test_candidate_expires_with_its_scan():
    board = OpportunityBoard()
    now = datetime.now(UTC)
    expired = FactorCandidate(
        symbol="BTCUSDT",
        scan_id="scan-old",
        created_at=now - timedelta(seconds=600),
        expires_at=now - timedelta(seconds=1),
    )
    board.publish(
        candidates=[expired],
        broad_market={},
        scan_stats={},
        universe_size=1,
        eligible_count=1,
    )
    # legacy publish binds unbound candidates; this one was already bound+expired
    assert board.current_snapshot() is not None
    assert board.candidate_for("BTCUSDT", now=now) is None
    assert board.historical_candidate_for("BTCUSDT") is not None


def test_failed_scan_does_not_make_stale_board_current():
    board = OpportunityBoard()
    now = datetime.now(UTC)

    class _Snap:
        pass

    from crypto_trader.market_data.opportunity.snapshot import (
        STATUS_COMPLETE,
        MarketObservationSnapshot,
    )

    good = MarketObservationSnapshot(
        scan_id="scan-good",
        started_at=now,
        completed_at=now,
        expires_at=now + timedelta(seconds=180),
        status=STATUS_COMPLETE,
    )
    board.publish_snapshot(good)
    assert require_usable_snapshot(board.current_snapshot(), now=now).scan_id == "scan-good"

    failed = MarketObservationSnapshot(
        scan_id="scan-failed",
        started_at=now,
        completed_at=now,
        expires_at=now + timedelta(seconds=180),
        status=STATUS_FAILED,
        error="EMPTY_TICKERS_BATCH",
    )
    board.publish_snapshot(failed)
    assert board.current_snapshot().scan_id == "scan-failed"
    assert board.current_candidates() == []
    with pytest.raises(SnapshotExpired):
        require_usable_snapshot(board.current_snapshot(), now=now)


def test_expired_snapshot_is_refused_for_autonomous_use():
    now = datetime.now(UTC)
    from crypto_trader.market_data.opportunity.snapshot import (
        STATUS_COMPLETE,
        MarketObservationSnapshot,
    )

    stale = MarketObservationSnapshot(
        scan_id="scan-stale",
        started_at=now - timedelta(seconds=600),
        completed_at=now - timedelta(seconds=599),
        expires_at=now - timedelta(seconds=419),
        status=STATUS_COMPLETE,
    )
    assert stale.is_expired(now=now) is True
    with pytest.raises(SnapshotExpired):
        require_usable_snapshot(stale, now=now)
    assert snapshot_expiry(now, 180) > now
    assert DEFAULT_CANDIDATE_TTL_SECONDS == 180.0


# -------------------------------------------------------------------- service
class _SlowClient:
    """One fast symbol + one symbol that never returns in time."""

    def __init__(self) -> None:
        self.candle_calls: list[str] = []

    async def get_tickers(self, inst_type):
        ts = str(int(datetime.now(UTC).timestamp() * 1000))
        rows = []
        for _symbol, inst in _SlowUniverse._Snap.instruments.items():
            rows.append(
                {
                    "instId": inst.inst_id,
                    "last": "10",
                    "open24h": "9",
                    "bidPx": "9.99",
                    "askPx": "10.01",
                    "bidSz": "100",
                    "askSz": "100",
                    "vol24h": "1000",
                    "volCcy24h": "1000000",  # -> 10M USD estimated turnover
                    "ts": ts,
                }
            )
        return rows

    async def get_open_interests(self, inst_type):
        return [
            {"instId": inst.inst_id, "oi": "1000"}
            for inst in _SlowUniverse._Snap.instruments.values()
        ]

    async def get_funding_rates(self, inst_type):
        return [
            {"instId": inst.inst_id, "fundingRate": "0.0001"}
            for inst in _SlowUniverse._Snap.instruments.values()
        ]

    async def get_candles(self, inst_id, bar, limit):
        self.candle_calls.append(inst_id)
        if inst_id == "SLOW-USDT-SWAP":
            await asyncio.sleep(5)
            return []
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        return [
            [str(now_ms - index * 60_000), "10", "10.5", "9.5", "10", "100", "0", "0", "1"]
            for index in range(1, 4)
        ]


class _SlowUniverse:
    class _Snap:
        instruments = {
            "FASTUSDT": Instrument(
                symbol="FASTUSDT",
                inst_id="FAST-USDT-SWAP",
                state="live",
                settle_ccy="USDT",
                ct_val="1",
                list_time=None,
                raw={},
            ),
            "SLOWUSDT": Instrument(
                symbol="SLOWUSDT",
                inst_id="SLOW-USDT-SWAP",
                state="live",
                settle_ccy="USDT",
                ct_val="1",
                list_time=None,
                raw={},
            ),
        }
        size = 2

    async def refresh(self, force=False):
        return self._Snap()


def test_one_slow_symbol_does_not_hang_the_scanner():
    client = _SlowClient()
    board = OpportunityBoard()
    service = OpportunityScannerService(
        universe=_SlowUniverse(),
        okx_client=client,
        board=board,
        config=ScannerConfig(
            per_request_timeout_seconds=0.2,
            whole_scan_deadline_seconds=3.0,
            max_concurrency=4,
        ),
    )
    started = datetime.now(UTC)
    summary = asyncio.run(asyncio.wait_for(service.scan_once(), timeout=10))
    elapsed = (datetime.now(UTC) - started).total_seconds()
    assert elapsed < 5
    assert summary["status"] == STATUS_PARTIAL
    # exactly one ERROR (the timed-out symbol) and no empty-response noise
    assert summary["candle_coverage"]["errors"] == 1
    assert summary["candle_coverage"]["empty_responses"] == 0
    assert summary["scanned"] == 2  # both facts exist; only one candle fetch failed


def test_scan_cycles_do_not_overlap_and_cadence_is_targeted():
    class FakeClock:
        def __init__(self) -> None:
            self.now = 0.0

        def __call__(self) -> float:
            return self.now

    clock = FakeClock()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now += seconds

    client = _SlowClient()
    board = OpportunityBoard()
    service = OpportunityScannerService(
        universe=_SlowUniverse(),
        okx_client=client,
        board=board,
        config=ScannerConfig(
            scan_interval_seconds=90.0,
            per_request_timeout_seconds=0.2,
            whole_scan_deadline_seconds=2.0,
        ),
        max_cycles=3,
        sleep=fake_sleep,
        clock=clock,
    )
    asyncio.run(service.run_forever())
    assert service.cycles_completed == 3
    assert service.last_cycle is not None
    assert service.last_cycle.status == "ON_SCHEDULE"
    assert service.scan_overrun_count == 0
    # one cycle ends before the next begins: sleeps are non-negative and the
    # target grid advances by the configured cadence
    assert all(delay >= 0 for delay in sleeps)
    assert abs(sum(sleeps) - 2 * 90.0) < 1.0


def test_scan_overrun_is_marked_and_not_hidden():
    class SlowScanService(OpportunityScannerService):
        async def scan_once(self):
            await asyncio.sleep(0.35)
            return {"status": "COMPLETE"}

    clock_state = {"now": 0.0}

    def clock():
        return clock_state["now"] if False else _real_monotonic()

    import time as _time

    def _real_monotonic():
        return _time.monotonic()

    async def fake_sleep(seconds: float) -> None:
        return None

    service = SlowScanService(
        universe=_SlowUniverse(),
        okx_client=_SlowClient(),
        board=OpportunityBoard(),
        config=ScannerConfig(scan_interval_seconds=0.1),
        max_cycles=1,
        sleep=fake_sleep,
    )
    asyncio.run(service.run_forever())
    assert service.scan_overrun_count == 1
    assert service.last_cycle.status == "SCAN_OVERRUN"


def test_market_set_counts_are_never_conflated():
    counts = MarketSetCounts()
    counts.record_scan(
        discovered=100, observable=80, attempted=40, success=20, ready=15, execution_supported=70
    )
    payload = counts.as_dict()
    assert payload["discovered_count"] == 100
    assert payload["analysis_attempted_count"] == 40
    assert payload["analysis_success_count"] == 20
    assert payload["analysis_ready_count"] == 15
    assert payload["analysis_attempted_count"] != payload["analysis_success_count"]
