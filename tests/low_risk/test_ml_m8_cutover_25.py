# ruff: noqa: ASYNC240
"""M8: ACTIVE trained XGBoost #25 runtime cutover and corrupt fail-closed."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from crypto_trader import ml_meta
from crypto_trader.factors.expert.engine import ExpertEvidenceEngine
from crypto_trader.factors.expert.types import REQUIRED_MODEL_IDS
from crypto_trader.market_data.opportunity.factors import Candle
from crypto_trader.market_data.state import MarketState
from crypto_trader.ml_artifacts import ArtifactResolver
from crypto_trader.ml_registry import ModelRegistry

MODEL_25 = "25_META_FORECAST"


def _evidence(model_id: str, i: int) -> dict:
    return {
        "model_id": model_id,
        "model_version": "1.0",
        "family": "ORDER_FLOW" if "ORDER" in model_id else "TREND",
        "direction": "LONG" if i % 2 == 0 else "SHORT",
        "score": 0.3 if i % 2 == 0 else -0.3,
        "confidence": 0.7,
        "available": True,
    }


def _frozen(n=140):
    model_ids = [m for m in REQUIRED_MODEL_IDS if m != MODEL_25]
    start = datetime(2026, 1, 1, tzinfo=UTC)
    snaps, labels = [], []
    for i in range(n):
        sid = f"s{i}"
        net = 40.0 if i % 2 == 0 else -20.0
        snaps.append(
            {
                "snapshot_id": sid,
                "captured_at": (start + timedelta(minutes=i)).isoformat(),
                "candidate": i % 2 == 0,
                "control": i % 2 == 1,
                "market_regime": "TREND" if i % 2 == 0 else "RANGE",
                "scanner_rank": (i % 10) + 1,
                "features": {
                    "model_evidence": [_evidence(mid, i) for mid in model_ids],
                    "relative_volume": 1.2,
                    "spread_bps": 5.0,
                    "trade_notional_window_usd": 1_000_000.0,
                    "costs": {"total_cost_bps": 22.0},
                    "price": 100.0,
                },
            }
        )
        labels.append(
            {
                "snapshot_id": sid,
                "horizon": "15m",
                "label_version": "label-v2",
                "long_net_bps": net,
                "short_net_bps": -net,
            }
        )
    return {"snapshots": snaps, "labels": labels}


def _registry_with_active_25(tmp_path) -> ModelRegistry:
    registry = ModelRegistry(tmp_path / "registry.json")
    m21 = tmp_path / "m21.json"
    m21.write_text("{}")
    registry.register(
        model_id="21_ORDER_FLOW_ML",
        model_version="v21",
        artifact_path=str(m21),
        artifact_hash="h21",
        feature_version="order-flow-v2",
        label_version="label-v2",
        state="SHADOW",
    )
    result = ml_meta.train_meta_forecast(
        _frozen(),
        tmp_path,
        registry=registry,
        min_train=20,
        min_valid=5,
        dataset_version="ds-m8",
        dataset_hash="dhash-m8",
    )
    assert result["status"] == "OK"
    registry.set_state(MODEL_25, result["model_version"], "ACTIVE", reason="test")
    return registry


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


async def _engine(registry: ModelRegistry) -> ExpertEvidenceEngine:
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


async def test_active_25_xgboost_is_used_in_runtime_evidence(tmp_path) -> None:
    registry = _registry_with_active_25(tmp_path)
    engine = await _engine(registry)
    package = await engine.evaluate(symbol="BTCUSDT")
    assert package is not None
    row = package.model_evidence[MODEL_25]
    metrics = row["metrics"]
    assert metrics["artifact_status"] == "ACTIVE_TRAINED_ARTIFACT"
    assert metrics["algorithm"] == ml_meta.ALGORITHM_25
    assert metrics["xgboost_version"]
    assert 0.0 <= metrics["probability_up"] <= 1.0
    assert row["model_version"] not in {"", "0"}


async def test_provisional_25_used_only_without_active_artifact(tmp_path) -> None:
    registry = ModelRegistry(tmp_path / "empty-registry.json")
    engine = await _engine(registry)
    package = await engine.evaluate(symbol="BTCUSDT")
    row = package.model_evidence[MODEL_25]
    assert row["metrics"]["artifact_status"] == "PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED"


async def test_corrupt_active_25_degrades_and_never_uses_proxy(tmp_path) -> None:
    registry = _registry_with_active_25(tmp_path)
    entry = registry.active_entry(MODEL_25)
    metadata_path = Path(entry["artifact_path"])
    metadata = json.loads(metadata_path.read_text())
    model_path = Path(metadata["xgboost_model_path"])
    original = model_path.read_bytes()
    model_path.write_bytes(original + b"corrupt")
    engine = await _engine(registry)
    package = await engine.evaluate(symbol="BTCUSDT")
    row = package.model_evidence[MODEL_25]
    assert row["direction"] == "UNAVAILABLE"
    assert row["metrics"]["artifact_status"] == "ACTIVE_ARTIFACT_INTEGRITY_FAILED"
    assert "PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED" not in json.dumps(row["metrics"])
