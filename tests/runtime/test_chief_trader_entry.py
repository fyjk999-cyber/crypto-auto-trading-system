import json
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
        ),
        decision_context_provider=StaticContextProvider(),
    )
    signals = await adapter.on_market_data(make_ctx())
    assert len(signals) == 1
    assert signals[0].side.value == "BUY"
    assert signals[0].metadata["decision_id"] == "d2"


async def test_llm_short_maps_to_sell_signal():
    adapter = ChiefTraderStrategyAdapter(
        provider=StubProvider(
            {"action": "SHORT", "thesis": "trend down", "decision_id": "d3", "model_version": "1"}
        ),
        decision_context_provider=StaticContextProvider(),
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
        provider=CountingProvider(), min_decision_interval_seconds=60.0,
        decision_context_provider=StaticContextProvider(),
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
    adapter = ChiefTraderStrategyAdapter(
        provider=StubProvider(), evidence_backend=backend,
        decision_context_provider=StaticContextProvider(),
    )
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


class ScriptedProvider:
    """Returns a full new-schema structured response; records invocations."""

    name = "scripted"

    def __init__(self, response):
        self.response = response
        self.calls = 0
        self.is_healthy = True
        self.route_ready_flag = True

    def healthy(self):
        return self.is_healthy

    def route_ready(self):
        return self.route_ready_flag

    async def complete_json(self, *, prompt, temperature=0.2, timeout_seconds=30.0,
                            retries=2):
        self.calls += 1
        from crypto_trader.llm_chief.provider import LLMResponse

        return LLMResponse(
            str(self.response), self.name, "scripted", 0,
            parsed_json=self.response, ok=True,
        )


def _long_response(**overrides):
    response = {
        "decision_id": "dec_llm_1",
        "symbol": "BTCUSDT",
        "action": "LONG",
        "market_regime": "BULL",
        "selected_strategy": "trend_following",
        "strategy_fit_score": 0.81,
        "supporting_factors": ["trend", "momentum"],
        "contradicting_factors": ["funding_rate"],
        "dominant_factor": "trend",
        "thesis": "trend dominant, funding crowded",
        "raw_llm_confidence": 0.78,
        "evidence_adjusted_confidence": 0.69,
        "reason_codes": ["TREND_DOMINANT", "FUNDING_CROWDING_RISK"],
    }
    response.update(overrides)
    return response


class StaticContextProvider:
    """Supplies a fixed StrategyEvidencePackage-shaped context."""

    def __init__(self, evidence=None, factor_snapshot=None):
        self.evidence = evidence if evidence is not None else {
            "market_regime": "BULL",
            "strategy_candidates": [
                {"strategy_id": "trend_following", "strategy_version": "0.1.0",
                 "direction": "LONG", "fit_score": 0.81, "raw_confidence": 0.78,
                 "supporting_factors": ["trend"], "contradicting_factors": ["funding_rate"],
                 "reason_codes": ["EMA_BULL"], "data_health": "OK"},
                {"strategy_id": "mean_reversion", "strategy_version": "0.1.0",
                 "direction": "SHORT", "fit_score": 0.31, "raw_confidence": 0.31,
                 "supporting_factors": [], "contradicting_factors": [],
                 "reason_codes": [], "data_health": "OK"},
            ],
            "dominant_factors": ["trend"],
            "risk_flags": ["FUNDING_CROWDED_LONGS"],
        }
        self.factor_snapshot = factor_snapshot if factor_snapshot is not None else {
            "snapshot_id": "fsnap_test_1",
            "factor_set_version": "factorset-v2",
        }

    async def build(self, market_data):
        from crypto_trader.runtime.live_decision_context import LiveDecisionBundle

        return LiveDecisionBundle(
            factor_snapshot_id=self.factor_snapshot["snapshot_id"],
            factor_set_version=self.factor_snapshot["factor_set_version"],
            factor_snapshot=self.factor_snapshot,
            evidence=self.evidence,
        )


async def test_scenario_A_trend_long_with_contradiction_trades():
    """Trend LONG + funding contradiction -> BUY still reaches RiskEngine."""
    provider = ScriptedProvider(_long_response())
    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(),
    )
    signals = await adapter.on_market_data(make_ctx())
    assert len(signals) == 1
    assert signals[0].side.value == "BUY"  # contradiction did NOT veto
    metadata = signals[0].metadata
    assert metadata["selected_strategy"] == "trend_following"
    assert metadata["factor_snapshot_id"] == "fsnap_test_1"


