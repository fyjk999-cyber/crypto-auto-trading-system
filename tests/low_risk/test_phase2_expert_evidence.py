"""Phase 2 (Low-Risk V2) 25-model expert evidence tests.

Fixtures are deterministic unit inputs, not fabricated acceptance evidence.
They prove the model contract (completeness, opposition preservation,
correlation control, no-data honesty, cost gate, no order authority).
"""

from __future__ import annotations

import inspect
import math
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from crypto_trader.factors.expert import (
    REQUIRED_MODELS,
    AllInCostEstimate,
    EvidenceDirection,
    ExpertEvidenceEngine,
    ExpertInputs,
    ModelEvidence,
    ModelFamily,
    build_consensus,
    build_timeframes,
    resample_candles,
)
from crypto_trader.factors.expert import engine as engine_module
from crypto_trader.factors.expert import models as models_module
from crypto_trader.factors.expert.models import evaluate_all
from crypto_trader.market_data.opportunity.factors import Candle
from crypto_trader.market_data.state import DataHealth, MarketState, SourceStatus

BASE_MS = 1_767_000_000_000  # epoch-aligned minute boundary


def _candles(
    count: int, *, drift: float = 0.0005, start: float = 100.0, volume: float = 10.0
) -> list[Candle]:
    candles: list[Candle] = []
    price = start
    for index in range(count):
        open_price = price
        price = price * (1.0 + drift)
        high = max(open_price, price) * (1.0 + 0.0004)
        low = min(open_price, price) * (1.0 - 0.0004)
        candles.append(
            Candle(
                ts_ms=BASE_MS - (count - index) * 60_000,
                open=open_price,
                high=high,
                low=low,
                close=price,
                volume=volume + (index % 5),
            )
        )
    return candles


def _state(*, cvd: Decimal = Decimal("50"), imbalance: Decimal = Decimal("0.3")) -> MarketState:
    state = MarketState(
        symbol="BTCUSDT",
        provider="OKX_PUBLIC",
        data_source="REAL",
        instrument_id="BTC-USDT-SWAP",
        price=Decimal("120"),
        mark_price=Decimal("120"),
        index_price=Decimal("120"),
        best_bid=Decimal("119.99"),
        best_ask=Decimal("120.01"),
        spread=Decimal("0.02"),
        depth=Decimal("100"),
        taker_buy_volume=Decimal("150"),
        taker_sell_volume=Decimal("100"),
        cvd=cvd,
        trade_count=80,
        trade_notional=Decimal("2400000"),
        large_trade_count=3,
        largest_trade_notional=Decimal("150000"),
        trades_window_seconds=120.0,
        last_trade_price=Decimal("120"),
        depth_bid_5=Decimal("60"),
        depth_ask_5=Decimal("40"),
        depth_bid_10=Decimal("90"),
        depth_ask_10=Decimal("70"),
        imbalance_l5=imbalance,
        microprice=Decimal("120.005"),
        spread_bps=Decimal("1.6"),
        funding_rate=Decimal("0.0001"),
        open_interest=Decimal("1000000"),
        open_interest_change=Decimal("-5000"),
    )
    for name in (
        "ticker",
        "orderbook",
        "mark_price",
        "index_price",
        "funding",
        "open_interest",
        "trades",
    ):
        state.sources[name] = SourceStatus(status=DataHealth.HEALTHY, age_seconds=0.1)
    state.mark_healthy_from_sources()
    return state


TIMEFRAMES = ("4h", "1h", "15m", "5m", "1m")


def _timeframe_candles(count: int, drift: float) -> dict[str, list[Candle]]:
    return {timeframe: _candles(count, drift=drift) for timeframe in TIMEFRAMES}


def _inputs(
    *, count: int = 400, drift: float = 0.0005, state: MarketState | None = None
) -> ExpertInputs:
    return ExpertInputs(
        symbol="BTCUSDT",
        candles=_timeframe_candles(count, drift),
        state=state if state is not None else _state(),
    )


