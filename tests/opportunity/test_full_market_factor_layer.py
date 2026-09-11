"""MASTER DIRECTIVE §31-§39 required tests: full-market factor layer.

Proves the permanent authority invariants against the real canonical code:

  §31  single-factor admission (OR semantics, no consensus)
  §32  admission via a DIFFERENT single factor
  §33  multi-factor evidence merges into ONE candidate
  §34  factor output is not a trade signal (no direction, no execution path)
  §35  DeepSeek may trade WITHOUT any factor trigger (mocked canonical chain)
  §36  factor/evidence UNAVAILABLE never blocks trading
  §37  factors cannot reach Execution without DeepSeek decision + TradePlan
  §38  bullish factor evidence + SHORT decision is preserved
  §39  no candidate starvation (rotation keeps non-candidates reviewable)
  §26/§27 per-symbol evidence routing with factual warmup, no BTC reuse
  §29/§30 board counters + durable llm_decisions lineage
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from crypto_trader.alpha.evidence_router import PerSymbolEvidenceRouter
from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.models import Account, Instrument, SignalIntent
from crypto_trader.llm.tools.alpha import build_canonical_tool_registry
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.runtime_strategy import LiveLLMDecisionStrategy
from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.context import build_opportunity_context
from crypto_trader.market_data.opportunity.factors import (
    Candle,
    MomentumFactor,
    SymbolFacts,
    validate_no_direction_semantics,
)
from crypto_trader.market_data.opportunity.scanner import (
    CANDIDATE_SOURCE_FACTOR_SCANNER,
    CANDIDATE_SOURCE_MARKET_OBSERVER,
    FactorCandidate,
    FactorScanner,
    RotationScheduler,
)
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.sizing.service import LiveEntrySizingService
from crypto_trader.strategy.base import StrategyContext

# --------------------------------------------------------------------- helpers


def rising_candles(n: int = 120, base: float = 100.0, step: float = 0.5) -> list[Candle]:
    start = 1_700_000_000_000
    return [
        Candle(
            ts_ms=start + i * 60_000,
            open=base + i * step,
            high=base + i * step + 0.2,
            low=base + i * step - 0.2,
            close=base + i * step,
            volume=1.0,
        )
        for i in range(n)
    ]


def flat_candles(n: int = 120, base: float = 100.0) -> list[Candle]:
    start = 1_700_000_000_000
    return [
        Candle(ts_ms=start + i * 60_000, open=base, high=base, low=base, close=base, volume=1.0)
        for i in range(n)
    ]


def facts(**kwargs) -> SymbolFacts:
    kwargs.setdefault("symbol", "ETHUSDT")
    return SymbolFacts(**kwargs)


class FakeEvidenceEngine:
    name = "quant_evidence_only"
    symbol = "BTCUSDT"

    def analyze_evidence(self, _ctx):
        return {"regime": {"regime": "BULL"}, "data_quality": "FACTUAL_ORDERBOOK"}


class FakeChief:
    def __init__(self, action: str, decision_id: str = "llm_factor_layer_test"):
        self.action = action
        self.decision_id = decision_id
        self.calls = 0

    async def decide(self, ctx):
        self.calls += 1
        directional = self.action in {"LONG", "SHORT"}
        from crypto_trader.llm_chief.decision import ChiefTraderDecision

        return ChiefTraderDecision(
            decision_id=self.decision_id,
            symbol=ctx.symbol,
            action=self.action,
            market_regime=ctx.regime,
            thesis="factual LLM thesis" if directional else "",
            position_size_request=0.01 if directional else 0.0,
            leverage_request=2.0 if directional else 0.0,
            stop_loss=(101.0 if self.action == "SHORT" else 99.0)
            if directional
            else None,  # SHORT stop above mid
        )


class FakeAudit:
    def __init__(self, events):
        self.events = events

    async def log(self, action, **kwargs):
        self.events.append((action, kwargs))
        return "audit_1"


class FakePlanner:
    def __init__(self, events):
        self.events = events

    async def create_entry_signal(self, decision, **kwargs):
        self.events.append(("plan", decision.decision_id))
        signal = SignalIntent(
            signal_id=decision.decision_id,
            strategy_id="live_llm",
            symbol=decision.symbol,
            side=OrderSide.BUY if decision.action == "LONG" else OrderSide.SELL,
            quantity=kwargs.get("quantity", Decimal(str(decision.position_size_request))),
            reason=decision.thesis,
            metadata={"trade_plan_id": "plan_1", "decision_id": decision.decision_id},
        )
        return SimpleNamespace(trade_plan_id="plan_1"), signal


def make_ctx(symbol: str = "BTCUSDT") -> StrategyContext:
    now = datetime.now(UTC)
    book = OrderBook(symbol=symbol, exchange="OKX")
    book.apply_snapshot(
        1, [(Decimal("100"), Decimal("1"))], [(Decimal("101"), Decimal("1"))], now=now
    )
    return StrategyContext(
        symbol=symbol,
        book=book,
        account=Account(equity=Decimal("10000")),
        positions={},
        clock_time=now,
        run_id="run_1",
        mark_price=Decimal("100.5"),
        realized_volatility=Decimal("0.01"),
        instrument=Instrument(
            symbol=symbol, base_asset=symbol[:-4], quote_asset="USDT", step_size="0.00001"
        ),
    )


# ------------------------------------------------------------------- §31 §32 §33


def test_single_factor_trigger_admits_candidate_or_semantics():
    """§31: ONE independently triggered factor is sufficient admission."""
    scanner = FactorScanner(factors=(MomentumFactor(),))
    big_move = rising_candles()
    f = facts(candles=big_move, last_price=big_move[-1].close * 1.02)
    candidates = scanner.scan({"ETHUSDT": f})
    assert len(candidates) == 1
    c = candidates[0]
    assert c.symbol == "ETHUSDT"
    assert c.factor_trigger_count == 1
    assert c.factor_evidence_present is True
    assert c.source == CANDIDATE_SOURCE_FACTOR_SCANNER
    assert c.triggered[0].factor == "MOMENTUM_EXPANSION"


def test_different_single_factor_also_admits():
    """§32: admission does not depend on one privileged factor."""
    from crypto_trader.market_data.opportunity.factors import DEFAULT_FACTORS

    scanner = FactorScanner(factors=DEFAULT_FACTORS)
    f = facts(candles=[], funding_rate=0.004)  # funding only, no candles
    candidates = scanner.scan({"XRPUSDT": f})
    assert len(candidates) == 1
    assert candidates[0].triggered[0].factor == "FUNDING_EXTREME"


def test_multi_factor_evidence_merges_into_one_candidate():
    """§33: several triggered factors enrich one candidate; never many signals."""
    from crypto_trader.market_data.opportunity.factors import DEFAULT_FACTORS

    scanner = FactorScanner(factors=DEFAULT_FACTORS)
    cands = rising_candles()
    f = facts(
        candles=cands,
        last_price=cands[-1].close * 1.02,
        funding_rate=0.004,
        volume_24h_usd=50_000_000,
    )
    candidates = scanner.scan({"ETHUSDT": f})
    assert len(candidates) == 1
    names = {o.factor for o in candidates[0].triggered}
    assert "MOMENTUM_EXPANSION" in names
    assert "FUNDING_EXTREME" in names


# ------------------------------------------------------------------------ §34


def test_factor_output_is_factual_and_has_no_execution_surface():
    """§34: factor semantics are factual; candidates are not signals/orders."""
    scanner = FactorScanner(factors=(MomentumFactor(),))
    big = rising_candles()
    candidates = scanner.scan({"ETHUSDT": facts(candles=big, last_price=big[-1].close * 1.02)})
    validate_no_direction_semantics([o for c in candidates for o in c.triggered])
    payload = candidates[0].as_dict()
    blob = str(payload).upper()
    for word in ("BUY", "SELL", "OPEN_LONG", "OPEN_SHORT"):
        assert word not in blob
    candidate = candidates[0]
    for forbidden in ("to_signal", "to_order", "execute", "submit", "place_order"):
        assert not hasattr(candidate, forbidden)
    assert not isinstance(candidate, SignalIntent)


# ------------------------------------------------------------------- §35 §36


async def test_deepseek_may_trade_without_any_factor_trigger(database):
    """§35: canonical chain executes a LONG with an EMPTY opportunity board."""
    events = []
    board = OpportunityBoard()  # no candidates published at all
    chief = FakeChief("LONG")
    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        chief=chief,
        planner=FakePlanner(events),
        decisions=LLMDecisionStore(database.session_factory),
        audit=FakeAudit(events),
        sizer=LiveEntrySizingService(),
        opportunity_board=board,
    )
    signals = await strategy.on_market_data(make_ctx("BTCUSDT"))
    assert chief.calls == 1
    assert len(signals) == 1
    assert signals[0].side == OrderSide.BUY
    stored = await LLMDecisionStore(database.session_factory).get("llm_factor_layer_test")
    assert stored.opportunity_source == CANDIDATE_SOURCE_MARKET_OBSERVER
    assert stored.factor_evidence_present is False
    assert stored.triggered_factors == []
    stats = board.snapshot()["stats"]
    assert stats["directional_without_factor_evidence"] == 1
    assert stats["directional_with_factor_evidence"] == 0


async def test_unavailable_evidence_never_blocks_the_decision(database):
    """§36/§28: missing factor data must not gate DeepSeek's decision."""
    events = []
    board = OpportunityBoard()
    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        chief=FakeChief("NO_TRADE"),
        planner=FakePlanner(events),
        decisions=LLMDecisionStore(database.session_factory),
        audit=FakeAudit(events),
        sizer=LiveEntrySizingService(),
        opportunity_board=board,
        evidence_router=PerSymbolEvidenceRouter(feed=None),  # cannot warm anything
    )
    signals = await strategy.on_market_data(make_ctx("SOLUSDT"))
    assert signals == []  # NO_TRADE decision, not a data failure
    stored = await LLMDecisionStore(database.session_factory).get("llm_factor_layer_test")
    assert stored is not None and stored.action == "NO_TRADE"


