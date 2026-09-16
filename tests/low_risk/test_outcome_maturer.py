# ruff: noqa: E402
from datetime import UTC, datetime, timedelta

from sqlalchemy import select


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=UTC)


from crypto_trader.market_data.opportunity.outcome_maturer import (
    evaluate_horizon,
    mature_due,
)
from crypto_trader.persistence.models import (
    OpportunityOutcomeMaturationORM,
    ScanSnapshotORM,
)


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    async def get_candles(self, inst_id, bar, limit=300, **kwargs):
        return self.rows


def _rows(start, minutes, start_price=100.0, step=0.01):
    out = []
    for i in range(minutes):
        ts = int((start + timedelta(minutes=i)).timestamp() * 1000)
        price = start_price + i * step
        out.append(
            [
                str(ts),
                str(price),
                str(price + 0.05),
                str(price - 0.05),
                str(price),
                "1",
                "1",
                "1",
                "1",
            ]
        )
    return out


def test_evaluate_horizon_mirror_and_no_direction_label():
    metrics = evaluate_horizon(
        entry_price=100.0,
        target_price=101.0,
        highs=[100.2, 100.3, 101.5, 101.6],
        lows=[99.8, 99.6, 100.2, 100.9],
        closes=[100.0, 99.9, 100.5, 101.0],
        expected_direction=None,
        all_in_cost_bps=22.0,
        direction_source="NONE",
    )
    assert round(metrics["long_gross_bps"], 4) == 100.0
    assert round(metrics["short_gross_bps"], 4) == -100.0
    assert round(metrics["long_net_bps"], 4) == 78.0
    assert metrics["future_high"] == 101.6 and metrics["future_low"] == 99.6
    assert metrics["mfe_bps"] > 0 and metrics["mae_bps"] < 0
    assert metrics["label"] is None


def test_evaluate_horizon_direction_label_requires_factual_source():
    good = evaluate_horizon(
        entry_price=100.0,
        target_price=101.0,
        highs=[101.0],
        lows=[100.0],
        closes=[100.5, 101.0],
        expected_direction="LONG",
        all_in_cost_bps=10.0,
        direction_source="CORE_LLM",
    )
    assert good["label"] == "DIRECTION_CORRECT"
    bad = evaluate_horizon(
        entry_price=100.0,
        target_price=99.0,
        highs=[100.0],
        lows=[99.0],
        closes=[99.5, 99.0],
        expected_direction="LONG",
        all_in_cost_bps=10.0,
        direction_source="EVIDENCE_REFERENCE",
    )
    assert bad["label"] == "DIRECTION_WRONG"


def _obs(sid, captured, price=100.0, extra=None):
    features = {"price": price, "costs": {"total_cost_bps": 22.0}}
    if extra:
        features.update(extra)
    return ScanSnapshotORM(
        snapshot_id=sid,
        captured_at=captured,
        cycle_id="c",
        trading_day=captured.date().isoformat(),
        snapshot_version="scan-snapshot-v1",
        snapshot_hash=f"h-{sid}",
        symbol="BTCUSDT",
        candidate=True,
        control=False,
        scanner_score=1.0,
        selection_reason="FACTOR_SCANNER",
        features_json=features,
    )


async def test_mature_due_exact_horizon_and_idempotent(database):
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    captured = now - timedelta(hours=2)
    async with database.session_factory() as session:
        session.add(_obs("obs-1", captured))
        await session.commit()
    client = FakeClient(_rows(captured - timedelta(minutes=5), 180))
    first = await mature_due(database.session_factory, client, now=now, horizons={"1h": 3600})
    assert first["written"] == 1 and first["by_direction_source"].get("NONE") == 1
    async with database.session_factory() as session:
        row = (await session.execute(select(OpportunityOutcomeMaturationORM))).scalars().first()
    assert row.expected_direction is None and row.label is None
    assert row.alignment_ok is True and row.path_end_ts == row.actual_target_ts
    assert (
        abs((_aware(row.actual_target_ts) - (captured + timedelta(hours=1))).total_seconds()) <= 60
    )
    assert row.long_net_bps > 0
    second = await mature_due(database.session_factory, client, now=now, horizons={"1h": 3600})
    assert second["written"] == 0 and second["skipped_existing"] == 1


