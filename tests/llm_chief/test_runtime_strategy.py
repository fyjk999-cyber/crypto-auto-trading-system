from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.models import Account, SignalIntent
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.runtime_strategy import LiveLLMDecisionStrategy
from crypto_trader.market_data.orderbook import OrderBook
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
    def __init__(self, action: str):
        self.action = action
        self.calls = 0

    async def decide(self, ctx):
        self.calls += 1
        return ChiefTraderDecision(
            decision_id="llm_runtime_test",
            symbol=ctx.symbol,
            action=self.action,
            market_regime=ctx.regime,
            thesis="factual LLM thesis" if self.action in {"LONG", "SHORT"} else "",
            position_size_request=0.01 if self.action in {"LONG", "SHORT"} else 0.0,
            leverage_request=2.0 if self.action in {"LONG", "SHORT"} else 0.0,
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

    async def create_entry_signal(self, decision):
        self.calls += 1
        self.events.append(("plan", decision.decision_id))
        signal = SignalIntent(
            signal_id=decision.decision_id,
            strategy_id="live_llm",
            symbol=decision.symbol,
            side=OrderSide.BUY if decision.action == "LONG" else OrderSide.SELL,
            quantity=Decimal(str(decision.position_size_request)),
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
    )

    signals = await strategy.on_market_data(make_ctx())

    assert chief.calls == 1
    assert planner.calls == 1
    assert len(signals) == 1
    assert signals[0].strategy_id == "live_llm"
    assert signals[0].side == OrderSide.BUY
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
        chief = FakeChief(action)
        strategy = LiveLLMDecisionStrategy(
            evidence_engine=FakeEvidenceEngine(),
            chief=chief,
            planner=FakePlanner(events),
            decisions=LLMDecisionStore(database.session_factory),
            audit=FakeAudit(events),
        )
        first = make_ctx()
        await strategy.on_market_data(first)
        await strategy.on_market_data(first)
        assert chief.calls == 1
        resumed = make_ctx()
        resumed.clock_time = first.clock_time + timedelta(seconds=31)
        await strategy.on_market_data(resumed)
        assert chief.calls == 2


async def test_fail_closed_decision_is_throttled(database):
    events = []
    chief = FakeChief("NO_TRADE")
    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        chief=chief,
        planner=FakePlanner(events),
        decisions=LLMDecisionStore(database.session_factory),
        audit=FakeAudit(events),
    )
    first = make_ctx()
    await strategy.on_market_data(first)
    await strategy.on_market_data(first)
    assert chief.calls == 1
