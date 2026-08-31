"""P1 CS-20260831-060113 canonical TradePlan entry wiring tests."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace

from crypto_trader.config import Settings
from crypto_trader.domain.enums import MarketType, OrderStatus
from crypto_trader.domain.models import Instrument
from crypto_trader.execution.authority import ExecutionAuthority
from crypto_trader.ledger.service import LedgerService
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.order.manager import OrderManager
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.reconciliation.service import ReconciliationService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.ai_first_chief_trader import AIFirstChiefTraderStrategyAdapter
from crypto_trader.runtime.engine import TradingEngine
from crypto_trader.runtime.lease import LeaseManager
from crypto_trader.runtime.trade_plan import TradePlan, TradePlanStore
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter


def _chief_context(symbol="ETHUSDT"):
    return ChiefTraderContext(
        symbol=symbol,
        market_snapshot={"symbol": symbol, "mark_price": "100"},
        regime="RANGE",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        strategy_evidence={
            "market_regime": "RANGE",
            "strategy_candidates": [
                {"strategy_id": "market_structure", "strategy_version": "0.1.0",
                 "direction": "LONG", "fit_score": 0.1, "raw_confidence": 0.2,
                 "supporting_factors": ["trend"], "contradicting_factors": [],
                 "reason_codes": ["TEST"], "data_health": "OK"}
            ],
        },
        factor_snapshot={"snapshot_id": "snap_test", "factor_set_version": "v1"},
    )


def _decision(action="LONG", decision_id="dec-test"):
    return ChiefTraderDecision(
        decision_id=decision_id, symbol="ETHUSDT", action=action,
        market_regime="RANGE", thesis="AI sees a trade", selected_strategy="market_structure",
        strategy_fit_score=0.1, raw_llm_confidence=0.2, evidence_adjusted_confidence=0.2,
        reason_codes=["AI_DECISION"],
    )


class _DecisionEngine:
    model_version = "test"

    def __init__(self, decision):
        self.decision = decision

    async def decide(self, chief_ctx):
        return self.decision


class _TestAIFirstAdapter(AIFirstChiefTraderStrategyAdapter):
    def __init__(self, chief_ctx, decision, store):
        super().__init__(
            min_strategy_fit=0.45,
            min_trade_confidence=0.55,
            entry_cooldown_seconds=0.0,
            reversal_cooldown_seconds=0.0,
            trade_plan_store=store,
        )
        self.test_context = chief_ctx
        self.engine = _DecisionEngine(decision)
        self.persisted = []
        self.signals = []

    async def _build_context(self, ctx):
        return self.test_context

    async def _persist_evidence(self, decision, ctx, chief_ctx, execution_reference=""):
        self.persisted.append(decision)

    def _map_to_signals(self, decision, ctx, chief_ctx, trade_plan_id=""):
        if decision.action in ("LONG", "SHORT") and not trade_plan_id:
            return []
        if decision.action in ("LONG", "SHORT"):
            self.signals.append(SimpleNamespace(signal_id="sig_test", action=decision.action,
                                                metadata={"trade_plan_id": trade_plan_id}))
            return self.signals[-1:]
        return []


async def _run_decide(adapter, symbol="ETHUSDT"):
    ctx = SimpleNamespace(symbol=symbol, positions={})
    return await adapter._decide(ctx)


async def test_long_creates_durable_plan_and_signal(database):
    store = TradePlanStore(database.session_factory)
    adapter = _TestAIFirstAdapter(_chief_context(), _decision("LONG"), store)
    signals = await _run_decide(adapter)
    assert len(signals) == 1
    plan_id = signals[0].metadata["trade_plan_id"]
    assert plan_id
    plan = await store.get(plan_id)
    assert plan["decision_id"] == "dec-test"
    assert plan["direction"] == "LONG"
    assert plan["status"] == "PLANNED"


async def test_short_creates_durable_plan_and_signal(database):
    store = TradePlanStore(database.session_factory)
    adapter = _TestAIFirstAdapter(_chief_context(), _decision("SHORT"), store)
    signals = await _run_decide(adapter)
    assert len(signals) == 1
    plan_id = signals[0].metadata["trade_plan_id"]
    assert plan_id
    plan = await store.get(plan_id)
    assert plan["direction"] == "SHORT"


async def test_no_trade_does_not_create_plan(database):
    store = TradePlanStore(database.session_factory)
    adapter = _TestAIFirstAdapter(_chief_context(), _decision("NO_TRADE"), store)
    signals = await _run_decide(adapter)
    assert signals == []
    assert await store.list_active() == []


async def test_wait_does_not_create_plan(database):
    store = TradePlanStore(database.session_factory)
    adapter = _TestAIFirstAdapter(_chief_context(), _decision("WAIT"), store)
    signals = await _run_decide(adapter)
    assert signals == []
    assert await store.list_active() == []


async def test_persist_failure_preserves_ai_action_and_blocks_signal(database):
    class FailingStore:
        async def get_by_decision_id(self, decision_id):
            return None

        async def put(self, plan):
            raise RuntimeError("db down")

    adapter = _TestAIFirstAdapter(_chief_context(), _decision("LONG"), FailingStore())
    signals = await _run_decide(adapter)
    assert signals == []
    persisted = adapter.persisted[-1]
    assert persisted.action == "LONG"
    assert persisted.execution_block_reason == "TRADE_PLAN_PERSIST_FAILED"


async def test_decision_retry_reuses_same_plan(database):
    store = TradePlanStore(database.session_factory)
    adapter = _TestAIFirstAdapter(_chief_context(), _decision("LONG"), store)
    signals1 = await _run_decide(adapter)
    signals2 = await _run_decide(adapter)
    plan1 = signals1[0].metadata["trade_plan_id"]
    plan2 = signals2[0].metadata["trade_plan_id"]
    assert plan1 == plan2
    assert await store.get_by_decision_id("dec-test") is not None


async def test_market_type_roundtrip(database):
    store = TradePlanStore(database.session_factory)
    for i, (symbol, expected) in enumerate([("ETHUSDT", "SPOT"), ("BTCUSDT", "PERPETUAL")]):
        adapter = _TestAIFirstAdapter(_chief_context(symbol), _decision("LONG", f"dec-{i}"), store)
        signals = await _run_decide(adapter, symbol=symbol)
        assert len(signals) == 1
        plan_id = signals[0].metadata["trade_plan_id"]
        plan = await store.get(plan_id)
        assert plan["market_type"] == expected
        assert plan["market_type"] in ("SPOT", "PERPETUAL")


def _make_engine_settings(db_url):
    return Settings(
        app_env="test", trading_mode="PAPER", live_trading_enabled=False,
        database_url=db_url, engine_tick_seconds=3600,
        run_lease_ttl_seconds=30, run_lease_renew_interval_seconds=60,
        reconciliation_interval_seconds=3600, market_data_max_age_seconds=60,
        orderbook_max_age_seconds=60,
    )


def _build_engine(db, sim, strategy):
    settings = _make_engine_settings(db.url)
    order_manager = OrderManager(db.session_factory)
    ledger = LedgerService(db.session_factory)
    portfolio = PortfolioService(db.session_factory)
    risk = RiskEngine()
    market_data = MarketDataService()
    leases = LeaseManager(db.session_factory)
    recon = ReconciliationService(db.session_factory)
    return TradingEngine(
        settings=settings, database=db, adapter=sim,
        order_manager=order_manager, ledger=ledger, portfolio=portfolio,
        risk_engine=risk, market_data=market_data, lease_manager=leases,
        reconciliation=recon, strategies=[strategy], authority=ExecutionAuthority(),
    )


class _SpotFullLineageAdapter(AIFirstChiefTraderStrategyAdapter):
    symbol = "ETHUSDT"

    def __init__(self, store):
        super().__init__(
            min_strategy_fit=0.45, min_trade_confidence=0.55,
            entry_cooldown_seconds=0.0, reversal_cooldown_seconds=0.0,
            trade_plan_store=store,
        )
        self.engine = _DecisionEngine(_decision("LONG", "dec-spot"))
        self.persisted = []
        self.test_context = _chief_context("ETHUSDT")

    async def _build_context(self, ctx):
        return self.test_context

    async def _persist_evidence(self, decision, ctx, chief_ctx, execution_reference=""):
        self.persisted.append(decision)

    async def on_market_data(self, ctx):
        return await self._decide(ctx)


async def test_spot_full_lineage_tradeplan_to_fill(database):
    store = TradePlanStore(database.session_factory)
    eth_instrument = Instrument(
        symbol="ETHUSDT", base_asset="ETH", quote_asset="USDT",
        tick_size="0.01", step_size="0.0001", min_qty="0.0001",
        min_notional="5", price_precision=2, quantity_precision=4,
        exchange="SIMULATED",
    )
    sim = SimulatedExchangeAdapter(
        initial_balances={"USDT": Decimal("10000")},
        instruments=[eth_instrument],
    )
    await sim.connect()
    strategy = _SpotFullLineageAdapter(store)
    engine = _build_engine(database, sim, strategy)
    await engine.start()
    await engine.tick()
    assert len(strategy.persisted) >= 1, "strategy did not reach decision persist"
    # find filled order by waiting
    order = None
    for _ in range(1000):
        await asyncio.sleep(0.01)
        orders = await engine.order_manager.list_all()
        if orders:
            order = orders[-1]
            if order.status == OrderStatus.FILLED:
                break
    await engine.wait_for_event_queue()
    assert order is not None and order.status == OrderStatus.FILLED
    # verify fill payload carries trade_plan_id
    from sqlalchemy import select

    from crypto_trader.persistence.models import FillORM
    async with database.session_factory() as session:
        row = (await session.execute(
            select(FillORM).where(FillORM.order_id == order.internal_order_id)
        )).scalars().first()
        assert row is not None, "fill missing"
        payload = row.payload_json or {}
        assert payload.get("trade_plan_id"), "fill payload missing trade_plan_id"
        plan = await store.get(payload["trade_plan_id"])
        assert plan is not None
        assert plan["decision_id"] == "dec-spot"
    await engine.stop()


async def _make_perp_bundle(database):
    from crypto_trader.runtime.bootstrap import build_system

    settings = Settings(
        _env_file=None, app_env="test", trading_mode="PAPER",
        live_trading_enabled=False, database_url=database.url,
        auto_start_runtime=False, paper_mode="PAPER_SYNTHETIC",
        paper_initial_equity="100000", engine_tick_seconds=3600,
        reconciliation_interval_seconds=3600, run_lease_renew_interval_seconds=3600,
    )
    bundle = await build_system(settings)
    await bundle.engine.start()
    return bundle


async def test_perpetual_lineage_tradeplan_to_fill(database):
    from crypto_trader.domain.enums import OrderSide, OrderType, PositionSide
    from crypto_trader.domain.models import SignalIntent
    from crypto_trader.runtime.execution_symbols import reference_symbol_for

    store = TradePlanStore(database.session_factory)
    plan = TradePlan(
        trade_plan_id="plan-perp-1", decision_id="dec-perp", symbol="BTCUSDT",
        execution_symbol="BTCUSDT_PERP", market_type="PERPETUAL",
        direction="LONG", entry_thesis="perp lineage test", status="PLANNED")
    await store.put(plan)

    bundle = await _make_perp_bundle(database)
    await bundle.market_data.ingest_snapshot(
        reference_symbol_for("BTCUSDT_PERP"), 1,
        [(Decimal("100"), Decimal("10"))], [(Decimal("101"), Decimal("10"))])
    signal = SignalIntent(
        signal_id="sig-perp-1", strategy_id="llm_chief_trader",
        symbol="BTCUSDT_PERP", side=OrderSide.BUY, quantity=Decimal("1"),
        order_type=OrderType.MARKET, reason="test", market_type=MarketType.PERPETUAL,
        position_side=PositionSide.LONG, reduce_only=False,
        metadata={"trade_plan_id": "plan-perp-1"},
    )
    decision = await bundle.engine.process_signal(signal)
    assert decision.decision.value == "APPROVE"
    await bundle.engine.wait_for_event_queue()

    from sqlalchemy import select

    from crypto_trader.persistence.models import FillORM
    async with database.session_factory() as session:
        row = (await session.execute(select(FillORM).limit(1))).scalars().first()
        assert row is not None
        payload = row.payload_json or {}
        assert payload.get("trade_plan_id") == "plan-perp-1"
        loaded = await store.get("plan-perp-1")
        assert loaded is not None and loaded["market_type"] == "PERPETUAL"
    await bundle.engine.stop()
    await bundle.database.close()
