"""Durable TradePlan persistence tests (isolated test DB)."""

from crypto_trader.runtime.trade_plan import TradePlan, TradePlanStore


async def test_trade_plan_persists_and_reloads(database):
    store = TradePlanStore(database.session_factory)
    plan = TradePlan(
        trade_plan_id="tp-1",
        decision_id="dec-1",
        llm_invocation_id="llm-1",
        symbol="BTCUSDT",
        execution_symbol="BTC-USDT-SWAP",
        market_type="PERPETUAL",
        direction="LONG",
        selected_strategy="breakout_retest",
        strategy_version="1.0",
        market_regime="TRENDING",
        entry_thesis="bullish structure + pullback",
        supporting_evidence=["trend"],
        contradicting_evidence=["volatility"],
        invalidation_conditions=["close below vwap"],
        target_conditions=["ATH retest"],
        expected_horizon_seconds=14400.0,
        max_holding_time_seconds=21600.0,
        risk_intent="NORMAL",
        entry_price_reference="78000",
        factor_snapshot_id="fs-1",
        tool_trace_id="tt-1",
        memory_refs=["mem-1"],
        status="OPEN",
    )
    await store.put(plan)
    loaded = await store.get("tp-1")
    assert loaded["trade_plan_id"] == "tp-1"
    assert loaded["decision_id"] == "dec-1"
    assert loaded["entry_thesis"] == "bullish structure + pullback"
    assert loaded["direction"] == "LONG"
    assert loaded["status"] == "OPEN"
    assert "trend" in loaded["supporting_evidence"]


async def test_trade_plan_original_thesis_not_overwritten(database):
    store = TradePlanStore(database.session_factory)
    plan = TradePlan(
        trade_plan_id="tp-2", decision_id="dec-2", symbol="ETHUSDT",
        execution_symbol="ETH-USDT-SWAP", market_type="PERPETUAL",
        direction="SHORT", entry_thesis="range rejection at high",
        status="PLANNED")
    await store.put(plan)
    await store.update_status("tp-2", "INVALIDATED")
    loaded = await store.get("tp-2")
    assert loaded["entry_thesis"] == "range rejection at high"
    assert loaded["status"] == "INVALIDATED"