def test_unresolvable_symbol_tool_reports_unavailable_quality():
    """§27/§28: unresolvable per-symbol tools honestly report UNAVAILABLE."""
    router = PerSymbolEvidenceRouter(feed=None, max_engines=0)  # cannot resolve
    registry = build_canonical_tool_registry(router)
    evidence = _run(registry.call("trend", "NEWUSDT", {"strategy_context": make_ctx("NEWUSDT")}))
    assert evidence.data_quality == "UNAVAILABLE"
    assert "evidence:UNAVAILABLE" in evidence.source_refs


def _run(coro):
    import asyncio

    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ------------------------------------------------------------------------ §37


def test_factor_layer_never_imports_execution_surfaces():
    """§37: opportunity modules cannot reach Execution/OrderManager paths."""
    code = (
        "import sys\n"
        "import crypto_trader.market_data.opportunity.factors\n"
        "import crypto_trader.market_data.opportunity.scanner\n"
        "import crypto_trader.market_data.opportunity.board\n"
        "import crypto_trader.market_data.opportunity.context\n"
        "import crypto_trader.market_data.opportunity.service\n"
        "banned = [m for m in sys.modules if m.startswith('crypto_trader.execution')]\n"
        "banned += [m for m in sys.modules if m.startswith('crypto_trader.order')]\n"
        "assert not banned, banned\n"
        "print('CLEAN')\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd="/Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-fullmarket",
    )
    assert out.returncode == 0, out.stderr
    assert "CLEAN" in out.stdout


