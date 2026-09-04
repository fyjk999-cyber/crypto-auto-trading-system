from __future__ import annotations

from datetime import UTC, datetime

import pytest

from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.trade_plan.service import TradePlanService, TradePlanState


def decision(action: str, *, size: float = 0.1) -> ChiefTraderDecision:
    return ChiefTraderDecision(
        decision_id="live_decision_1",
        symbol="BTCUSDT",
        action=action,
        market_regime="BULL",
        thesis="factual market structure supports the proposal",
        position_size_request=size,
        leverage_request=2,
        created_at=datetime.now(UTC).isoformat(),
    )


async def test_live_llm_entry_creates_idempotent_trade_plan_before_signal(database):
    planner = LiveLLMTradePlanner(TradePlanService(database.session_factory))
    first_plan, first_signal = await planner.create_entry_signal(decision("LONG"))
    second_plan, second_signal = await planner.create_entry_signal(decision("LONG"))

    assert first_plan is not None and first_signal is not None
    assert first_plan.state == TradePlanState.PLANNED
    assert first_signal.metadata["trade_plan_id"] == first_plan.trade_plan_id
    assert second_plan is not None and second_signal is not None
    assert second_plan.trade_plan_id == first_plan.trade_plan_id
    assert second_signal.signal_id == first_signal.signal_id


async def test_live_llm_no_trade_never_creates_plan_or_signal(database):
    planner = LiveLLMTradePlanner(TradePlanService(database.session_factory))
    plan, signal = await planner.create_entry_signal(decision("NO_TRADE"))
    assert plan is None
    assert signal is None
    with pytest.raises(ValueError):
        await planner.create_entry_signal(decision("SHORT", size=0))
