from types import SimpleNamespace

import pytest

from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.runtime.ai_first_chief_trader import AIFirstChiefTraderStrategyAdapter


def _chief_context(*, fit: float = 0.10, regime: str = "UNKNOWN", snapshot: bool = True):
    return ChiefTraderContext(
        symbol="ETHUSDT",
        market_snapshot={"symbol": "ETHUSDT"},
        regime=regime,
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        strategy_evidence={
            "market_regime": regime,
            "strategy_candidates": [
                {
                    "strategy_id": "market_structure",
                    "strategy_version": "0.1.0",
                    "direction": "LONG",
                    "fit_score": fit,
                    "raw_confidence": fit,
                    "supporting_factors": ["trend"],
                    "contradicting_factors": ["mean_reversion"],
                    "reason_codes": ["TEST_EVIDENCE"],
                    "data_health": "OK",
                }
            ],
        },
        factor_snapshot=(
            {"snapshot_id": "snap_test", "factor_set_version": "v1"}
            if snapshot
            else {}
        ),
    )


def _long_decision(*, fit: float = 0.10, confidence: float = 0.20):
    return ChiefTraderDecision(
        decision_id="decision_test",
        symbol="ETHUSDT",
        action="LONG",
        market_regime="UNKNOWN",
        thesis="AI sees a trade despite weak quantitative evidence",
        selected_strategy="market_structure",
        strategy_fit_score=fit,
        raw_llm_confidence=confidence,
        evidence_adjusted_confidence=confidence,
        reason_codes=["AI_DECISION"],
    )


class _DecisionEngine:
    model_version = "test"

    def __init__(self, decision) -> None:
        self.decision = decision
        self.calls = 0

    async def decide(self, chief_ctx):
        self.calls += 1
        return self.decision


class _TestAIFirstAdapter(AIFirstChiefTraderStrategyAdapter):
    def __init__(self, chief_ctx, decision) -> None:
        super().__init__(
            min_strategy_fit=0.45,
            min_trade_confidence=0.55,
            entry_cooldown_seconds=0.0,
        )
        self.test_context = chief_ctx
        self.engine = _DecisionEngine(decision)
        self.persisted = []

    async def _build_context(self, ctx):
        return self.test_context

    async def _persist_evidence(self, decision, ctx, chief_ctx, execution_reference=""):
        self.persisted.append(decision)

    def _map_to_signals(self, decision, ctx, chief_ctx, trade_plan_id=""):
        if decision.action in ("LONG", "SHORT"):
            return [SimpleNamespace(signal_id="sig_test", action=decision.action,
                                    metadata={"trade_plan_id": trade_plan_id})]
        return []


@pytest.mark.asyncio
async def test_low_strategy_fit_and_low_confidence_still_reach_ai_and_preserve_action():
    adapter = _TestAIFirstAdapter(
        _chief_context(fit=0.10, regime="UNKNOWN"),
        _long_decision(fit=0.10, confidence=0.20),
    )
    ctx = SimpleNamespace(symbol="ETHUSDT", positions={})

    signals = await adapter._decide(ctx)

    assert adapter.engine.calls == 1
    assert len(signals) == 1
    persisted = adapter.persisted[-1]
    assert persisted.action == "LONG"
    assert "LOW_STRATEGY_FIT_EVIDENCE" in persisted.reason_codes
    assert "LOW_CONFIDENCE_EVIDENCE" in persisted.reason_codes
    assert "REGIME_UNKNOWN" in persisted.reason_codes


@pytest.mark.asyncio
async def test_other_symbol_position_does_not_block_current_symbol_ai_decision():
    adapter = _TestAIFirstAdapter(
        _chief_context(fit=0.60, regime="BULL"),
        _long_decision(fit=0.60, confidence=0.70),
    )
    ctx = SimpleNamespace(
        symbol="ETHUSDT",
        positions={"BTCUSDT": SimpleNamespace(quantity=1)},
    )

    signals = await adapter._decide(ctx)

    assert adapter.engine.calls == 1
    assert len(signals) == 1


@pytest.mark.asyncio
async def test_current_symbol_position_still_blocks_new_entry():
    adapter = _TestAIFirstAdapter(
        _chief_context(fit=0.60, regime="BULL"),
        _long_decision(fit=0.60, confidence=0.70),
    )
    ctx = SimpleNamespace(
        symbol="ETHUSDT",
        positions={"ETHUSDT": SimpleNamespace(quantity=1)},
    )

    signals = await adapter._decide(ctx)

    assert signals == []
    assert adapter.engine.calls == 0
    assert adapter.persisted[-1].reason_codes == ["POSITION_ALREADY_OPEN"]


@pytest.mark.asyncio
async def test_missing_real_factor_snapshot_remains_fail_closed_before_ai():
    adapter = _TestAIFirstAdapter(
        _chief_context(fit=0.60, regime="BULL", snapshot=False),
        _long_decision(fit=0.60, confidence=0.70),
    )
    ctx = SimpleNamespace(symbol="ETHUSDT", positions={})

    signals = await adapter._decide(ctx)

    assert signals == []
    assert adapter.engine.calls == 0
    assert adapter.persisted[-1].reason_codes == ["FACTOR_CONTEXT_UNAVAILABLE"]


@pytest.mark.asyncio
async def test_open_perpetual_position_gates_new_entry_before_ai():
    adapter = _TestAIFirstAdapter(
        _chief_context(fit=0.60, regime="BULL"),
        _long_decision(fit=0.60, confidence=0.70),
    )
    adapter.perpetual_position_provider = lambda symbol: True
    ctx = SimpleNamespace(symbol="ETHUSDT", positions={})

    signals = await adapter._decide(ctx)

    assert adapter.engine.calls == 0  # AI is never consulted for pyramiding
    assert signals == []
    assert "POSITION_ALREADY_OPEN" in adapter.persisted[-1].reason_codes


@pytest.mark.asyncio
async def test_perpetual_state_check_failure_fails_closed():
    adapter = _TestAIFirstAdapter(
        _chief_context(fit=0.60, regime="BULL"),
        _long_decision(fit=0.60, confidence=0.70),
    )

    async def _broken_provider():
        raise RuntimeError("state store unavailable")

    adapter.perpetual_position_provider = _broken_provider
    ctx = SimpleNamespace(symbol="ETHUSDT", positions={})

    signals = await adapter._decide(ctx)

    assert adapter.engine.calls == 0
    assert signals == []
    assert "PERPETUAL_STATE_UNAVAILABLE" in adapter.persisted[-1].reason_codes


@pytest.mark.asyncio
async def test_flat_perpetual_state_does_not_block_entry():
    adapter = _TestAIFirstAdapter(
        _chief_context(fit=0.60, regime="BULL"),
        _long_decision(fit=0.60, confidence=0.70),
    )
    adapter.perpetual_position_provider = lambda symbol: False
    ctx = SimpleNamespace(symbol="ETHUSDT", positions={})

    signals = await adapter._decide(ctx)

    assert adapter.engine.calls == 1
    assert len(signals) == 1