async def test_scenario_G_wait_produces_no_order():
    provider = ScriptedProvider(_long_response(action="WAIT"))
    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(),
    )
    assert await adapter.on_market_data(make_ctx()) == []
    assert provider.calls == 1


async def test_scenario_H_unknown_action_fails_closed():
    provider = ScriptedProvider(_long_response(action="MOON"))
    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(),
    )
    assert await adapter.on_market_data(make_ctx()) == []


async def test_position_management_actions_produce_no_entry():
    for action in ("ADD", "REDUCE", "EXIT"):
        provider = ScriptedProvider(_long_response(action=action))
        adapter = ChiefTraderStrategyAdapter(
            provider=provider, min_decision_interval_seconds=0.0,
            decision_context_provider=StaticContextProvider(),
        )
        assert await adapter.on_market_data(make_ctx()) == [], action


async def test_scenario_E_all_weak_fit_blocks_before_llm():
    evidence = {
        "market_regime": "RANGE",
        "strategy_candidates": [
            {"strategy_id": "trend_following", "strategy_version": "0.1.0",
             "direction": "NO_TRADE", "fit_score": 0.0, "raw_confidence": 0.0,
             "supporting_factors": [], "contradicting_factors": [],
             "reason_codes": ["EMA_FLAT"], "data_health": "OK"},
            {"strategy_id": "momentum", "strategy_version": "0.1.0",
             "direction": "LONG", "fit_score": 0.41, "raw_confidence": 0.41,
             "supporting_factors": ["momentum"], "contradicting_factors": [],
             "reason_codes": [], "data_health": "OK"},
        ],
        "dominant_factors": [],
        "risk_flags": [],
    }
    provider = ScriptedProvider(_long_response())
    recorded = {}

    class Backend:
        async def store_decision(self, evidence_row):
            recorded.update(evidence_row)

    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(evidence=evidence),
        evidence_backend=Backend(),
    )
    assert await adapter.on_market_data(make_ctx()) == []
    assert provider.calls == 0  # LLM not invoked: deterministic gate
    assert recorded["decision"]["action"] == "NO_TRADE"
    assert "INSUFFICIENT_STRATEGY_EDGE" in recorded["decision"]["reason_codes"]
    assert recorded["factor_snapshot_id"] == "fsnap_test_1"
    assert recorded["factor_set_version"] == "factorset-v2"


async def test_low_evidence_adjusted_confidence_fails_closed():
    provider = ScriptedProvider(_long_response(evidence_adjusted_confidence=0.40))
    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(),
        min_trade_confidence=0.55,
    )
    signals = await adapter.on_market_data(make_ctx())
    assert signals == []


async def test_context_provider_failure_fails_closed():
    """§2: real FactorSnapshot unavailable -> NO_TRADE, LLM NOT invoked."""
    class BrokenProvider:
        async def build(self, market_data):
            raise RuntimeError("candles unavailable")

    provider = ScriptedProvider(_long_response())
    recorded = {}

    class Backend:
        async def store_decision(self, evidence_row):
            recorded.update(evidence_row)

    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=BrokenProvider(),
        evidence_backend=Backend(),
    )
    signals = await adapter.on_market_data(make_ctx())
    assert signals == []
    assert provider.calls == 0  # LLM NOT invoked without real context
    assert recorded["decision"]["action"] == "NO_TRADE"
    assert "FACTOR_CONTEXT_UNAVAILABLE" in recorded["decision"]["reason_codes"]


async def test_missing_factor_snapshot_blocks_entry_before_llm():
    """§2: context provider returns None (insufficient history) -> fail closed."""
    class NoneProvider:
        async def build(self, market_data):
            return None

    provider = ScriptedProvider(_long_response())
    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=NoneProvider(),
    )
    assert await adapter.on_market_data(make_ctx()) == []
    assert provider.calls == 0


async def test_missing_strategy_evidence_blocks_entry():
    """§2: snapshot present but no strategy candidates -> no entry, no LLM."""
    provider = ScriptedProvider(_long_response())
    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(evidence={}),
    )
    signals = await adapter.on_market_data(make_ctx())
    assert signals == []
    assert provider.calls == 0


