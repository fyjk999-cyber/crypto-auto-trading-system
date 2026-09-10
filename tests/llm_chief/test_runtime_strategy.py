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
    ):
        self.action = action
        self.size = size
        self.stop_loss = stop_loss
        self.decision_id = decision_id
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


def make_ctx():
    now = datetime.now(UTC)
    book = OrderBook(symbol="BTCUSDT", exchange="OKX")
    book.apply_snapshot(
        1,
        [(Decimal("100"), Decimal("1"))],
        [(Decimal("101"), Decimal("1"))],
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
    assert planner.last_quantity == Decimal("0.01")
    assert events[0][0:2] == ("audit", "LIVE_LLM_DECISION")
    assert events[1] == ("plan", "llm_runtime_test")
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
    assert planner.last_quantity == Decimal("6.66666")
    assert signals[0].quantity == Decimal("6.66666")
    assert planner.last_quantity != Decimal("0.001")


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
    assert planner.last_execution_metadata["liquidity"] == "1"
    assert planner.last_execution_metadata["sizing_approved_leverage"] == "1"


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
