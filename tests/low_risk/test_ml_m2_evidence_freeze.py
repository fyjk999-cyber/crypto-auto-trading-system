"""M2: factual decision-time #01-#24 evidence freeze in the canonical scanner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from crypto_trader.factors.expert.types import REQUIRED_MODEL_IDS
from crypto_trader.market_data.opportunity.factors import SymbolFacts
from crypto_trader.market_data.opportunity.service import OpportunityScannerService
from crypto_trader.market_data.opportunity.snapshots import (
    MODEL_EVIDENCE_SCHEMA_VERSION,
    ScanSnapshotCollector,
    decision_time_features,
    freeze_model_evidence,
)
from crypto_trader.persistence.models import ScanSnapshotORM


def _facts(symbol: str) -> SymbolFacts:
    return SymbolFacts(
        symbol=symbol,
        last_price=100.0,
        bid=99.9,
        ask=100.1,
        bid_qty=2.0,
        ask_qty=1.0,
        spread_bps=20.0,
        book_imbalance_l5=0.3,
        microprice=100.0,
        trade_count=120,
        taker_buy_volume=10.0,
        taker_sell_volume=6.0,
        cvd=4.0,
        volume_24h_usd=1_000_000.0,
        cohort_median_turnover_usd=500_000.0,
        open_interest=12345.0,
        oi_change_pct=1.5,
        funding_rate=0.0001,
        observed_at=datetime.now(UTC),
    )


def _model_evidence(model_id: str) -> dict:
    return {
        "model_id": model_id,
        "model_version": "1.0",
        "family": "ORDER_FLOW",
        "direction": "LONG",
        "direction_score": 0.42,
        "score": 0.42,
        "confidence": 0.71,
        "available": True,
        "theory": "factual decision-time theory",
        "supporting_evidence": ["cvd_ratio=0.2"],
        "counter_evidence": ["spread=20bps"],
        "neutral_evidence": [],
        "regime_compatibility": ["TREND"],
        "strategy_compatibility": ["BREAKOUT"],
        "data_quality": "HEALTHY",
        "freshness_seconds": 1.2,
        "sample_size": 120,
        "reliability_tier": "CANDIDATE",
        "metrics": {
            "artifact_status": "PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED",
            "artifact_hash": "abc",
        },
        "unavailable_reason": None,
    }


class FakeEvidenceEngine:
    authority = "EVIDENCE_ONLY"

    def __init__(self, regime: str = "TREND") -> None:
        self.regime = regime
        self.calls: list[str] = []
        self.costs = SimpleNamespace(as_dict=lambda: {"total_cost_bps": 22.0})

    async def evaluate(self, *, symbol, state=None):
        self.calls.append(symbol)
        evidence = {
            model_id: _model_evidence(model_id)
            for model_id in REQUIRED_MODEL_IDS
            if model_id != "25_META_FORECAST"
        }
        evidence["25_META_FORECAST"] = {
            **_model_evidence("25_META_FORECAST"),
            "metrics": {"artifact_status": "PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED"},
        }
        return SimpleNamespace(symbol=symbol, regime=self.regime, model_evidence=evidence)


def test_freeze_model_evidence_full_factual_contract_and_no_self_feature() -> None:
    evidence = [_model_evidence("01_EMA_MULTI_TF"), _model_evidence("25_META_FORECAST")]
    frozen = freeze_model_evidence(evidence)
    assert len(frozen) == 1
    row = frozen[0]
    for key in (
        "model_id",
        "model_version",
        "family",
        "available",
        "direction",
        "score",
        "confidence",
        "quality",
        "freshness",
        "theory",
        "supporting_evidence",
        "counter_evidence",
        "neutral_evidence",
        "metrics",
        "artifact_status",
        "artifact_version",
        "artifact_hash",
    ):
        assert key in row, key
    assert row["model_id"] == "01_EMA_MULTI_TF"
    assert row["artifact_status"] == "PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED"

    features = decision_time_features(_facts("BTCUSDT"), model_evidence=evidence)
    assert features["model_evidence_schema_version"] == MODEL_EVIDENCE_SCHEMA_VERSION
    assert features["model_evidence_01_24_count"] == 1
    assert all(item["model_id"] != "25_META_FORECAST" for item in features["model_evidence"])


async def test_candidate_and_control_freeze_same_01_24_schema(database) -> None:
    engine = FakeEvidenceEngine()
    service = object.__new__(OpportunityScannerService)
    service.snapshot_collector = ScanSnapshotCollector(database.session_factory)
    service.control_sample_size = 1
    service.collection_error = None
    service.collection_stats = {}
    service.expert_engine = engine
    service.state_provider = None
    candidate = SimpleNamespace(symbol="BTCUSDT", priority=0.9, nominated_reason="BREAKOUT_ATTEMPT")
    facts = {symbol: _facts(symbol) for symbol in ("BTCUSDT", "ETHUSDT")}
    await service._collect_ml_snapshots([candidate], facts, [], captured_at=datetime.now(UTC))
    assert service.collection_error is None

    async with database.session_factory() as session:
        rows = (await session.execute(select(ScanSnapshotORM))).scalars().all()
    assert len(rows) == 2
    assert {row.candidate for row in rows} == {True, False}
    candidate_features = next(row.features_json for row in rows if row.candidate)
    control_features = next(row.features_json for row in rows if row.control)
    for features in (candidate_features, control_features):
        assert features["model_evidence_01_24_count"] == 24
        assert features["model_evidence_schema_version"] == MODEL_EVIDENCE_SCHEMA_VERSION
        assert features["artifact_status"] == "PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED"
        assert all(
            item["model_id"] != "25_META_FORECAST" for item in features["model_evidence"]
        )
    assert {item["model_id"] for item in candidate_features["model_evidence"]} == {
        item["model_id"] for item in control_features["model_evidence"]
    }
    assert set(candidate_features["model_evidence"][0]) == set(
        control_features["model_evidence"][0]
    )
    assert sorted(engine.calls) == ["BTCUSDT", "ETHUSDT"]


async def test_persisted_decision_time_evidence_is_not_recomputed(database) -> None:
    engine = FakeEvidenceEngine()
    service = object.__new__(OpportunityScannerService)
    service.snapshot_collector = ScanSnapshotCollector(database.session_factory)
    service.control_sample_size = 0
    service.collection_error = None
    service.collection_stats = {}
    service.expert_engine = engine
    service.state_provider = None
    candidate = SimpleNamespace(symbol="BTCUSDT", priority=0.9, nominated_reason="BREAKOUT_ATTEMPT")
    facts = {"BTCUSDT": _facts("BTCUSDT")}
    first_at = datetime.now(UTC)
    await service._collect_ml_snapshots([candidate], facts, [], captured_at=first_at)

    async with database.session_factory() as session:
        original = (await session.execute(select(ScanSnapshotORM))).scalars().one()
        original_features = dict(original.features_json)

    # A later evaluation with different evidence must not rewrite the old row.
    engine.regime = "UNCERTAIN"
    await service._collect_ml_snapshots(
        [candidate], facts, [], captured_at=first_at + timedelta(minutes=5)
    )
    async with database.session_factory() as session:
        rows = (
            (await session.execute(select(ScanSnapshotORM).order_by(ScanSnapshotORM.captured_at)))
            .scalars()
            .all()
        )
    assert len(rows) == 2
    assert rows[0].features_json == original_features
    assert rows[0].features_json["model_evidence"][0]["metrics"]["artifact_status"] == (
        "PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED"
    )