async def test_unwired_context_provider_blocks_entry():
    """§2: without a wired context provider there is NO real factor context."""
    provider = ScriptedProvider(_long_response())
    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
    )
    assert await adapter.on_market_data(make_ctx()) == []
    assert provider.calls == 0


async def test_evidence_persistence_failure_is_instrumented(caplog):
    class FailingBackend:
        async def store_decision(self, evidence):
            raise RuntimeError("db down")

    provider = ScriptedProvider(_long_response())
    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(),
        evidence_backend=FailingBackend(),
    )
    import logging as _logging

    with caplog.at_level(_logging.WARNING, logger="crypto_trader.chief_trader"):
        signals = await adapter.on_market_data(make_ctx())
    assert len(signals) == 1  # trading NOT blocked by evidence failure
    assert adapter.evidence_persist_failures == 1
    assert any("DECISION_EVIDENCE_PERSIST_FAILED" in r.message for r in caplog.records)


async def test_short_and_buy_sell_mapping_exhaustive():
    provider = ScriptedProvider(_long_response(action="SHORT"))
    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(),
    )
    signals = await adapter.on_market_data(make_ctx())
    assert signals[0].side.value == "SELL"
    # OPEN_LONG alias maps to BUY.
    provider2 = ScriptedProvider(_long_response(action="OPEN_LONG"))
    adapter2 = ChiefTraderStrategyAdapter(
        provider=provider2, min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(),
    )
    signals2 = await adapter2.on_market_data(make_ctx())
    assert signals2[0].side.value == "BUY"


# ---------------------------------------------------------------------------
# PAPER EXPLORATION MODE (STAGE A) - §31 test contract
# ---------------------------------------------------------------------------

def make_signal(qty="1"):
    from crypto_trader.domain.enums import OrderSide
    from crypto_trader.domain.models import SignalIntent as _SignalIntent

    return _SignalIntent(
        signal_id="sig_1",
        strategy_id="test",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=qty,
        limit_price="100",
    )


def make_account(equity="10000"):
    from crypto_trader.domain.models import Account as _Account

    return _Account(equity=Decimal(equity))


def _exploration_adapter(provider, backend=None, sampler=lambda: 0.0, **overrides):
    params = dict(
        provider=provider,
        min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(),
        exploration_mode=True,
        exploration_min_fit=0.40,
        exploration_min_confidence=0.45,
        exploration_probability=0.30,
        exploration_borderline_fit=0.50,
        exploration_size_fraction=0.5,
        normal_fit_threshold=0.55,
        normal_confidence_threshold=0.55,
        entry_cooldown_seconds=240.0,
        exploration_sampler=sampler,
        evidence_backend=backend,
    )
    params.update(overrides)
    return ChiefTraderStrategyAdapter(**params)


def _mid_response(**overrides):
    """Plausible-but-borderline opportunity: fit 0.42 / confidence 0.49."""
    response = _long_response()
    response.update(
        {
            "strategy_fit_score": 0.42,
            "raw_llm_confidence": 0.55,
            "evidence_adjusted_confidence": 0.49,
        }
    )
    response.update(overrides)
    return response


def _fit_evidence(fit: float, direction: str = "LONG") -> dict:
    """Evidence package with a single candidate at the given fit."""
    return {
        "market_regime": "BULL" if direction == "LONG" else "BEAR",
        "strategy_candidates": [
            {"strategy_id": "trend_following", "strategy_version": "0.1.0",
             "direction": direction, "fit_score": fit, "raw_confidence": fit,
             "supporting_factors": ["trend"], "contradicting_factors": [],
             "reason_codes": [], "data_health": "OK"},
        ],
        "dominant_factors": ["trend"], "risk_flags": [],
    }


async def test_exploration_fit_042_conf_050_trades_small():
    """§11: fit=0.42 + confidence=0.49 CAN become an exploration trade."""
    provider = ScriptedProvider(_mid_response())
    adapter = _exploration_adapter(
        provider,
        decision_context_provider=StaticContextProvider(evidence=_fit_evidence(0.42)),
    )
    signals = await adapter.on_market_data(make_ctx())
    assert len(signals) == 1
    metadata = signals[0].metadata
    assert metadata["decision_class"] == "EXPLORATION_ENTRY"
    # §5: exploration size is a bounded fraction of the normal PAPER size.
    assert Decimal(signals[0].quantity) == Decimal("0.0005")


