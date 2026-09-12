from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.models import Account, Instrument, SignalIntent
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.runtime_strategy import LiveLLMDecisionStrategy
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.sizing.service import LiveEntrySizingService
from crypto_trader.strategy.base import StrategyContext
from crypto_trader.valuation.domain import ValuationBatch


class FakeEvidenceEngine:
    name = "quant_evidence_only"
    symbol = "BTCUSDT"

    def analyze_evidence(self, _ctx):
        return {
            "regime": {"regime": "BULL"},
            "signals": [{"strategy": "trend", "side": "BUY"}],
            "data_quality": "FACTUAL_ORDERBOOK",
        }


class FakeChief:
    def __init__(
        self,
        action: str,
        size: float = 0.01,
        stop_loss: float | None = None,
        decision_id: str = "llm_runtime_test",
        confidence: float = 0.80,
    ):
        self.action = action
        self.size = size
        self.stop_loss = stop_loss
        self.decision_id = decision_id
        # Conviction drives the risk BUDGET band (never leverage). 0.80 is the
        # neutral 1.00x band, so the risk budget equals base_fraction x equity.
        self.confidence = confidence
        self.calls = 0

    async def decide(self, ctx):
        self.calls += 1
        return ChiefTraderDecision(
            decision_id=self.decision_id,
            symbol=ctx.symbol,
            action=self.action,
            market_regime=ctx.regime,
            thesis="factual LLM thesis" if self.action in {"LONG", "SHORT"} else "",
            position_size_request=self.size if self.action in {"LONG", "SHORT"} else 0.0,
            leverage_request=2.0 if self.action in {"LONG", "SHORT"} else 0.0,
            raw_llm_confidence=self.confidence,
            stop_loss=(
                self.stop_loss
                if self.stop_loss is not None
                else 99.0
                if self.action == "LONG"
                else 102.0
                if self.action == "SHORT"
                else None
            ),
        )


class FakeAudit:
    def __init__(self, events):
        self.events = events

    async def log(self, action, **kwargs):
        self.events.append(("audit", action, kwargs))
        return "audit_1"


class FakePlanner:
    def __init__(self, events):
        self.events = events
        self.calls = 0
        self.last_quantity = None
        self.last_execution_metadata = None

    async def create_entry_signal(self, decision, **kwargs):
        self.calls += 1
        self.last_quantity = kwargs.get("quantity")
        self.last_execution_metadata = kwargs.get("execution_metadata")
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


def make_valuation() -> ValuationBatch:
    """A proven valuation batch: sizing equity is never ledger cash (§28)."""
    return ValuationBatch(
        valuation_id="val-runtime-strategy",
        account_id="default",
        currency="USDT",
        quality="HEALTHY",
        raw_mtm_equity=Decimal("10000"),
        available_margin=Decimal("10000"),
    )


def make_ctx():
    now = datetime.now(UTC)
    book = OrderBook(symbol="BTCUSDT", exchange="OKX")
    # Factual multi-level depth on both sides, best-first. Liquidity V2 caps the
    # quantity on the side the order consumes, so a one-contract book could no
    # longer support a real position (and correctly would not).
    book.apply_snapshot(
        1,
        [(Decimal("100"), Decimal("1000")), (Decimal("99.9"), Decimal("1000"))],
        [(Decimal("101"), Decimal("1000")), (Decimal("101.1"), Decimal("1000"))],
        now=now,
    )
    return StrategyContext(
        symbol="BTCUSDT",
        book=book,
        account=Account(equity=Decimal("10000")),
        positions={},
        clock_time=now,
        run_id="run_1",
        mark_price=Decimal("100.5"),
        realized_volatility=Decimal("0.01"),
        instrument=Instrument(
            symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT", step_size="0.00001"
        ),
        valuation=make_valuation(),
    )


