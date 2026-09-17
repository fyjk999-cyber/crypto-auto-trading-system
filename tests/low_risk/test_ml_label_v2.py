"""M1 label-v2 exact factual maturer tests (LEARNING_ONLY)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
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


async def test_okx_history_pagination_uses_after_and_moves_backward() -> None:
    class FakeClient:
        def __init__(self):
            self.calls: list[tuple[int | None, int | None]] = []

        async def get_history_candles(
            self, inst_id, bar, *, after=None, before=None, limit=100
        ):
            self.calls.append((after, before))
            rows = []
            if after is not None:
                # Empirical OKX semantics: after=X returns rows earlier than X.
                base = int(after) - 1
                for i in range(limit):
                    ts = base - i * 60_000
                    confirm = "1" if i % 10 != 9 else "0"
                    rows.append([str(ts), "100", "101", "99", "100.5", "1", "1", "1", confirm])
                return rows
            if before is not None:
                # before=X returns rows newer than X (provider must never use it).
                base = int(before) + 1
                for i in range(limit):
                    ts = base + i * 60_000
                    rows.append([str(ts), "100", "101", "99", "100.5", "1", "1", "1", "1"])
                return rows
            return []

    client = FakeClient()
    provider = OkxHistoricalCandleProvider(
        client, page_limit=100, max_pages=8, page_delay_seconds=0
    )
    end_ms = 1_800_000_000_000
    candles = await provider.closed_candles("BTCUSDT", "1m", end_ms - 500 * 60_000, end_ms)

    assert client.calls
    assert all(after is not None and before is None for after, before in client.calls)
    cursors = [after for after, _before in client.calls if after is not None]
    assert all(cursors[i] < cursors[i - 1] for i in range(1, len(cursors)))
    assert all(c.ts_ms <= end_ms for c in candles)
    assert all(c.ts_ms >= end_ms - 500 * 60_000 for c in candles)
    assert len(candles) > 300
    assert all(c.confirm for c in candles)
    assert [c.ts_ms for c in candles] == sorted(c.ts_ms for c in candles)
    assert len({c.ts_ms for c in candles}) == len(candles)

    # window-aware cache: second call should not hit the client again
    calls_before = list(client.calls)
    await provider.closed_candles("BTCUSDT", "1m", end_ms - 500 * 60_000, end_ms)
    assert client.calls == calls_before
    assert provider.stats()["history_cache_hits"] >= 1


async def test_mid_bar_t0_endpoint_without_pre_t0_path_contamination() -> None:
    t0 = datetime(2026, 1, 1, 11, 50, 15, 500713, tzinfo=UTC)
    bar_ms = 60_000
    t0_ms = int(t0.timestamp() * 1000)
    bar_start_ms = (t0_ms // bar_ms) * bar_ms
    covering = Candle(
        ts_ms=bar_start_ms,
        open=100.0,
        high=130.0,
        low=70.0,
        close=101.0,
        bar_ms=bar_ms,
    )
    snap = _snap(snapshot_id="midbar", ts=t0, price=100.0, costs={"total_cost_bps": 1.0})
    result = LabelV2Maturer().build_label(
        snap, "1m", candles=[covering], now=t0 + timedelta(minutes=5)
    )
    assert result.maturity_status == ml_labels.STATUS_MATURE_VALID
    assert result.usable_for_training is True
    assert result.entry_price == 100.0
    assert result.partial_start_bar is True
    assert result.path_quality == ml_labels.PATH_QUALITY_UNAVAILABLE_PARTIAL_START
    assert result.endpoint_quality == ml_labels.ENDPOINT_QUALITY_CLOSED
    assert result.raw_t0 == t0
    assert result.aligned_bar_start == datetime.fromtimestamp(bar_start_ms / 1000, tz=UTC)
    assert result.actual_target_ts == datetime.fromtimestamp(
        (bar_start_ms + bar_ms) / 1000, tz=UTC
    )
    assert result.alignment_error_seconds == pytest.approx(15.500713, abs=0.001)
    assert result.future_high is None
    assert result.future_low is None
    assert result.realized_volatility is None

    # A candle that closes after the requested target must never become endpoint.
    future = Candle(
        ts_ms=bar_start_ms + bar_ms,
        open=101.0,
        high=140.0,
        low=80.0,
        close=139.0,
        bar_ms=bar_ms,
    )
    result_future = LabelV2Maturer().build_label(
        snap, "1m", candles=[future], now=t0 + timedelta(minutes=5)
    )
    assert result_future.maturity_status == ml_labels.STATUS_INCONCLUSIVE_DATA_GAP


async def test_exact_bar_boundary_keeps_full_post_t0_path() -> None:
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    endpoint = Candle(
        ts_ms=int(t0.timestamp() * 1000),
        open=100.0,
        high=105.0,
        low=95.0,
        close=102.0,
        bar_ms=900_000,
    )
    result = LabelV2Maturer().build_label(
        _snap(ts=t0, price=100.0),
        "15m",
        candles=[endpoint],
        now=t0 + timedelta(hours=2),
    )
    assert result.maturity_status == ml_labels.STATUS_MATURE_VALID
    assert result.partial_start_bar is False
    assert result.path_quality == ml_labels.PATH_QUALITY_FULL
    assert result.future_high == 105.0
    assert result.future_low == 95.0


async def test_completed_snapshot_commits_before_later_snapshot_failure(database) -> None:
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    await _seed(database, _snap(snapshot_id="first", ts=t0))
    await _seed(database, _snap(snapshot_id="second", ts=t0 + timedelta(minutes=1)))

    class LaterFailureProvider:
        def __init__(self):
            self.calls = 0

        async def closed_candles(self, symbol, bar, start_ms, end_ms):
            self.calls += 1
            if self.calls > 6:
                raise RuntimeError("simulated later snapshot failure")
            return [
                Candle(
                    ts_ms=start_ms,
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=101.0,
                    bar_ms=end_ms - start_ms,
                )
            ]

    with pytest.raises(RuntimeError):
        await LabelV2Maturer().mature_pending(
            database.session_factory,
            LaterFailureProvider(),
            now=t0 + timedelta(days=1),
            limit=2,
        )

    async with database.session_factory() as s:
        first_rows = int(
            await s.scalar(
                select(func.count())
                .select_from(ScanSnapshotLabelORM)
                .where(
                    ScanSnapshotLabelORM.snapshot_id == "first",
                    ScanSnapshotLabelORM.label_version == "label-v2",
                )
            )
        )
        second_rows = int(
            await s.scalar(
                select(func.count())
                .select_from(ScanSnapshotLabelORM)
                .where(
                    ScanSnapshotLabelORM.snapshot_id == "second",
                    ScanSnapshotLabelORM.label_version == "label-v2",
                )
            )
        )
    assert first_rows == 6
    assert second_rows == 0


async def test_backlog_recovers_and_label_v1_is_preserved(database) -> None:
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    await _seed(database, _snap(snapshot_id="backlog", ts=t0, price=100.0))
    async with database.session_factory() as s:
        s.add(
            ScanSnapshotLabelORM(
                snapshot_id="backlog",
                symbol="BTCUSDT",
                snapshot_ts=t0,
                horizon="1h",
                feature_version="scan-features-v1",
                label_version="label-v1",
                long_label="PROFITABLE",
                short_label="NOT_PROFITABLE",
                matured_at=t0,
            )
        )
        await s.commit()

    class BoundaryProvider:
        async def closed_candles(self, symbol, bar, start_ms, end_ms):
            return [
                Candle(
                    ts_ms=start_ms,
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=101.0,
                    bar_ms=end_ms - start_ms,
                )
            ]

    counts = await LabelV2Maturer().mature_pending(
        database.session_factory, BoundaryProvider(), now=t0 + timedelta(days=1)
    )
    assert counts[ml_labels.STATUS_MATURE_VALID] == 6
    async with database.session_factory() as s:
        label_v1_count = int(
            await s.scalar(
                select(func.count())
                .select_from(ScanSnapshotLabelORM)
                .where(ScanSnapshotLabelORM.label_version == "label-v1")
            )
        )
        label_v2_count = int(
            await s.scalar(
                select(func.count())
                .select_from(ScanSnapshotLabelORM)
                .where(ScanSnapshotLabelORM.label_version == "label-v2")
            )
        )
        snapshot = (
            await s.execute(
                select(ScanSnapshotORM).where(ScanSnapshotORM.snapshot_id == "backlog")
            )
        ).scalar_one()
    assert label_v1_count == 1
    assert label_v2_count == 6
    assert snapshot.outcome_status == "LABELED"


async def test_backlog_advances_past_terminal_inconclusive_snapshot(database) -> None:
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    await _seed(database, _snap(snapshot_id="bad", ts=t0, symbol="BADUSDT"))
    await _seed(
        database,
        _snap(snapshot_id="good", ts=t0 + timedelta(minutes=10), symbol="BTCUSDT"),
    )

    class MixedProvider:
        async def closed_candles(self, symbol, bar, start_ms, end_ms):
            if symbol == "BADUSDT":
                return []
            return [
                Candle(
                    ts_ms=start_ms,
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=101.0,
                    bar_ms=end_ms - start_ms,
                )
            ]

    counts = await LabelV2Maturer().mature_pending(
        database.session_factory, MixedProvider(), now=t0 + timedelta(days=1), limit=2
    )
    assert counts[ml_labels.STATUS_INCONCLUSIVE_DATA_GAP] == 6
    assert counts[ml_labels.STATUS_MATURE_VALID] == 6
    async with database.session_factory() as s:
        bad = (
            await s.execute(
                select(ScanSnapshotORM).where(ScanSnapshotORM.snapshot_id == "bad")
            )
        ).scalar_one()
        good = (
            await s.execute(
                select(ScanSnapshotORM).where(ScanSnapshotORM.snapshot_id == "good")
            )
        ).scalar_one()
    assert bad.outcome_status == "LABELED"
    assert good.outcome_status == "LABELED"


async def test_provider_fetches_bar_covering_mid_bar_start() -> None:
    class FakeClient:
        def __init__(self):
            self.after = None

        async def get_history_candles(self, inst_id, bar, *, after=None, before=None, limit=100):
            self.after = after
            base = ((int(after) - 1) // 60_000) * 60_000
            rows = []
            for i in range(limit):
                ts = base - i * 60_000
                rows.append([str(ts), "100", "101", "99", "100.5", "1", "1", "1", "1"])
            return rows

    t0 = datetime(2026, 1, 1, 12, 0, 22, 762831, tzinfo=UTC)
    start_ms = int(t0.timestamp() * 1000)
    end_ms = start_ms + 60_000
    client = FakeClient()
    provider = OkxHistoricalCandleProvider(
        client, page_limit=100, max_pages=4, page_delay_seconds=0
    )
    candles = await provider.closed_candles("BTCUSDT", "1m", start_ms, end_ms)
    covering_start_ms = (start_ms // 60_000) * 60_000
    assert client.after == end_ms + 1
    assert any(c.ts_ms == covering_start_ms for c in candles)
    assert all(covering_start_ms <= c.ts_ms <= end_ms for c in candles)