async def test_exploration_fit_052_above_borderline_unsampled():
    """fit 0.50-0.55 (above borderline band, below NORMAL) always explores."""
    provider = ScriptedProvider(
        _mid_response(strategy_fit_score=0.52, evidence_adjusted_confidence=0.52)
    )
    adapter = _exploration_adapter(
        provider,
        sampler=lambda: 0.99,  # would skip if borderline sampling applied
        decision_context_provider=StaticContextProvider(evidence=_fit_evidence(0.52)),
    )
    signals = await adapter.on_market_data(make_ctx())
    assert len(signals) == 1
    assert signals[0].metadata["decision_class"] == "EXPLORATION_ENTRY"


async def test_normal_entry_keeps_full_size_and_class():
    """fit 0.81 / conf 0.69 clears the NORMAL band: full size, tagged NORMAL."""
    provider = ScriptedProvider(_long_response())
    adapter = _exploration_adapter(provider)
    signals = await adapter.on_market_data(make_ctx())
    assert len(signals) == 1
    assert signals[0].metadata["decision_class"] == "NORMAL_ENTRY"
    assert Decimal(signals[0].quantity) == Decimal("0.001")


async def test_exploration_borderline_skipped_records_counterfactual(database):
    """fit 0.38-0.50 not sampled -> persisted EXPLORATION_SKIPPED."""
    from sqlalchemy import select

    from crypto_trader.evolution.persistence_backends import SqlEvidenceBackend
    from crypto_trader.persistence.models import DecisionEvidenceORM

    provider = ScriptedProvider(_mid_response())
    backend = SqlEvidenceBackend(database.session_factory)
    adapter = _exploration_adapter(
        provider, backend=backend, sampler=lambda: 0.99,
        decision_context_provider=StaticContextProvider(evidence=_fit_evidence(0.42)),
    )
    signals = await adapter.on_market_data(make_ctx())
    assert signals == []
    assert provider.calls == 0  # sampled out BEFORE the LLM call
    async with database.session_factory() as session:
        row = (
            await session.execute(
                select(DecisionEvidenceORM)
                .where(DecisionEvidenceORM.strategy_id == "llm_chief_trader")
                .order_by(DecisionEvidenceORM.timestamp_utc.desc())
                .limit(1)
            )
        ).scalar_one()
    assert row.decision_json["action"] == "NO_TRADE"
    assert "EXPLORATION_SKIPPED" in row.decision_json["reason_codes"]
    analysis = row.analysis_evidence_json
    if isinstance(analysis, str):
        analysis = json.loads(analysis)
    assert analysis["exploration_mode"] is True
    assert analysis["decision_class"] == "NO_TRADE"


async def test_exploration_confidence_gate_blocks():
    """conf 0.40 < exploration minimum 0.45 -> fail closed, no order."""
    provider = ScriptedProvider(
        _mid_response(evidence_adjusted_confidence=0.40)
    )
    adapter = _exploration_adapter(
        provider,
        decision_context_provider=StaticContextProvider(evidence=_fit_evidence(0.42)),
    )
    assert await adapter.on_market_data(make_ctx()) == []


async def test_exploration_weak_fit_still_blocked():
    """fit 0.25 is below even the exploration minimum -> no trade."""
    provider = ScriptedProvider(_mid_response(strategy_fit_score=0.25))
    adapter = _exploration_adapter(
        provider,
        decision_context_provider=StaticContextProvider(evidence=_fit_evidence(0.25)),
    )
    assert await adapter.on_market_data(make_ctx()) == []
    assert provider.calls == 0  # deterministic gate, no LLM spend


async def test_entry_cooldown_blocks_immediate_reentry():
    """§13: a second NEW entry inside the cooldown is recorded, not traded."""
    provider = ScriptedProvider(_long_response())
    adapter = _exploration_adapter(provider)
    first = await adapter.on_market_data(make_ctx())
    assert len(first) == 1
    second = await adapter.on_market_data(make_ctx())
    assert second == []
    assert provider.calls == 1  # cooldown checked before the LLM


