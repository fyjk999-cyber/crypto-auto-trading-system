"""Phase B: scanner feature collector, control samples, persistence."""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_trader.market_data.opportunity.factors import SymbolFacts
from crypto_trader.market_data.opportunity.snapshots import (
    SCAN_FEATURE_VERSION,
    ScanSnapshotCollector,
    build_scan_snapshot,
    decision_time_features,
    select_control_samples,
)


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


def test_features_are_decision_time_and_versioned() -> None:
    features = decision_time_features(_facts("BTCUSDT"))
    assert features["feature_version"] == SCAN_FEATURE_VERSION
    assert features["available_at_decision_time"] is True
    assert features["l1_imbalance"] == (2.0 - 1.0) / 3.0
    assert features["relative_volume"] == 2.0
    assert features["l10_imbalance"] is None  # honest feed gap
    assert features["is_order"] is False


def test_control_samples_never_include_candidates() -> None:
    facts = {symbol: _facts(symbol) for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")}
    controls = select_control_samples(
        facts, candidate_symbols={"BTCUSDT", "ETHUSDT"}, count=2, seed=7
    )
    assert len(controls) == 2
    assert {row["symbol"] for row in controls} <= {"SOLUSDT", "XRPUSDT"}
    assert all(row["control"] and not row["candidate"] for row in controls)
    assert all(row["sampling_method"] for row in controls)
    assert all(row["selection_probability"] == 1.0 for row in controls)


async def test_scan_snapshot_persists_candidate_and_control(database) -> None:
    collector = ScanSnapshotCollector(database.session_factory)
    cycle_id = "cycle-test-1"
    rows = [
        build_scan_snapshot(
            symbol="BTCUSDT",
            features=decision_time_features(_facts("BTCUSDT")),
            cycle_id=cycle_id,
            candidate=True,
            control=False,
            scanner_rank=1,
            scanner_score=0.9,
            selection_reason="BREAKOUT_ATTEMPT",
            sampling_method="CANDIDATE",
        ),
        build_scan_snapshot(
            symbol="XRPUSDT",
            features=decision_time_features(_facts("XRPUSDT")),
            cycle_id=cycle_id,
            candidate=False,
            control=True,
            sampling_method="STRATIFIED_RANDOM",
            selection_probability=0.5,
        ),
    ]
    assert await collector.persist(rows) == 2
    assert await collector.persist(rows) == 0  # idempotent by snapshot_id

    from sqlalchemy import inspect

    async with database.engine.begin() as conn:
        names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
    assert "scan_snapshots" in names


async def test_collector_failure_never_propagates(database) -> None:
    from types import SimpleNamespace

    from crypto_trader.market_data.opportunity.service import OpportunityScannerService

    class ExplodingCollector:
        async def persist(self, rows):
            raise RuntimeError("storage down")

    service = object.__new__(OpportunityScannerService)
    service.snapshot_collector = ExplodingCollector()
    service.control_sample_size = 1
    service.collection_error = None
    service.collection_stats = {}
    candidate = SimpleNamespace(symbol="BTCUSDT", priority=0.9, nominated_reason="BREAKOUT_ATTEMPT")
    facts = {"BTCUSDT": _facts("BTCUSDT"), "ETHUSDT": _facts("ETHUSDT")}
    await service._collect_ml_snapshots([candidate], facts, [], captured_at=datetime.now(UTC))
    assert service.collection_error is not None
    assert service.collection_stats["persisted"] == 0


async def test_collector_persists_candidate_and_control_same_schema(database) -> None:
    from types import SimpleNamespace

    from sqlalchemy import select

    from crypto_trader.market_data.opportunity.service import OpportunityScannerService
    from crypto_trader.persistence.models import ScanSnapshotORM

    service = object.__new__(OpportunityScannerService)
    service.snapshot_collector = ScanSnapshotCollector(database.session_factory)
    service.control_sample_size = 2
    service.collection_error = None
    service.collection_stats = {}
    candidates = [
        SimpleNamespace(symbol="BTCUSDT", priority=0.9, nominated_reason="BREAKOUT_ATTEMPT")
    ]
    facts = {symbol: _facts(symbol) for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")}
    await service._collect_ml_snapshots(candidates, facts, [], captured_at=datetime.now(UTC))
    assert service.collection_error is None
    async with database.session_factory() as session:
        rows = (await session.execute(select(ScanSnapshotORM))).scalars().all()
    assert len(rows) == 3
    assert {row.candidate for row in rows} == {True, False}
    features = [row.features_json for row in rows]
    assert all(item["available_at_decision_time"] is True for item in features)
    assert all(set(item) == set(features[0]) for item in features)  # same schema
