from datetime import datetime
from decimal import Decimal

from crypto_trader.domain.models import Account
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.runtime.chief_trader_strategy import ChiefTraderStrategyAdapter
from crypto_trader.strategy.base import StrategyContext


class StubProvider:
    name = "stub"

    def __init__(self, response=None, ok=True, healthy=True):
        self.response = response or {
            "action": "NO_TRADE",
            "thesis": "none",
            "decision_id": "d1",
            "model_version": "0",
        }
        self.ok = ok
        self.is_healthy = healthy

    def healthy(self):
        return self.is_healthy

    async def complete_json(self, *, prompt, temperature=0.2, timeout_seconds=30.0, retries=2):
        from crypto_trader.llm_chief.provider import LLMResponse

        if not self.ok:
            return LLMResponse("", self.name, "stub", 0, ok=False, error="STUB_FAIL")
        return LLMResponse(
            str(self.response), self.name, "stub", 0, parsed_json=self.response, ok=True
        )


def make_ctx(symbol="BTCUSDT"):
    book = OrderBook(symbol=symbol, exchange="test")
    book.apply_snapshot(1, [(Decimal("100"), Decimal("1"))], [(Decimal("101"), Decimal("1"))])
    return StrategyContext(
        symbol=symbol,
        book=book,
        account=Account(equity=Decimal("100000")),
        positions={},
        clock_time=datetime(2026, 8, 26),
        mark_price=Decimal("100"),
        funding=Decimal("0.0001"),
        oi=Decimal("1000"),
    )


async def test_llm_no_trade_submits_nothing():
    adapter = ChiefTraderStrategyAdapter(provider=StubProvider())
    signals = await adapter.on_market_data(make_ctx())
    assert signals == []


async def test_llm_long_maps_to_buy_signal():
    adapter = ChiefTraderStrategyAdapter(
        provider=StubProvider(
            {"action": "LONG", "thesis": "trend", "decision_id": "d2", "model_version": "1"}
        )
    )
    signals = await adapter.on_market_data(make_ctx())
    assert len(signals) == 1
    assert signals[0].side.value == "BUY"
    assert signals[0].metadata["decision_id"] == "d2"


async def test_llm_short_maps_to_sell_signal():
    adapter = ChiefTraderStrategyAdapter(
        provider=StubProvider(
            {"action": "SHORT", "thesis": "trend down", "decision_id": "d3", "model_version": "1"}
        )
    )
    signals = await adapter.on_market_data(make_ctx())
    assert len(signals) == 1
    assert signals[0].side.value == "SELL"


async def test_llm_failure_fails_closed():
    adapter = ChiefTraderStrategyAdapter(provider=StubProvider(ok=False))
    signals = await adapter.on_market_data(make_ctx())
    assert signals == []


async def test_unconfigured_llm_gateway_does_not_invoke_live_route():
    adapter = ChiefTraderStrategyAdapter(provider=StubProvider(healthy=False))
    signals = await adapter.on_market_data(make_ctx())
    assert signals == []


async def test_llm_invalid_json_fails_closed():
    adapter = ChiefTraderStrategyAdapter(provider=None)
    signals = await adapter.on_market_data(make_ctx())
    assert signals == []



class CountingProvider(StubProvider):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls = 0
        self.route_ready_flag = True

    def route_ready(self):
        return self.route_ready_flag

    async def complete_json(self, **kwargs):
        self.calls += 1
        return await super().complete_json(**kwargs)


async def test_entry_decisions_are_rate_limited():
    adapter = ChiefTraderStrategyAdapter(
        provider=CountingProvider(), min_decision_interval_seconds=60.0
    )
    first = await adapter.on_market_data(make_ctx())
    second = await adapter.on_market_data(make_ctx())
    third = await adapter.on_market_data(make_ctx())
    assert first == [] and second == [] and third == []   # NO_TRADE; invocation count matters:
    assert adapter.provider.calls == 1                    # only the first tick invokes the LLM
    adapter.min_decision_interval_seconds = 0.0
    await adapter.on_market_data(make_ctx())
    assert adapter.provider.calls == 2                    # interval disabled -> invoked again


async def test_route_not_ready_blocks_invocation():
    provider = CountingProvider()
    provider.route_ready_flag = False
    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0
    )
    signals = await adapter.on_market_data(make_ctx())
    assert signals == []
    assert provider.calls == 0


async def test_every_decision_is_persisted_as_evidence(database):
    """NO_TRADE included: decision chain stays auditable (smoke gate)."""
    from sqlalchemy import select

    from crypto_trader.evolution.persistence_backends import SqlEvidenceBackend
    from crypto_trader.persistence.models import DecisionEvidenceORM

    seen = {}

    class RecordingBackend:
        async def store_decision(self, evidence):
            seen[evidence["decision_id"]] = evidence

    backend = RecordingBackend()
    adapter = ChiefTraderStrategyAdapter(provider=StubProvider(), evidence_backend=backend)
    signals = await adapter.on_market_data(make_ctx())
    assert signals == []
    assert "d1" in seen
    evidence = seen["d1"]
    assert evidence["strategy_id"] == "llm_chief_trader"
    assert evidence["decision"]["action"] == "NO_TRADE"
    assert evidence["analysis_evidence"]["llm_invocation_id"] == ""

    # The real SQL backend accepts the same shape.
    sql_backend = SqlEvidenceBackend(database.session_factory)
    await sql_backend.store_decision(evidence)
    async with database.session_factory() as session:
        row = (
            await session.execute(
                select(DecisionEvidenceORM).where(DecisionEvidenceORM.decision_id == "d1")
            )
        ).scalar_one()
        assert row.symbol == "BTCUSDT"


async def test_sql_evidence_backend_is_idempotent(database):
    from sqlalchemy import func, select

    from crypto_trader.evolution.persistence_backends import SqlEvidenceBackend
    from crypto_trader.persistence.models import DecisionEvidenceORM

    adapter = ChiefTraderStrategyAdapter(provider=StubProvider())
    signals = await adapter.on_market_data(make_ctx())
    assert signals == []
    sql_backend = SqlEvidenceBackend(database.session_factory)
    evidence = {
        "decision_id": "d1",
        "timestamp_utc": "2026-08-28T00:00:00+00:00",
        "symbol": "BTCUSDT",
        "timeframe": "runtime",
        "strategy_id": "llm_chief_trader",
        "strategy_version": "1.1.0",
        "model_version": "0",
        "prompt_version": "chief-prompt-v1",
        "factor_snapshot_id": "",
        "factor_set_version": "factorset-v1",
        "factor_profile": "FULL",
        "market_data_reference": "tick",
        "analysis_evidence": {},
        "decision": {"action": "NO_TRADE"},
        "risk_decision": {},
        "execution_intent_reference": "",
        "created_at_utc": "2026-08-28T00:00:00+00:00",
    }
    await sql_backend.store_decision(evidence)
    await sql_backend.store_decision(evidence)
    async with database.session_factory() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(DecisionEvidenceORM).where(
                    DecisionEvidenceORM.decision_id == "d1"
                )
            )
        ).scalar_one()
    assert count == 1