async def test_active_position_blocks_new_entry():
    """§14: one open position -> no repeated entries for data collection."""
    from crypto_trader.domain.models import Position

    provider = ScriptedProvider(_long_response())
    adapter = _exploration_adapter(provider)
    ctx = make_ctx()
    ctx.positions["BTCUSDT"] = Position(
        symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
        quantity=Decimal("0.001"),
    )
    signals = await adapter.on_market_data(ctx)
    assert signals == []
    assert provider.calls == 0  # no LLM spend while a position is open


async def test_exploration_never_activates_in_live_mode():
    """§30 hard lock: exploration config is REFUSED outside safe PAPER."""
    import pytest
    from pydantic import ValidationError

    from crypto_trader.config import Settings

    with pytest.raises(ValidationError):
        Settings(
            trading_mode="LIVE", live_trading_enabled=True,
            paper_exploration_mode=True, app_env="test",
        )
    with pytest.raises(ValidationError):
        Settings(
            trading_mode="PAPER", real_money_enabled=True,
            paper_exploration_mode=True, app_env="test",
        )
    safe = Settings(
        trading_mode="PAPER", paper_exploration_mode=True, app_env="test"
    )
    assert safe.exploration_mode_active is True
    off = Settings(
        trading_mode="PAPER", paper_exploration_mode=False, app_env="test"
    )
    assert off.exploration_mode_active is False


# ---------------------------------------------------------------------------
# Memory -> Live wiring (§1): RelevantMemory as bounded soft evidence
# ---------------------------------------------------------------------------

async def test_memory_retrieval_feeds_live_context(database):
    """Confirmed lessons + episodes are retrievable and recorded as refs."""

    from crypto_trader.llm_chief.memory_retrieval import LiveMemoryProvider
    from crypto_trader.persistence.models import (
        AITradeEpisodeORM,
        LessonORM,
    )

    async with database.session_factory() as session:
        session.add(
            LessonORM(
                lesson_id="lesson_test_1",
                scope="GLOBAL",
                type="STRATEGY_FIT",
                canonical_statement="Trend LONG with crowded funding rarely extends.",
                recommended_action="reduce confidence",
                confidence=0.7,
                status="CONFIRMED",
                first_seen="2026-08-28T00:00:00+00:00",
                last_seen="2026-08-28T00:00:00+00:00",
            )
        )
        session.add(
            AITradeEpisodeORM(
                episode_id="episode_test_1",
                symbol="BTCUSDT",
                market_regime="BULL",
                strategy_selected="trend_following",
                result="WIN",
                pnl="12.5",
                holding_time_seconds=3600.0,
            )
        )
        await session.commit()

    memory = LiveMemoryProvider(database.session_factory)
    snapshot = await memory.retrieve(regime="BULL", symbol="BTCUSDT")
    assert "lesson_test_1" in snapshot["memory_refs"]
    assert "episode_test_1" in snapshot["memory_refs"]
    assert snapshot["knowledge"][0]["statement"].startswith("Trend LONG")
    assert snapshot["similar_episodes"][0]["result"] == "WIN"

    # Live adapter consumes the memory and records the refs with the decision.
    provider = ScriptedProvider(_long_response())
    seen = {}

    class Backend:
        async def store_decision(self, evidence_row):
            seen.update(evidence_row)

    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(),
        memory_provider=memory, evidence_backend=Backend(),
    )
    signals = await adapter.on_market_data(make_ctx())
    assert len(signals) == 1
    assert seen["analysis_evidence"]["memory_refs"]
    assert "lesson_test_1" in seen["analysis_evidence"]["memory_refs"]
    assert adapter._last_memory["knowledge"]


async def test_memory_retrieval_failure_is_non_blocking(caplog):
    """Memory is soft evidence: retrieval failure never blocks trading."""
    import logging as _logging

    class BrokenMemory:
        async def retrieve(self, regime, symbol):
            raise RuntimeError("memory store down")

    provider = ScriptedProvider(_long_response())
    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(),
        memory_provider=BrokenMemory(),
    )
    with caplog.at_level(_logging.WARNING, logger="crypto_trader.chief_trader"):
        signals = await adapter.on_market_data(make_ctx())
    assert len(signals) == 1  # trading NOT blocked
    assert any("LIVE_MEMORY_RETRIEVAL_FAILED" in r.message for r in caplog.records)


