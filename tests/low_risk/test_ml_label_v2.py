"""M1 label-v2 exact factual maturer tests (LEARNING_ONLY)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from crypto_trader import ml_labels
from crypto_trader.ml_labels import (
    Candle,
    LabelV2Maturer,
    OkxHistoricalCandleProvider,
    TransientSourceError,
)
from crypto_trader.persistence.models import ScanSnapshotLabelORM, ScanSnapshotORM

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _snap(snapshot_id="s1", *, ts=T0, symbol="BTCUSDT", price=100.0, costs=None):
    features = {"price": price}
    if costs is not None:
        features["costs"] = costs
    return ScanSnapshotORM(
        snapshot_id=snapshot_id,
        captured_at=ts,
        cycle_id="c1",
        symbol=symbol,
        candidate=True,
        control=False,
        features_json=features,
    )


class FakeProvider:
    def __init__(self, candles_by_key=None, *, fail_once=False, fail_keys_once=None):
        self.candles_by_key = candles_by_key or {}
        self.fail_once = fail_once
        self.fail_keys_once = set(fail_keys_once or ())
        self.calls = 0

    async def closed_candles(self, symbol, bar, start_ms, end_ms):
        self.calls += 1
        key = (symbol, bar, end_ms)
        if key in self.fail_keys_once:
            self.fail_keys_once.discard(key)
            raise TransientSourceError("TEST_TRANSIENT")
        if self.fail_once and self.calls == 1:
            raise TransientSourceError("TEST_TRANSIENT")
        return list(self.candles_by_key.get(key, []))


async def _seed(database, snap):
    async with database.session_factory() as s:
        s.add(snap)
        await s.commit()


async def test_exact_horizon_and_strict_no_lookahead(database, tmp_path) -> None:
    await _seed(database, _snap(costs={"total_cost_bps": 12.0}))
    target_ms = int((T0 + timedelta(minutes=15)).timestamp() * 1000)
    endpoint = Candle(
        ts_ms=int(T0.timestamp() * 1000),
        open=100.0,
        high=102.5,
        low=99.0,
        close=102.0,
        bar_ms=900_000,
    )
    provider = FakeProvider(candles_by_key={("BTCUSDT", "15m", target_ms): [endpoint]})
    maturer = LabelV2Maturer()
    counts = await maturer.mature_pending(
        database.session_factory, provider, now=T0 + timedelta(hours=1)
    )
    assert counts["MATURE_VALID"] == 1
    async with database.session_factory() as s:
        row = (
            await s.execute(
                select(ScanSnapshotLabelORM).where(
                    ScanSnapshotLabelORM.horizon == "15m",
                    ScanSnapshotLabelORM.label_version == "label-v2",
                )
            )
        ).scalar_one()
    assert row.usable_for_training is True
    assert row.requested_target_ts.replace(tzinfo=UTC) == T0 + timedelta(minutes=15)
    assert row.actual_target_ts.replace(tzinfo=UTC) == T0 + timedelta(minutes=15)
    assert row.alignment_error_seconds == 0.0
    assert row.endpoint_policy == ml_labels.ENDPOINT_POLICY
    assert row.future_high == 102.5 and row.future_low == 99.0
    assert round(row.long_gross_bps, 6) == 200.0
    assert round(row.long_net_bps, 6) == 188.0
    assert round(row.short_gross_bps, 6) == -200.0
    assert row.cost_version == ml_labels.COST_VERSION_DECISION
    assert row.long_label == "PROFITABLE"

    # A post-horizon spike candle (close strictly after target) cannot change it.
    spike = Candle(
        ts_ms=int((T0 + timedelta(minutes=15)).timestamp() * 1000),
        open=102.0,
        high=150.0,
        low=101.0,
        close=149.0,
        bar_ms=900_000,
    )
    with_spike = maturer.build_label(
        _snap(costs={"total_cost_bps": 12.0}),
        "15m",
        candles=[endpoint, spike],
        now=T0 + timedelta(hours=1),
    )
    assert with_spike.maturity_status == ml_labels.STATUS_MATURE_VALID
    assert round(with_spike.long_gross_bps, 6) == 200.0
    assert with_spike.future_high == 102.5  # spike excluded


async def test_data_gap_and_alignment_are_inconclusive(database) -> None:
    await _seed(database, _snap(snapshot_id="gap"))
    result = LabelV2Maturer().build_label(
        _snap(snapshot_id="gap"), "15m", candles=[], now=T0 + timedelta(hours=1)
    )
    assert result.maturity_status == ml_labels.STATUS_INCONCLUSIVE_DATA_GAP
    assert result.usable_for_training is False

    # Enough bars to pass gap detection, but the latest closed candle ends
    # materially before target -> alignment inconclusive (never stale-price use).
    late_gap = [
        Candle(
            ts_ms=int((T0 + timedelta(minutes=i)).timestamp() * 1000),
            open=100,
            high=101,
            low=99,
            close=100,
            bar_ms=60_000,
        )
        for i in range(12)
    ]
    result2 = LabelV2Maturer().build_label(
        _snap(snapshot_id="align"), "15m", candles=late_gap, now=T0 + timedelta(hours=1)
    )
    assert result2.maturity_status == ml_labels.STATUS_INCONCLUSIVE_ALIGNMENT


async def test_transient_retry_and_duplicate_idempotency(database) -> None:
    await _seed(database, _snap(snapshot_id="retry"))
    target_ms = int((T0 + timedelta(minutes=5)).timestamp() * 1000)
    candle = Candle(
        ts_ms=int(T0.timestamp() * 1000), open=100, high=101, low=99, close=101, bar_ms=60_000
    )
    # 5m horizon: one 5m endpoint bar is exactly expected.
    endpoint_5m = Candle(
        ts_ms=int(T0.timestamp() * 1000), open=100, high=101, low=99, close=101, bar_ms=300_000
    )
    provider = FakeProvider(
        candles_by_key={
            ("BTCUSDT", "5m", target_ms): [endpoint_5m, candle],
        },
        fail_keys_once=[("BTCUSDT", "5m", target_ms)],
    )
    maturer = LabelV2Maturer()
    first = await maturer.mature_pending(
        database.session_factory, provider, now=T0 + timedelta(hours=5)
    )
    assert first[ml_labels.STATUS_TRANSIENT_SOURCE_ERROR] >= 1
    second = await maturer.mature_pending(
        database.session_factory, provider, now=T0 + timedelta(hours=5)
    )
    assert second[ml_labels.STATUS_MATURE_VALID] >= 1
    async with database.session_factory() as s:
        v2 = int(
            await s.scalar(
                select(func.count())
                .select_from(ScanSnapshotLabelORM)
                .where(ScanSnapshotLabelORM.label_version == "label-v2")
            )
        )
        retry_row = (
            await s.execute(
                select(ScanSnapshotLabelORM).where(
                    ScanSnapshotLabelORM.snapshot_id == "retry",
                    ScanSnapshotLabelORM.horizon == "5m",
                )
            )
        ).scalar_one()
    assert v2 == 6
    assert retry_row.maturation_status == ml_labels.STATUS_MATURE_VALID
    third = await maturer.mature_pending(
        database.session_factory, provider, now=T0 + timedelta(hours=5)
    )
    assert third[ml_labels.STATUS_MATURE_VALID] == 0
    async with database.session_factory() as s:
        assert (
            int(
                await s.scalar(
                    select(func.count())
                    .select_from(ScanSnapshotLabelORM)
                    .where(ScanSnapshotLabelORM.label_version == "label-v2")
                )
            )
            == 6
        )


async def test_cost_versioning_is_explicit_when_missing(database) -> None:
    await _seed(database, _snap(snapshot_id="nocost"))
    endpoint = Candle(
        ts_ms=int(T0.timestamp() * 1000), open=100, high=101, low=99, close=101, bar_ms=300_000
    )
    provider = FakeProvider(
        candles_by_key={
            ("BTCUSDT", "5m", int((T0 + timedelta(minutes=5)).timestamp() * 1000)): [endpoint]
        }
    )
    await LabelV2Maturer().mature_pending(
        database.session_factory, provider, now=T0 + timedelta(hours=1)
    )
    async with database.session_factory() as s:
        row = (
            await s.execute(
                select(ScanSnapshotLabelORM).where(
                    ScanSnapshotLabelORM.snapshot_id == "nocost",
                    ScanSnapshotLabelORM.horizon == "5m",
                )
            )
        ).scalar_one()
    assert row.cost_version == ml_labels.COST_VERSION_ESTIMATE
    assert row.cost_components_json["quality"] == "estimated_missing"


async def test_historical_pagination_beyond_300_bars() -> None:
    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def get_history_candles(self, inst_id, bar, *, before=None, limit=100):
            self.calls += 1
            rows = []
            for i in range(limit):
                ts = int(before) - 1 - i * 60_000
                confirm = "1" if i % 10 != 9 else "0"  # unconfirmed rows must be dropped
                rows.append([str(ts), "100", "101", "99", "100.5", "1", "1", "1", confirm])
            return rows

    client = FakeClient()
    provider = OkxHistoricalCandleProvider(
        client, page_limit=100, max_pages=8, page_delay_seconds=0
    )
    end_ms = 1_800_000_000_000
    candles = await provider.closed_candles("BTCUSDT", "1m", end_ms - 500 * 60_000, end_ms)
    assert client.calls > 3
    assert len(candles) > 300
    assert all(c.confirm for c in candles)
    assert [c.ts_ms for c in candles] == sorted(c.ts_ms for c in candles)
    assert len({c.ts_ms for c in candles}) == len(candles)
    # window-aware cache: second call should not hit the client again
    calls_before = client.calls
    await provider.closed_candles("BTCUSDT", "1m", end_ms - 500 * 60_000, end_ms)
    assert client.calls == calls_before