async def test_live_llm_is_only_directional_signal_authority_and_audits_before_plan(database):
    events = []
    chief = FakeChief("LONG")
    planner = FakePlanner(events)
    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        chief=chief,
        planner=planner,
        decisions=LLMDecisionStore(database.session_factory),
        audit=FakeAudit(events),
        sizer=LiveEntrySizingService(),
    )

    signals = await strategy.on_market_data(make_ctx())

    assert chief.calls == 1
    assert planner.calls == 1
    assert len(signals) == 1
    assert signals[0].strategy_id == "live_llm"
    assert signals[0].side == OrderSide.BUY
    # POSITION SIZING V2: the LLM's raw 0.01 is advisory only. The Sizer's
    # deterministic risk budget produces the quantity that reaches the plan,
    # sized at the entry touch (101), not the mid (100.5).
    assert planner.last_quantity == Decimal("25")
    assert planner.last_quantity != Decimal("0.01")
    assert events[0][0:2] == ("audit", "LIVE_LLM_DECISION")
    assert events[1][0:2] == ("audit", "LIVE_LLM_SIZING_AUDIT")
    assert events[2] == ("plan", "llm_runtime_test")
    # The durable decision audit must precede TradePlan creation, and the sizing
    # explanation must be complete and durable: no mystery positions.
    sizing = events[1][2]["after"]
    assert sizing["binding_cap"] == "RISK_BUDGET"
    assert sizing["risk_budget"] == "50.00000"
    assert sizing["equity"] == "10000"
    assert sizing["entry_price"] == "101"
    assert sizing["requested_quantity_from_llm"] == "0.01"
    assert sizing["requested_exposure_from_llm"] == "1.01"
    assert Decimal(sizing["final_qty"]) == planner.last_quantity
    assert sizing["max_loss_estimate"] == "50.00000"
    assert Decimal(sizing["max_loss_estimate"]) <= Decimal(sizing["risk_budget"])
    assert sizing["valuation_id"] == "val-runtime-strategy"
    stored = await LLMDecisionStore(database.session_factory).get("llm_runtime_test")
    assert stored is not None
    assert stored.action == "LONG"
    assert stored.trade_plan_id == "plan_1"


async def test_non_directional_llm_decision_fails_closed_without_tradeplan(database):
    events = []
    chief = FakeChief("NO_TRADE")
    planner = FakePlanner(events)
    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        chief=chief,
        planner=planner,
        decisions=LLMDecisionStore(database.session_factory),
        audit=FakeAudit(events),
        sizer=LiveEntrySizingService(),
    )

    signals = await strategy.on_market_data(make_ctx())

    assert chief.calls == 1
    assert planner.calls == 0
    assert signals == []
    assert events[0][0:2] == ("audit", "LIVE_LLM_DECISION")
    stored = await LLMDecisionStore(database.session_factory).get("llm_runtime_test")
    assert stored is not None
    assert stored.action == "NO_TRADE"


async def test_every_decision_result_uses_the_same_attempt_cooldown(database):
    for action in ("NO_TRADE", "WAIT", "LONG", "SHORT"):
        events = []
        chief = FakeChief(action, decision_id=f"cooldown-{action.lower()}")
        strategy = LiveLLMDecisionStrategy(
            evidence_engine=FakeEvidenceEngine(),
            chief=chief,
            planner=FakePlanner(events),
            decisions=LLMDecisionStore(database.session_factory),
            audit=FakeAudit(events),
            sizer=LiveEntrySizingService(),
        )
        first = make_ctx()
        await strategy.on_market_data(first)
        await strategy.on_market_data(first)
        assert chief.calls == 1
        resumed = make_ctx()
        resumed.clock_time = first.clock_time + timedelta(seconds=31)
        await strategy.on_market_data(resumed)
        assert chief.calls == 2


async def test_cooldown_starts_when_slow_provider_attempt_finishes(database):
    first = make_ctx()
    provider_finished_at = first.clock_time + timedelta(seconds=20)
    chief = FakeChief("NO_TRADE", decision_id="slow-provider-no-trade")
    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        chief=chief,
        planner=FakePlanner([]),
        decisions=LLMDecisionStore(database.session_factory),
        audit=FakeAudit([]),
        sizer=LiveEntrySizingService(),
        attempt_clock=lambda: provider_finished_at,
    )

    await strategy.on_market_data(first)
    inside_completion_cooldown = make_ctx()
    inside_completion_cooldown.clock_time = first.clock_time + timedelta(seconds=31)
    await strategy.on_market_data(inside_completion_cooldown)
    assert chief.calls == 1

    after_completion_cooldown = make_ctx()
    after_completion_cooldown.clock_time = first.clock_time + timedelta(seconds=51)
    await strategy.on_market_data(after_completion_cooldown)
    assert chief.calls == 2