# ------------------------------------------------------------------------ §38


async def test_bullish_factor_evidence_does_not_force_direction(database):
    """§7/§38: bullish candidate + DeepSeek SHORT is preserved end-to-end."""
    events = []
    board = OpportunityBoard()
    big = rising_candles()
    candidate = FactorCandidate(
        symbol="BTCUSDT",
        source=CANDIDATE_SOURCE_FACTOR_SCANNER,
        nominated_reason="momentum expansion observed",
    )
    board.publish(
        candidates=[candidate],
        broad_market={},
        scan_stats={},
        universe_size=100,
        eligible_count=80,
    )
    scanner = FactorScanner(factors=(MomentumFactor(),))
    obs = scanner.scan_symbol(facts(candles=big, last_price=big[-1].close * 1.02))[0]
    candidate.triggered = [o for o in obs if o.status == "TRIGGERED"]
    assert candidate.factor_evidence_present is True

    chief = FakeChief("SHORT", decision_id="short_despite_bullish")
    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        chief=chief,
        planner=FakePlanner(events),
        decisions=LLMDecisionStore(database.session_factory),
        audit=FakeAudit(events),
        sizer=LiveEntrySizingService(),
        opportunity_board=board,
    )
    signals = await strategy.on_market_data(make_ctx("BTCUSDT"))
    assert len(signals) == 1
    assert signals[0].side == OrderSide.SELL  # DeepSeek contradicted the factor
    stored = await LLMDecisionStore(database.session_factory).get("short_despite_bullish")
    assert stored.action == "SHORT"
    assert stored.opportunity_source == CANDIDATE_SOURCE_FACTOR_SCANNER
    assert stored.factor_evidence_present is True
    assert stored.triggered_factors  # evidence recorded, direction untouched


