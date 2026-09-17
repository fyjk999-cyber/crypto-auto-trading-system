# ruff: noqa: ASYNC240
"""M5: deterministic #21 promotion gate and ACTIVE artifact runtime cutover."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from crypto_trader import ml_trainer
from crypto_trader.factors.expert.engine import ExpertEvidenceEngine
from crypto_trader.market_data.opportunity.factors import Candle
from crypto_trader.market_data.state import MarketState
from crypto_trader.ml_artifacts import ArtifactResolver
from crypto_trader.ml_registry import ModelRegistry
from crypto_trader.ml_shadow import decide_promotion

MODEL_21 = "21_ORDER_FLOW_ML"


def _ordered_samples(n=120):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(n):
        bullish = i % 2 == 0
        rows.append(
            {
                "ts": (start + timedelta(minutes=i)).isoformat(),
                "features": {
                    "l1_imbalance": 0.4 if bullish else -0.4,
                    "l5_imbalance": 0.3 if bullish else -0.3,
                    "price": 100.0,
                    "microprice": 100.01,
                    "spread_bps": 5.0,
                    "cvd": 5.0 if bullish else -5.0,
                    "taker_buy_volume": 10.0 if bullish else 4.0,
                    "taker_sell_volume": 4.0 if bullish else 10.0,
                    "relative_volume": 1.2,
                    "oi_change_pct": 0.3,
                    "funding_rate": 0.0001,
                    "price_change_24h_pct": 1.0 if bullish else -1.0,
                    "trade_count": 120,
                    "trade_notional_window_usd": 1_000_000.0,
                    "large_trade_count": 3,
                },
                "label": 1 if bullish else 0,
                "net_bps": 30.0 if bullish else -20.0,
            }
        )
    return rows


def _active_21_registry(tmp_path) -> tuple[ModelRegistry, dict]:
    result = ml_trainer.walk_forward_train(
        _ordered_samples(),
        tmp_path,
        horizon="15m",
        direction="LONG",
        min_edge_bps=0.0,
        code_sha="sha-m5",
        dataset_version="ds-active",
        dataset_hash="dhash-active",
    )
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register(
        model_id=MODEL_21,
        model_version=result["model_version"],
        artifact_path=result["artifact_path"],
        artifact_hash=result["artifact_hash"],
        dataset_version=result["dataset_version"],
        dataset_hash=result["dataset_hash"],
        feature_version=result["feature_version"],
        feature_schema_hash=result["feature_schema_hash"],
        label_version=result["label_version"],
        code_sha="sha-m5",
        algorithm=result["artifact_metadata"]["algorithm"],
        training_cutoff_ts=result["training_cutoff_ts"],
        validation_windows=result["artifact_metadata"]["validation_windows"],
        hyperparameters=result["artifact_metadata"]["hyperparameters"],
        metrics=result["metrics"],
        state="VALIDATING",
    )
    registry.set_state(MODEL_21, result["model_version"], "ACTIVE", reason="test-promote")
    return registry, result


def _candles():
    start = 1_700_000_000_000
    return [
        Candle(
            ts_ms=start + i * 60_000,
            open=100.0 + i * 0.01,
            high=100.1 + i * 0.01,
            low=99.9 + i * 0.01,
            close=100.0 + i * 0.01,
            volume=10.0,
        )
        for i in range(300)
    ]


async def _engine(registry: ModelRegistry):
    candles = _candles()

    async def timeframe_provider(_symbol):
        return {bar: candles for bar in ("4h", "1h", "15m", "5m", "1m")}

    state = MarketState(
        symbol="BTCUSDT",
        price=Decimal("100"),
        best_bid=Decimal("99.99"),
        best_ask=Decimal("100.01"),
        bid_size=Decimal("3"),
        ask_size=Decimal("2"),
        imbalance_l5=Decimal("0.2"),
        microprice=Decimal("100"),
        spread_bps=Decimal("2"),
        taker_buy_volume=Decimal("10"),
        taker_sell_volume=Decimal("8"),
        cvd=Decimal("2"),
        trade_count=100,
        trade_notional=Decimal("100000"),
        large_trade_count=2,
        open_interest=Decimal("1000000"),
        funding_rate=Decimal("0.0001"),
    )
    return ExpertEvidenceEngine(
        timeframe_provider=timeframe_provider,
        state_provider=lambda _symbol: state,
        model_runtime=ArtifactResolver(registry),
    )


async def test_active_21_artifact_is_used_in_runtime_evidence(tmp_path) -> None:
    registry, result = _active_21_registry(tmp_path)
    engine = await _engine(registry)
    package = await engine.evaluate(symbol="BTCUSDT")
    assert package is not None
    row = package.model_evidence[MODEL_21]
    metrics = row["metrics"]
    assert metrics["artifact_status"] == "ACTIVE_TRAINED_ARTIFACT"
    assert metrics["artifact_hash"] == result["artifact_hash"]
    assert metrics["dataset_version"] == "ds-active"
    assert row["model_version"] == result["model_version"]
    assert 0.0 <= metrics["probability_up"] <= 1.0
    assert row["direction"] in {"LONG", "SHORT", "NEUTRAL"}


async def test_provisional_21_is_used_only_without_active_artifact(tmp_path) -> None:
    engine = await _engine(ModelRegistry(tmp_path / "empty-registry.json"))
    package = await engine.evaluate(symbol="BTCUSDT")
    row = package.model_evidence[MODEL_21]
    assert row["metrics"]["artifact_status"] == "PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED"
    assert "ACTIVE_TRAINED_ARTIFACT" not in row["metrics"]["artifact_status"]


async def test_corrupt_active_21_degrades_and_never_uses_proxy(tmp_path) -> None:
    registry, result = _active_21_registry(tmp_path)
    artifact_path = Path(result["artifact_path"])
    corrupt = json.loads(artifact_path.read_text())
    corrupt["weights"] = [0.0] * len(corrupt["weights"])
    artifact_path.write_text(json.dumps(corrupt, sort_keys=True))
    engine = await _engine(registry)
    package = await engine.evaluate(symbol="BTCUSDT")
    row = package.model_evidence[MODEL_21]
    assert row["direction"] == "UNAVAILABLE"
    assert row["metrics"]["artifact_status"] == "ACTIVE_ARTIFACT_INTEGRITY_FAILED"
    assert "PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED" not in json.dumps(row["metrics"])
    assert "ACTIVE_ARTIFACT_INTEGRITY_FAILED" in (row["unavailable_reason"] or "")


def test_promotion_gate_requires_integrity_true_forward_and_performance() -> None:
    good_forward = {"samples": 30, "mean_net_bps": 8.0, "win_rate": 0.6}
    assert (
        decide_promotion(
            post_cost_passed=True,
            fold_count=3,
            shadow_summary=good_forward,
            artifact_integrity=False,
        )
        == "REJECT"
    )
    assert (
        decide_promotion(
            post_cost_passed=True,
            fold_count=3,
            shadow_summary=good_forward,
            schema_compatible=False,
        )
        == "REJECT"
    )
    assert (
        decide_promotion(
            post_cost_passed=True,
            fold_count=3,
            shadow_summary={"samples": 5, "mean_net_bps": 8.0, "win_rate": 0.6},
            min_shadow=30,
        )
        == "CONTINUE_SHADOW"
    )
    assert (
        decide_promotion(
            post_cost_passed=True,
            fold_count=3,
            shadow_summary={"samples": 30, "mean_net_bps": 8.0, "win_rate": 0.6},
            min_shadow=30,
        )
        == "PROMOTE"
    )
    assert (
        decide_promotion(
            post_cost_passed=True,
            fold_count=3,
            shadow_summary={"samples": 30, "mean_net_bps": -1.0, "win_rate": 0.6},
            min_shadow=30,
        )
        == "REJECT"
    )