async def test_horizons_use_their_own_factual_paths(database):
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    captured = now - timedelta(hours=2)
    async with database.session_factory() as session:
        session.add(_obs("obs-2", captured))
        await session.commit()
    client = FakeClient(_rows(captured - timedelta(minutes=5), 180))
    await mature_due(database.session_factory, client, now=now, horizons={"15m": 900, "1h": 3600})
    async with database.session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(OpportunityOutcomeMaturationORM).order_by(
                        OpportunityOutcomeMaturationORM.horizon
                    )
                )
            )
            .scalars()
            .all()
        )
    by_horizon = {row.horizon: row for row in rows}
    assert len(rows) == 2
    assert _aware(by_horizon["15m"].requested_target_ts) == captured + timedelta(minutes=15)
    assert _aware(by_horizon["1h"].requested_target_ts) == captured + timedelta(hours=1)
    assert _aware(by_horizon["15m"].actual_target_ts) < _aware(by_horizon["1h"].actual_target_ts)
    assert by_horizon["15m"].target_price < by_horizon["1h"].target_price
    assert _aware(by_horizon["15m"].path_end_ts) < _aware(by_horizon["1h"].path_end_ts)


async def test_missed_maturity_reconstructs_history_not_current_price(database):
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    captured = now - timedelta(hours=30)
    async with database.session_factory() as session:
        session.add(_obs("obs-3", captured))
        await session.commit()
    client = FakeClient(_rows(captured - timedelta(minutes=5), 1500))
    result = await mature_due(database.session_factory, client, now=now, horizons={"24h": 86400})
    assert result["written"] == 1
    async with database.session_factory() as session:
        row = (await session.execute(select(OpportunityOutcomeMaturationORM))).scalars().first()
    assert (
        abs((_aware(row.actual_target_ts) - (captured + timedelta(hours=24))).total_seconds()) <= 60
    )
    assert (now - _aware(row.actual_target_ts)).total_seconds() > 5 * 3600
    assert row.label is None


async def test_unaligned_gap_is_flagged(database):
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    captured = now - timedelta(hours=2)
    async with database.session_factory() as session:
        session.add(_obs("obs-4", captured))
        await session.commit()
    rows = _rows(captured, 1) + _rows(captured + timedelta(minutes=30), 1)
    result = await mature_due(
        database.session_factory, FakeClient(rows), now=now, horizons={"1h": 3600}
    )
    assert result["written"] == 1 and result["unaligned"] == 1
    async with database.session_factory() as session:
        row = (await session.execute(select(OpportunityOutcomeMaturationORM))).scalars().first()
    assert row.alignment_ok is False and row.alignment_error_seconds > 120


class _PagedClient:
    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda row: int(row[0]))

    async def get_candles(self, inst_id, bar, limit=300, after=None, **kwargs):
        if after is None:
            return self.rows[-limit:]
        older = [row for row in self.rows if int(row[0]) <= int(after)]
        return older[-limit:]


async def test_post_horizon_spike_cannot_affect_path_or_metrics(database):
    from crypto_trader.market_data.opportunity.outcome_maturer import _load_candles  # noqa: F401

    now = datetime(2026, 9, 16, 4, 0, tzinfo=UTC)
    captured = now - timedelta(hours=2)
    rows = _rows(captured - timedelta(minutes=5), 180)
    spike_index = 75  # candle opening at captured+70m, beyond the 1h horizon
    rows[spike_index][2] = "500.0"
    rows[spike_index][3] = "50.0"
    rows[spike_index][4] = "400.0"
    async with database.session_factory() as session:
        session.add(_obs("obs-strict", captured))
        await session.commit()
    result = await mature_due(
        database.session_factory, FakeClient(rows), now=now, horizons={"1h": 3600}
    )
    assert result["written"] == 1
    async with database.session_factory() as session:
        row = (await session.execute(select(OpportunityOutcomeMaturationORM))).scalars().first()
    assert row.future_high < 200.0  # post-horizon spike excluded
    assert row.endpoint_policy == "CLOSED_BAR_END_LE_TARGET"
    assert row.final_bar_partial is False
    assert _aware(row.actual_target_ts) <= captured + timedelta(hours=1)