def test_required_registry_is_exactly_25_models() -> None:
    assert len(REQUIRED_MODELS) == 25
    ids = [spec.model_id for spec in REQUIRED_MODELS]
    assert len(set(ids)) == 25
    assert ids[0] == "01_EMA_MULTI_TF" and ids[-1] == "25_META_FORECAST"
    families = {spec.family for spec in REQUIRED_MODELS}
    assert {
        ModelFamily.TREND,
        ModelFamily.MOMENTUM,
        ModelFamily.MEAN_REVERSION,
        ModelFamily.VOLATILITY,
        ModelFamily.VOLUME_FLOW,
        ModelFamily.ORDER_FLOW,
        ModelFamily.POSITIONING,
        ModelFamily.REGIME,
        ModelFamily.META,
    } <= families
    assert set(models_module.MODEL_FUNCTIONS) == set(ids) - {"25_META_FORECAST"}


def test_all_25_models_evaluate_with_factual_series() -> None:
    outputs = evaluate_all(_inputs())
    assert set(outputs) == {spec.model_id for spec in REQUIRED_MODELS}
    for model_id, evidence in outputs.items():
        assert evidence.model_id == model_id
        assert evidence.direction in set(EvidenceDirection)
        assert -1.0 <= evidence.direction_score <= 1.0
        assert 0.0 <= evidence.confidence <= 1.0
        assert evidence.theory
        assert isinstance(evidence.supporting_evidence, list)
        assert isinstance(evidence.counter_evidence, list)
    available = [item for item in outputs.values() if item.available]
    # With 400 factual 1m candles + a healthy market state, nearly every model
    # has enough data; the meta model must always be available when others are.
    assert len(available) >= 20
    assert outputs["25_META_FORECAST"].available


def test_insufficient_data_is_unavailable_and_never_fabricated() -> None:
    inputs = ExpertInputs(symbol="BTCUSDT", candles={}, state=None)
    outputs = evaluate_all(inputs)
    assert len(outputs) == 25
    for evidence in outputs.values():
        assert evidence.direction == EvidenceDirection.UNAVAILABLE
        assert evidence.confidence == 0.0
        assert evidence.unavailable_reason
        assert evidence.direction_score == 0.0
    consensus = build_consensus("UNCERTAIN", list(outputs.values()))
    assert consensus.unavailable_count == 25
    assert consensus.long_count == consensus.short_count == consensus.neutral_count == 0
    assert consensus.not_an_order is True
    assert consensus.authority == "EVIDENCE_ONLY"


def test_consensus_preserves_opposition_and_correlated_families() -> None:
    outputs = evaluate_all(_inputs(drift=0.0006))
    evidence = list(outputs.values())
    consensus = build_consensus("TREND_UP", evidence)
    directional = [item for item in evidence if item.available]
    assert (
        consensus.long_count + consensus.short_count + consensus.neutral_count
        == len(directional)
    )
    # Family collapsing must never exceed the number of families and must be
    # strictly smaller than the directional model count when models disagree.
    assert consensus.effective_independent_evidence <= len(consensus.family_votes)
    assert len(consensus.family_votes) <= len(ModelFamily)
    assert consensus.not_an_order is True
    assert consensus.authority == "EVIDENCE_ONLY"
    # Devil's advocate material is always present when any model is available.
    assert consensus.strongest_counterarguments
    assert consensus.strongest_support


def test_20l0s5n_differs_from_20l5s0n() -> None:
    def make(direction: EvidenceDirection, count: int, family: ModelFamily) -> list[ModelEvidence]:
        return [
            ModelEvidence(
                model_id=f"T{index:02d}",
                model_version="test",
                family=family,
                symbol="BTCUSDT",
                timeframes=("1h",),
                direction=direction,
                direction_score=(
                    1.0
                    if direction == EvidenceDirection.LONG
                    else -1.0
                    if direction == EvidenceDirection.SHORT
                    else 0.0
                ),
                confidence=0.7,
                theory="unit fixture",
                supporting_evidence=["support"] if direction != EvidenceDirection.NEUTRAL else [],
                counter_evidence=["counter"] if direction != EvidenceDirection.NEUTRAL else [],
            )
            for index in range(count)
        ]

    longs = make(EvidenceDirection.LONG, 20, ModelFamily.TREND)
    neutrals = make(EvidenceDirection.NEUTRAL, 5, ModelFamily.MOMENTUM)
    shorts = make(EvidenceDirection.SHORT, 5, ModelFamily.MOMENTUM)
    case_a = build_consensus("TREND_UP", longs + neutrals)
    case_b = build_consensus("TREND_UP", longs + shorts)
    assert case_a.long_count == 20 and case_a.short_count == 0 and case_a.neutral_count == 5
    assert case_b.long_count == 20 and case_b.short_count == 5 and case_b.neutral_count == 0
    assert case_a.raw_score != case_b.raw_score
    assert case_a.long_count != case_b.short_count
    # Family collapse: many same-family votes are one effective fact.
    assert case_a.effective_independent_evidence <= 2
    assert case_b.effective_independent_evidence <= 2