async def test_fail_closed_decision_is_throttled(database):
    events = []
    chief = FakeChief("FAIL_CLOSED")
    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        chief=chief,
        planner=FakePlanner(events),
        decisions=LLMDecisionStore(database.session_factory),
        audit=FakeAudit(events),
        sizer=LiveEntrySizingService(),
    )
    first = make_ctx()
    await strategy.on_market_data(first)
    await strategy.on_market_data(first)
    assert chief.calls == 1
    stored = await LLMDecisionStore(database.session_factory).get("llm_runtime_test")
    assert stored is not None
    assert stored.action == "FAIL_CLOSED"


async def test_live_entry_applies_risk_normalized_size_before_tradeplan(database):
    events = []
    planner = FakePlanner(events)
    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        chief=FakeChief("LONG", size=10),
        planner=planner,
        decisions=LLMDecisionStore(database.session_factory),
        audit=FakeAudit(events),
        sizer=LiveEntrySizingService(risk_fraction=Decimal("0.001")),
    )

    signals = await strategy.on_market_data(make_ctx())

    assert len(signals) == 1
    assert planner.last_quantity == Decimal("5")
    assert signals[0].quantity == Decimal("5")
    assert planner.last_quantity != Decimal("0.001")
    # The LLM asked for 10 units; the deterministic Sizer overrode it.
    assert planner.last_quantity != Decimal("10")


async def test_live_entry_propagates_factual_volatility_to_sizing_and_risk(database):
    events = []
    planner = FakePlanner(events)
    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        chief=FakeChief("LONG", size=10),
        planner=planner,
        decisions=LLMDecisionStore(database.session_factory),
        audit=FakeAudit(events),
        sizer=LiveEntrySizingService(),
    )
    context = make_ctx()
    context.realized_volatility = Decimal("0.10")

    await strategy.on_market_data(context)

    assert planner.last_execution_metadata["volatility"] == "0.10"
    assert planner.last_execution_metadata["liquidity"] == "1000"
    assert planner.last_execution_metadata["sizing_approved_leverage"] == "1"
    assert planner.last_execution_metadata["sizing_version"] == "v2"
    assert planner.last_execution_metadata["llm_size_authority"] == "ADVISORY_ONLY"


async def test_live_entry_rejects_stop_on_the_wrong_side_without_tradeplan(database):
    events = []
    planner = FakePlanner(events)
    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        chief=FakeChief("LONG", stop_loss=102),
        planner=planner,
        decisions=LLMDecisionStore(database.session_factory),
        audit=FakeAudit(events),
        sizer=LiveEntrySizingService(),
    )

    assert await strategy.on_market_data(make_ctx()) == []
    assert planner.calls == 0
    assert any(
        event[0:2] == ("audit", "LIVE_LLM_SIZING_REJECTED")
        and event[2]["after"]["reason_codes"] == ["INVALID_DIRECTIONAL_STOP"]
        for event in events
    )


async def test_entry_on_an_unhealthy_book_is_no_new_risk(database):
    """Liquidity V2: stale levels on an UNHEALTHY book are UNKNOWN depth.

    The levels are still present (mid-price is still computable), so this
    proves the fail-closed path is driven by the book's factual status and not
    merely by a missing best bid/ask.
    """
    from crypto_trader.domain.enums import MarketDataStatus

    events = []
    planner = FakePlanner(events)
    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        chief=FakeChief("LONG"),
        planner=planner,
        decisions=LLMDecisionStore(database.session_factory),
        audit=FakeAudit(events),
        sizer=LiveEntrySizingService(),
    )
    context = make_ctx()
    assert context.book.mid_price() is not None
    context.book.status = MarketDataStatus.UNHEALTHY

    assert await strategy.on_market_data(context) == []
    assert planner.calls == 0
    assert any(
        event[0:2] == ("audit", "LIVE_LLM_SIZING_REJECTED")
        and event[2]["after"]["reason_codes"] == ["LIQUIDITY_UNKNOWN"]
        and event[2]["after"]["depth_side"] == "ASK"
        for event in events
    )