# ------------------------------------------------------------------------ §39


def test_rotation_prevents_candidate_starvation():
    """§39: non-candidate eligible symbols still get review exposure."""
    rotation = RotationScheduler()
    universe = [f"S{i}USDT" for i in range(12)]
    rotation.sync(universe)
    seen = set()
    for _ in range(4):
        seen.update(rotation.next_batch(exclude=set(), size=3))
    assert seen == set(universe)  # everything gets a turn

    board = OpportunityBoard()
    candidate = FactorCandidate(symbol="S0USDT")
    board.publish(
        candidates=[candidate],
        broad_market={},
        scan_stats={},
        universe_size=12,
        eligible_count=12,
        rotation_symbols=[f"S{i}USDT" for i in range(1, 12)],
    )
    board.mark_reviewed("S0USDT")  # just reviewed — cooldown elapsed guard
    picks = {board.next_agenda_symbol() for _ in range(8)}
    assert "S0USDT" not in picks or len(picks) > 1
    assert picks & {f"S{i}USDT" for i in range(1, 12)}


def test_candidate_priority_ranks_but_never_gates():
    """§14: ranking is priority-only; a weaker candidate is still admitted."""
    scanner = FactorScanner(factors=(MomentumFactor(),))
    huge = rising_candles(step=5.0)
    small = rising_candles(step=0.05)
    cands = scanner.scan(
        {
            "BIGUSDT": facts(symbol="BIGUSDT", candles=huge, last_price=huge[-1].close * 1.10),
            "SMALLUSDT": facts(
                symbol="SMALLUSDT", candles=small, last_price=small[-1].close * 1.001
            ),
        }
    )
    assert {c.symbol for c in cands} == {"BIGUSDT", "SMALLUSDT"}
    assert cands[0].symbol == "BIGUSDT"  # priority order only


# ------------------------------------------------------- §26/§27 §29/§30 §43


async def test_evidence_router_is_strictly_per_symbol():
    """§26: no cross-symbol evidence reuse; BTC engine never serves ETH."""
    router = PerSymbolEvidenceRouter(feed=None)
    btc_engine = await router.resolve("BTCUSDT")
    eth_engine = await router.resolve("ETHUSDT")
    assert btc_engine is not eth_engine
    assert btc_engine.symbol == "BTCUSDT"
    assert eth_engine.symbol == "ETHUSDT"
    assert router.get("SOLUSDT") is None  # existing-only lookup: no creation
    ctx = make_ctx("SOLUSDT")
    evidence = router.analyze_evidence(ctx)
    assert evidence["data_quality"] == "UNAVAILABLE"


async def test_evidence_router_evicts_lru_symbol_instead_of_starving_new_market():
    router = PerSymbolEvidenceRouter(feed=None, max_engines=2)
    first = await router.resolve("BTCUSDT")
    await router.resolve("ETHUSDT")
    await router.resolve("BTCUSDT")  # BTC is now most recently used
    sol = await router.resolve("SOLUSDT")
    assert sol is not None and sol.symbol == "SOLUSDT"
    assert router.get("ETHUSDT") is None
    assert router.get("BTCUSDT") is first


async def test_evidence_router_rotates_over_40_symbols_without_starvation():
    router = PerSymbolEvidenceRouter(feed=None, max_engines=40)
    for index in range(45):
        await router.resolve(f"SYM{index}USDT")
    resident = set(router.known_symbols())
    assert len(resident) == 40
    assert not {f"SYM{index}USDT" for index in range(5)} & resident
    assert "SYM44USDT" in resident


async def test_evidence_router_retries_failed_warmup_after_bounded_delay():
    class FlakyFeed:
        def __init__(self):
            self.calls = 0

        async def warmup(self, *args, **kwargs):
            self.calls += 1
            return self.calls > 1

    feed = FlakyFeed()
    router = PerSymbolEvidenceRouter(feed=feed)
    engine = await router.resolve("BTCUSDT")
    assert engine is not None
    assert router.stats["warmups_failed"] == 1
    router._last_refresh["BTCUSDT"] -= 31
    await router.resolve("BTCUSDT")
    assert router.stats["warmups_ok"] == 1
    assert feed.calls == 2