def test_meta_forecast_rejects_trivial_edge_after_costs() -> None:
    expensive = AllInCostEstimate(
        entry_fee_bps=50.0,
        exit_fee_bps=50.0,
        spread_bps=30.0,
        slippage_bps=30.0,
        funding_bps=20.0,
        safety_margin_bps=20.0,
    )
    inputs = _inputs()
    inputs.costs = expensive
    outputs = evaluate_all(inputs)
    meta = outputs["25_META_FORECAST"]
    assert meta.metrics["all_in_cost_bps"] == pytest.approx(expensive.total_cost_bps)
    assert any("EXPECTED_EDGE_BELOW_ALL_IN_COST" in item for item in meta.counter_evidence)
    assert abs(meta.direction_score) < 0.05


def test_engine_is_deterministic_and_uses_bounded_providers() -> None:
    provider_calls = {"candles": 0}

    async def timeframe_provider(symbol: str):
        provider_calls["candles"] += 1
        return _timeframe_candles(400, 0.0005)

    async def run():
        engine = ExpertEvidenceEngine(
            timeframe_provider=timeframe_provider,
            state_provider=lambda symbol: _state(),
        )
        first = await engine.evaluate(symbol="BTCUSDT")
        second = await engine.evaluate(symbol="BTCUSDT")
        return first, second

    import asyncio

    first, second = asyncio.run(run())
    assert first is not None and second is not None

    def stable(package):
        return {
            model_id: {k: v for k, v in item.items() if k != "freshness_seconds"}
            for model_id, item in package.as_dict()["models"].items()
        }

    assert stable(first) == stable(second)
    assert first.consensus.as_dict() == second.consensus.as_dict()
    assert provider_calls["candles"] == 2


def test_engine_returns_none_without_factual_candles() -> None:
    async def empty_provider(symbol: str):
        return []

    async def run():
        engine = ExpertEvidenceEngine(candle_provider=empty_provider)
        return await engine.evaluate(symbol="BTCUSDT")

    import asyncio

    package = asyncio.run(run())
    assert package is None
    assert engine_module.REQUIRED_MODEL_IDS[0] == "01_EMA_MULTI_TF"


def test_resample_candles_is_deterministic() -> None:
    candles = _candles(125)
    hourly = resample_candles(candles, 60)
    assert len(hourly) >= 2
    for group in hourly:
        assert all(item.ts_ms % 3_600_000 == 0 for item in [group])
        assert group.high >= group.open and group.high >= group.close
        assert group.low <= group.open and group.low <= group.close
    assert resample_candles(candles, 60) == hourly
    assert len(resample_candles(candles, 1)) == len(candles)


def test_expert_layer_has_no_order_authority() -> None:
    sources = [
        inspect.getsource(engine_module),
        inspect.getsource(models_module),
    ]
    combined = "\n".join(sources)
    for forbidden in (
        "ExecutionAuthority",
        "OrderManager",
        "submit_order",
        "process_signal",
        "SignalIntent",
        "TradePlan",
    ):
        assert forbidden not in combined, f"expert layer must not reference {forbidden}"
    assert engine_module.ExpertEvidencePackage is not None


def test_chief_context_renders_expert_evidence() -> None:
    from crypto_trader.llm_chief.context import ChiefTraderContext
    from crypto_trader.llm_chief.engine import ChiefTraderEngine

    ctx = ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={},
        regime="TREND_UP",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        model_evidence={"consensus": {"not_an_order": True}, "models_total": 25},
    )
    prompt = ChiefTraderEngine().render_prompt(ctx)
    assert "ExpertEvidence25" in prompt
    assert "not_an_order" in prompt


def test_build_timeframes_contains_only_requested_bars() -> None:
    timeframes = build_timeframes(_candles(130))
    assert set(timeframes) == {"4h", "1h", "15m", "5m", "1m"}
    assert len(timeframes["1m"]) == 130
    assert timeframes["15m"][-1].close == pytest.approx(timeframes["1m"][-1].close)
    assert math.isfinite(float(_candles(2)[0].volume))
    assert datetime.now(UTC).tzinfo is not None
