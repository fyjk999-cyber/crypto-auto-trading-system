from datetime import UTC, datetime, timedelta

from crypto_trader.market_data.opportunity.ledger_freeze import (
    freeze_completed_day,
    latest_completed_trading_day,
)
from crypto_trader.market_data.opportunity.snapshots import build_scan_snapshot
from crypto_trader.persistence.models import (
    DailyOpportunityTop10ORM,
    ScanSnapshotORM,
)


def _obs(i, day, symbol, score, candidate=True):
    return ScanSnapshotORM(
        snapshot_id=f"obs-{i}",
        captured_at=datetime(2026, 9, 15, 1, 0, tzinfo=UTC) + timedelta(minutes=i),
        cycle_id="c",
        trading_day=day,
        snapshot_version="scan-snapshot-v1",
        snapshot_hash=f"hash-{i}",
        symbol=symbol,
        candidate=candidate,
        control=not candidate,
        scanner_score=score,
        scanner_rank=i,
        selection_reason="FACTOR_SCANNER",
        features_json={"price": 100.0 + i},
    )


def test_snapshot_builder_timezone_and_hash():
    features = {"price": 100.0, "l1_imbalance": 0.2}
    late = build_scan_snapshot(
        symbol="BTCUSDT",
        features=features,
        captured_at=datetime(2026, 9, 16, 16, 30, tzinfo=UTC),
        candidate=True,
        control=False,
    )
    assert late["trading_day"] == "2026-09-17"
    assert len(late["snapshot_hash"]) == 64
    same = build_scan_snapshot(
        symbol="X",
        features=features,
        captured_at=datetime(2026, 9, 16, 10, 0, tzinfo=UTC),
        candidate=False,
        control=True,
    )
    assert same["snapshot_hash"] == late["snapshot_hash"]
    other = build_scan_snapshot(
        symbol="X", features={"price": 101.0}, candidate=False, control=True
    )
    assert other["snapshot_hash"] != late["snapshot_hash"]


def test_latest_completed_day_boundary():
    assert latest_completed_trading_day(datetime(2026, 9, 16, 16, 30, tzinfo=UTC)) == "2026-09-16"
    assert latest_completed_trading_day(datetime(2026, 9, 16, 15, 0, tzinfo=UTC)) == "2026-09-15"


async def test_completed_day_freeze_is_observation_level_and_immutable(database):
    day = "2026-09-15"
    async with database.session_factory() as session:
        session.add(_obs(1, day, "BTCUSDT", 100.0))
        session.add(_obs(2, day, "BTCUSDT", 99.0))
        for i in range(3, 13):
            session.add(_obs(i, day, f"S{i}USDT", 100.0 - i))
        session.add(_obs(99, day, "CTRLUSDT", 999.0, candidate=False))
        await session.commit()

    first = await freeze_completed_day(database.session_factory, day)
    assert first["status"] == "FROZEN" and first["count"] == 10
    assert first["observation_ids"][0] == "obs-1"
    assert first["observation_ids"][1] == "obs-2"  # same symbol twice is allowed
    from sqlalchemy import select as sa_select

    async with database.session_factory() as session:
        rows = (
            (
                await session.execute(
                    sa_select(DailyOpportunityTop10ORM).order_by(DailyOpportunityTop10ORM.rank)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 10
    assert rows[0].evidence_package_json["snapshot_hash"] == "hash-1"
    assert all(row.symbol != "CTRLUSDT" for row in rows)

    async with database.session_factory() as session:
        session.add(_obs(100, day, "LATEUSDT", 9999.0))
        await session.commit()
    again = await freeze_completed_day(database.session_factory, day)
    assert again["status"] == "ALREADY_FROZEN" and again["count"] == 10
    async with database.session_factory() as session:
        rows2 = (
            (
                await session.execute(
                    sa_select(DailyOpportunityTop10ORM).order_by(DailyOpportunityTop10ORM.rank)
                )
            )
            .scalars()
            .all()
        )
    assert [row.observation_id for row in rows2] == first["observation_ids"]