async def test_board_counters_and_lineage_survive_storage(database):
    """§29/§30: observability proves traded-with vs traded-without factors."""
    events = []
    board = OpportunityBoard()
    big = rising_candles()
    candidate = FactorCandidate(
        symbol="BTCUSDT",
        source=CANDIDATE_SOURCE_FACTOR_SCANNER,
        nominated_reason="momentum",
    )
    obs, _ = FactorScanner(factors=(MomentumFactor(),)).scan_symbol(
        facts(candles=big, last_price=big[-1].close * 1.02)
    )
    candidate.triggered = [o for o in obs if o.status == "TRIGGERED"]
    board.publish(
        candidates=[candidate], broad_market={}, scan_stats={}, universe_size=5, eligible_count=5
    )
    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        chief=FakeChief("LONG"),
        planner=FakePlanner(events),
        decisions=LLMDecisionStore(database.session_factory),
        audit=FakeAudit(events),
        sizer=LiveEntrySizingService(),
        opportunity_board=board,
    )
    await strategy.on_market_data(make_ctx("BTCUSDT"))
    snap = board.snapshot()
    assert snap["stats"]["directional_with_factor_evidence"] == 1
    recent = snap["recent_decisions"][0]
    assert recent["candidate_source"] == CANDIDATE_SOURCE_FACTOR_SCANNER
    stored = await LLMDecisionStore(database.session_factory).get("llm_factor_layer_test")
    assert stored.opportunity_source == CANDIDATE_SOURCE_FACTOR_SCANNER
    assert stored.factor_evidence_present is True
    assert any(f["factor"] == "MOMENTUM_EXPANSION" for f in stored.triggered_factors)


def test_opportunity_context_is_bounded_and_authority_explicit():
    board = OpportunityBoard()
    board.publish(
        candidates=[],
        broad_market={"top_abs_movers_24h": [{"symbol": "X", "price_change_24h_pct": 1.0}]},
        scan_stats={},
        universe_size=5,
        eligible_count=5,
    )
    ctx = build_opportunity_context(symbol="BTCUSDT", candidate=None, board=board)
    assert ctx["factor_evidence_present"] is False
    assert "never prevents trading" in ctx["authority_note"]
    import json

    assert len(json.dumps(ctx)) < 4000  # bounded token cost (§25)


def test_factor_thresholds_are_stable_config():
    """§43: thresholds are frozen values, not learned mutable state."""
    from crypto_trader.market_data.opportunity.factors import FactorThresholds

    t = FactorThresholds()
    assert t.momentum_return_15m == 0.008
    assert t.funding_extreme == 0.0015
    assert not hasattr(t, "learn") and not hasattr(t, "update")


# ------------------------------------------------------------- migration §47


def test_migration_chain_extends_llm_decisions_with_lineage(tmp_path):
    """§30/§47: alembic upgrade head applies 0023_opportunity_lineage."""
    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path}/mig_test.db")
    command.upgrade(cfg, "head")
    engine = sa.create_engine(f"sqlite:///{tmp_path}/mig_test.db")
    insp = sa.inspect(engine)
    cols = {c["name"] for c in insp.get_columns("llm_decisions")}
    engine.dispose()
    assert {
        "opportunity_source",
        "triggered_factors_json",
        "factor_evidence_present",
        "nominated_reason",
    } <= cols


# ------------------------------------------------------- cooldown semantics


async def test_per_symbol_attempt_cooldown_is_independent(database):
    """Symbols have independent attempt cooldowns (multi-symbol agenda)."""
    events = []
    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        chief=FakeChief("NO_TRADE", decision_id="cooldown-x"),
        planner=FakePlanner(events),
        decisions=LLMDecisionStore(database.session_factory),
        audit=FakeAudit(events),
        sizer=LiveEntrySizingService(),
    )
    ctx_a = make_ctx("BTCUSDT")
    await strategy.on_market_data(ctx_a)
    await strategy.on_market_data(ctx_a)
    assert strategy._last_attempt_by_symbol["BTCUSDT"] is not None
    later = make_ctx("BTCUSDT")
    later.clock_time = ctx_a.clock_time + timedelta(seconds=31)
    await strategy.on_market_data(later)
    assert strategy._last_attempt_by_symbol["BTCUSDT"] == later.clock_time