async def test_no_historical_memory_live_operates_empty():
    """Section 7B: no memory rows -> empty RelevantMemory, decision still works."""
    provider = ScriptedProvider(_long_response())
    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(),
        memory_provider=None,
    )

    class EmptyMemory:
        async def retrieve(self, regime, symbol):
            return {
                "memory_refs": [], "knowledge": [], "patterns": [],
                "similar_episodes": [], "compressed_experience": [],
            }

    adapter.memory_provider = EmptyMemory()
    signals = await adapter.on_market_data(make_ctx())
    assert len(signals) == 1  # empty memory never blocks a valid decision
    assert adapter._last_memory["memory_refs"] == []


async def test_unknown_regime_with_context_failure_blocks_entry():
    """Section 7E: MarketRegime UNKNOWN from context failure -> no entry, no LLM."""
    provider = ScriptedProvider(_long_response())
    evidence = {
        "market_regime": "UNKNOWN",
        "strategy_candidates": [
            {"strategy_id": "trend_following", "strategy_version": "0.1.0",
             "direction": "LONG", "fit_score": 0.60, "raw_confidence": 0.60,
             "supporting_factors": [], "contradicting_factors": [],
             "reason_codes": [], "data_health": "OK"},
        ],
        "dominant_factors": [], "risk_flags": [],
    }
    recorded = {}

    class Backend:
        async def store_decision(self, evidence_row):
            recorded.update(evidence_row)

    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(evidence=evidence),
        evidence_backend=Backend(),
    )
    signals = await adapter.on_market_data(make_ctx())
    assert signals == []
    assert provider.calls == 0
    assert recorded["decision"]["action"] == "NO_TRADE"
    assert "MARKET_CONTEXT_UNAVAILABLE" in recorded["decision"]["reason_codes"]


async def test_missing_strategy_evidence_persists_no_trade(database):
    """Section 7D: candidates unavailable -> NO_TRADE persisted, LLM not called."""
    from sqlalchemy import select

    from crypto_trader.evolution.persistence_backends import SqlEvidenceBackend
    from crypto_trader.persistence.models import DecisionEvidenceORM

    provider = ScriptedProvider(_long_response())
    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(evidence={}),
        evidence_backend=SqlEvidenceBackend(database.session_factory),
    )
    assert await adapter.on_market_data(make_ctx()) == []
    assert provider.calls == 0
    async with database.session_factory() as session:
        row = (
            await session.execute(
                select(DecisionEvidenceORM)
                .where(DecisionEvidenceORM.strategy_id == "llm_chief_trader")
                .order_by(DecisionEvidenceORM.timestamp_utc.desc())
                .limit(1)
            )
        ).scalar_one()
    assert row.decision_json["action"] == "NO_TRADE"
    assert "STRATEGY_EVIDENCE_UNAVAILABLE" in row.decision_json["reason_codes"]


async def test_bridge_time_stop_exit_remains_operational():
    """Section 7G: position safety (EXIT) works even when factor context fails."""
    from crypto_trader.runtime.ai_position_bridge import (
        AIPositionEvaluation,
        AIPositionRuntimeBridge,
    )

    class FakeEngine:
        def __init__(self):
            self.market_data = None
            self.submitted = []

        async def process_signal(self, signal):
            self.submitted.append(signal)

    engine = FakeEngine()
    bridge = AIPositionRuntimeBridge(time_stop_seconds=0.0)
    evaluations: list[AIPositionEvaluation] = []
    await bridge._evaluate_one(
        engine,
        evaluations,
        symbol="BTCUSDT",
        market_type="PERPETUAL",
        side="LONG",
        abs_quantity=0.001,
        entry_price=100.0,
        realized_pnl=0.0,
    )
    assert evaluations[0].action == "EXIT"
    assert evaluations[0].reduce_only is True
    assert len(engine.submitted) == 1
    assert engine.submitted[0].reduce_only is True