async def test_historical_pagination_reconstructs_beyond_300_bars():
    from crypto_trader.market_data.opportunity.outcome_maturer import _load_candles

    start = datetime(2026, 9, 16, 0, 0, tzinfo=UTC)
    target = start + timedelta(hours=8)
    rows = _rows(start - timedelta(minutes=5), 8 * 60 + 10)
    candles, pages, data_gap, transient = await _load_candles(
        _PagedClient(rows), {}, "BTCUSDT", "1m", start, target
    )
    assert transient is False
    assert pages >= 2
    assert data_gap is False
    assert candles[0].ts <= start
    assert candles[-1].ts >= target - timedelta(minutes=1)
    timestamps = [candle.ts for candle in candles]
    assert len(timestamps) == len(set(timestamps))


async def test_due_work_queue_never_starves_tail_observations(database):
    from datetime import timedelta as _td

    now = datetime(2026, 9, 16, 4, 0, tzinfo=UTC)
    rows = _rows(now - _td(hours=2) - _td(minutes=5), 180)
    async with database.session_factory() as session:
        for i in range(600):
            session.add(
                ScanSnapshotORM(
                    snapshot_id=f"obs-{i}",
                    captured_at=now - _td(hours=2),
                    cycle_id="c",
                    trading_day="2026-09-15",
                    snapshot_version="scan-snapshot-v1",
                    symbol="BTCUSDT",
                    candidate=True,
                    control=False,
                    scanner_score=1.0,
                    features_json={"price": 100.0, "costs": {"total_cost_bps": 22.0}},
                )
            )
        for i in range(500):
            session.add(
                OpportunityOutcomeMaturationORM(
                    observation_id=f"obs-{i}",
                    symbol="BTCUSDT",
                    horizon="1h",
                    outcome_version="outcome-v1",
                    maturation_status="MATURE_VALID",
                    usable_for_learning=True,
                    alignment_ok=True,
                    data_gap=False,
                )
            )
        await session.commit()
    result = await mature_due(
        database.session_factory,
        FakeClient(rows),
        now=now,
        horizons={"1h": 3600},
        max_work_items=25,
    )
    assert result["due_work_items"] == 25 and result["written"] == 25
    async with database.session_factory() as session:
        written = (
            (
                await session.execute(
                    select(OpportunityOutcomeMaturationORM.observation_id).where(
                        OpportunityOutcomeMaturationORM.id > 500
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(written) == 25
    assert all(int(observation.split("-")[1]) >= 500 for observation in written)


async def test_configured_work_budget_is_exactly_enforced(database):
    from datetime import timedelta as _td

    now = datetime(2026, 9, 16, 4, 0, tzinfo=UTC)
    rows = _rows(now - _td(hours=2) - _td(minutes=5), 180)
    async with database.session_factory() as session:
        for i in range(30):
            session.add(
                ScanSnapshotORM(
                    snapshot_id=f"batch-{i}",
                    captured_at=now - _td(hours=2),
                    cycle_id="c",
                    trading_day="2026-09-15",
                    snapshot_version="scan-snapshot-v1",
                    symbol="BTCUSDT",
                    candidate=True,
                    control=False,
                    scanner_score=1.0,
                    features_json={"price": 100.0, "costs": {"total_cost_bps": 22.0}},
                )
            )
        await session.commit()
    result = await mature_due(
        database.session_factory, FakeClient(rows), now=now, horizons={"1h": 3600}, max_work_items=7
    )
    assert result["due_work_items"] == 7 and result["written"] == 7