def test_okx_ticker_volume_is_derived_to_usd_turnover():
    """Live-verified field mapping: OKX SWAP tickers have no volUsd24h.

    USD turnover must be derived factually from volCcy24h (base volume) x
    last, falling back to contracts x ctVal. Guards against a silent
    eligible_count=0 whole-universe exclusion.
    """
    import asyncio

    from crypto_trader.market_data.opportunity.eligibility import EligibilityFilter
    from crypto_trader.market_data.opportunity.factors import DEFAULT_FACTORS
    from crypto_trader.market_data.opportunity.scanner import FactorScanner
    from crypto_trader.market_data.opportunity.service import OpportunityScannerService
    from crypto_trader.market_data.opportunity.universe import Instrument

    class FakeUniverse:
        class _Snap:
            instruments = {
                "BTCUSDT": Instrument(
                    symbol="BTCUSDT", inst_id="BTC-USDT-SWAP", state="live",
                    settle_ccy="USDT", ct_val="0.01", list_time=None, raw={},
                )
            }
            size = 1
        async def refresh(self, force=False):
            return self._Snap()

    class FakeClient:
        async def get_tickers(self, inst_type):
            return [{
                "instId": "BTC-USDT-SWAP", "last": "50000", "open24h": "49000",
                "bidPx": "49999", "askPx": "50001",
                "vol24h": "1000", "volCcy24h": "50",  # 50 BTC x 50000 = 2.5M USD
                "ts": str(int(__import__("time").time() * 1000)),
            }]
        async def get_open_interests(self, inst_type):
            return [{"instId": "BTC-USDT-SWAP", "oi": "70000"}]
        async def get_funding_rates(self, inst_type):
            return [{"instId": "BTC-USDT-SWAP", "fundingRate": "0.0001"}]
        async def get_candles(self, inst_id, bar, limit):
            return []

    board = OpportunityBoard()
    service = OpportunityScannerService(
        universe=FakeUniverse(),
        okx_client=FakeClient(),
        board=board,
        scanner=FactorScanner(factors=DEFAULT_FACTORS),
        eligibility=EligibilityFilter(),
        candle_limit=120,
    )
    summary = asyncio.run(service.scan_once())
    snap = board.snapshot()
    assert summary["eligible"] == 1, snap["broad_market"]
    assert summary["scanned"] == 1
    assert snap["universe_size"] == 1
    assert summary["market_sets"]["all_market_count"] == 1
    assert summary["market_sets"]["observable_count"] == 1
    assert summary["market_sets"]["analysis_count"] == 1
    assert summary["market_sets"]["executable_count"] == 1
    assert snap["market_sets"]["all_market_count"] == 1


async def test_lease_renews_after_ttl_gap_via_same_owner_recovery(database):
    """§40 regression: a sleep/stall longer than the TTL must not permanently
    lose the lease. Same owner+token+token may recover the expired row; a
    DIFFERENT owner never may (fencing preserved)."""
    from crypto_trader.runtime.lease import LeaseManager

    lm = LeaseManager(database.session_factory)
    lease = await lm.acquire("lease_recovery_key", "owner_a", 10)
    assert lease is not None
    # simulate a wall-clock gap > TTL: expire the row in place
    from sqlalchemy import update as sa_update

    from crypto_trader.persistence.models import RuntimeLeaseORM

    async with database.session_factory() as s:
        await s.execute(
            sa_update(RuntimeLeaseORM)
            .where(RuntimeLeaseORM.lease_key == "lease_recovery_key")
            .values(expires_at=1.0)
        )
        await s.commit()
    # different owner cannot recover
    stolen = await lm.renew(
        "lease_recovery_key", lease.token, 10, owner_id="owner_b",
        fence_generation=lease.fence_generation,
    )
    assert stolen is False
    # same owner recovers
    ok = await lm.renew(
        "lease_recovery_key", lease.token, 10, owner_id="owner_a",
        fence_generation=lease.fence_generation,
    )
    assert ok is True
    held = await lm.is_held("lease_recovery_key", lease.token)
    assert held is True
    await lm.release(
        "lease_recovery_key",
        lease.token,
        owner_id="owner_a",
        fence_generation=lease.fence_generation,
    )