def test_invalid_learning_sample_filter():
    """Section 7H: executed trade missing lineage never counts as a valid sample."""
    from crypto_trader.runtime.exploration_analytics import (
        is_valid_learning_sample,
    )

    valid = {
        "factor_snapshot_id": "fsnap_1",
        "factor_set_version": "factorset-v1",
        "market_regime": "RANGE",
        "selected_strategy": "mean_reversion",
        "strategy_fit_score": 0.42,
        "decision_class": "EXPLORATION_ENTRY",
    }
    assert is_valid_learning_sample(valid) is True
    for key, bad_value in (
        ("factor_snapshot_id", ""),
        ("factor_set_version", ""),
        ("market_regime", "UNKNOWN"),
        ("selected_strategy", ""),
        ("strategy_fit_score", None),
        ("decision_class", ""),
    ):
        invalid = dict(valid)
        invalid[key] = bad_value
        assert is_valid_learning_sample(invalid) is False, key
    assert is_valid_learning_sample(None) is False


# ---------------------------------------------------------------------------
# CORE_TRADING_DOCTRINE_V1 regression contract (§14)
# ---------------------------------------------------------------------------

async def test_doctrine_A_single_strong_strategy_suffices():
    """One strong strategy + weak others -> trade still occurs (no unanimity)."""
    evidence = {
        "market_regime": "BULL",
        "strategy_candidates": [
            {"strategy_id": "trend_following", "strategy_version": "0.1.0",
             "direction": "LONG", "fit_score": 0.72, "raw_confidence": 0.7,
             "supporting_factors": ["trend"], "contradicting_factors": [],
             "reason_codes": [], "data_health": "OK"},
            {"strategy_id": "momentum", "strategy_version": "0.1.0",
             "direction": "NO_TRADE", "fit_score": 0.0, "raw_confidence": 0.0,
             "supporting_factors": [], "contradicting_factors": [],
             "reason_codes": [], "data_health": "OK"},
            {"strategy_id": "breakout", "strategy_version": "0.1.0",
             "direction": "NO_TRADE", "fit_score": 0.0, "raw_confidence": 0.0,
             "supporting_factors": [], "contradicting_factors": [],
             "reason_codes": [], "data_health": "OK"},
        ],
        "dominant_factors": ["trend"], "risk_flags": [],
    }
    provider = ScriptedProvider(_long_response(strategy_fit_score=0.72))
    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(evidence=evidence),
    )
    signals = await adapter.on_market_data(make_ctx())
    assert len(signals) == 1


async def test_doctrine_D_raw_factor_without_strategy_interpretation_no_trade():
    """A strong factor alone NEVER creates an order: no valid interpreter."""
    evidence = {
        "market_regime": "RANGE",
        "strategy_candidates": [
            {"strategy_id": "trend_following", "strategy_version": "0.1.0",
             "direction": "NO_TRADE", "fit_score": 0.0, "raw_confidence": 0.0,
             "supporting_factors": ["volume"], "contradicting_factors": [],
             "reason_codes": ["EMA_FLAT"], "data_health": "OK"},
            {"strategy_id": "momentum", "strategy_version": "0.1.0",
             "direction": "NO_TRADE", "fit_score": 0.0, "raw_confidence": 0.0,
             "supporting_factors": ["volume"], "contradicting_factors": [],
             "reason_codes": [], "data_health": "OK"},
        ],
        "dominant_factors": ["volume"],
        "risk_flags": [],
    }
    provider = ScriptedProvider(_long_response())
    adapter = ChiefTraderStrategyAdapter(
        provider=provider, min_decision_interval_seconds=0.0,
        decision_context_provider=StaticContextProvider(evidence=evidence),
    )
    signals = await adapter.on_market_data(make_ctx())
    assert signals == []
    assert provider.calls == 0


def test_doctrine_E_risk_engine_rejection_blocks_execution():
    """LLM proposal + RiskEngine REJECT -> no execution path exists."""
    from crypto_trader.domain.enums import ExecutionDecision
    from crypto_trader.risk.engine import RiskConfig, RiskEngine

    config = RiskConfig(max_position_notional=Decimal("50"))
    engine = RiskEngine(config)
    decision = engine.check(
        make_signal(qty="10"),
        account=make_account(),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
    )
    assert decision.decision == ExecutionDecision.REJECT


def test_doctrine_F_risk_engine_approval_allows_paper_execution():
    from crypto_trader.domain.enums import ExecutionDecision
    from crypto_trader.risk.engine import RiskEngine

    engine = RiskEngine()
    decision = engine.check(
        make_signal(qty="0.001"),
        account=make_account(),
        positions={},
        market_price=Decimal("100"),
        open_order_count=0,
    )
    assert decision.decision == ExecutionDecision.APPROVE