async def test_short_entry_caps_on_bid_depth_not_ask_depth(database):
    """A SHORT consumes bids; asymmetric factual depth must be respected."""
    events = []
    planner = FakePlanner(events)
    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        # A 0.1% stop: the risk budget alone would allow far more than the thin
        # bid side can actually absorb, so LIQUIDITY becomes the binding cap.
        chief=FakeChief("SHORT", stop_loss=100.6),
        planner=planner,
        decisions=LLMDecisionStore(database.session_factory),
        audit=FakeAudit(events),
        sizer=LiveEntrySizingService(),
    )
    context = make_ctx()
    # Thin bids, deep asks: a SHORT must be limited by the THIN bid side.
    context.book.apply_snapshot(
        2,
        [(Decimal("100"), Decimal("400"))],
        [(Decimal("101"), Decimal("100000"))],
    )

    signals = await strategy.on_market_data(context)

    assert len(signals) == 1
    assert signals[0].side == OrderSide.SELL
    sizing = next(
        event[2]["after"]
        for event in events
        if event[0:2] == ("audit", "LIVE_LLM_SIZING_AUDIT")
    )
    # 400 bids x 15% participation = 60, below the risk budget (83.33) and the
    # margin cap (200), so LIQUIDITY is what binds.
    # Compared numerically: Decimal string form varies with the lot exponent.
    assert Decimal(sizing["liquidity_depth"]) == Decimal("400")
    assert Decimal(sizing["liquidity_cap_qty"]) == Decimal("60")
    assert sizing["binding_cap"] == "LIQUIDITY"
    assert Decimal(sizing["final_qty"]) == Decimal("60")
    assert Decimal(sizing["risk_qty"]) > Decimal("60")
    # Had the deep ASK side been used by mistake, the cap would have been 15,000.
    assert Decimal(sizing["liquidity_cap_qty"]) != Decimal("15000")


async def test_the_sizer_metadata_contract_is_accepted_by_the_risk_engine(database):
    """End-to-end §33/§34: what the Sizer emits, RiskEngine re-verifies.

    The Sizer's execution_metadata is fed into the RiskEngine exactly as the
    real runtime does, proving the two authorities agree and that RiskEngine
    independently accepts a well-formed V2 claim.
    """
    from crypto_trader.domain.enums import ExecutionDecision
    from crypto_trader.risk.engine import RiskEngine

    events = []
    planner = FakePlanner(events)
    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        chief=FakeChief("LONG"),
        planner=planner,
        decisions=LLMDecisionStore(database.session_factory),
        audit=FakeAudit(events),
        sizer=LiveEntrySizingService(),
    )

    signals = await strategy.on_market_data(make_ctx())
    assert len(signals) == 1
    intent = signals[0].model_copy(update={"metadata": planner.last_execution_metadata})

    risk = RiskEngine()
    decision = risk.check(
        intent,
        account=Account(equity=Decimal("10000")),
        positions={},
        market_price=Decimal("100.5"),
        open_order_count=0,
        drawdown=Decimal("0"),
        current_equity=Decimal("10000"),
        peak_equity=Decimal("10000"),
        valuation_id="val-runtime-strategy",
        valuation_quality="HEALTHY",
        risk_equity=Decimal("10000"),
        available_margin=Decimal("10000"),
    )

    assert decision.decision == ExecutionDecision.APPROVE
    assert decision.checks["sizing_version"] == "v2"
    assert decision.checks["sizing_llm_authority"] == "ADVISORY_ONLY"
    assert decision.checks["sizing_risk_budget_verified"] == "50.00000"
    # RiskEngine independently confirmed the Sizer's approved leverage.
    assert Decimal(decision.checks["approved_leverage"]) <= Decimal("5")
