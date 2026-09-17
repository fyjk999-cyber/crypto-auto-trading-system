import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("mlc", ROOT / "scripts/ml_collector.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_horizons_and_no_llm_dependency():
    assert {"1m", "5m", "15m", "30m", "1h", "4h"} <= set(mod.H)
    src = (ROOT / "scripts/ml_collector.py").read_text()
    for bad in ("DEEPSEEK_API_KEY", "GLM_API_KEY", "LLM_MODEL", "TRADING_LLM_MODEL"):
        assert bad not in src


def test_signal_sets_stop_flag():
    mod.STOP = False
    mod._sig(None, None)
    assert mod.STOP is True
    mod.STOP = False


async def test_label_v2_maturity_and_idempotency(database):
    from crypto_trader.ml_labels import STATUS_MATURE_VALID, Candle
    from crypto_trader.persistence.models import ScanSnapshotLabelORM, ScanSnapshotORM

    captured = datetime(2026, 1, 1, tzinfo=UTC)
    captured_ms = int(captured.timestamp() * 1000)
    async with database.session_factory() as s:
        s.add(
            ScanSnapshotORM(
                snapshot_id="s1",
                captured_at=captured,
                cycle_id="c1",
                symbol="BTCUSDT",
                candidate=True,
                control=False,
                features_json={"price": 100.0},
                outcome_status="PENDING",
            )
        )
        await s.commit()

    class Provider:
        async def closed_candles(self, symbol, bar, start_ms, end_ms):
            return [
                Candle(
                    ts_ms=captured_ms,
                    open=100.0,
                    high=101.5,
                    low=99.5,
                    close=101.0,
                    bar_ms=60_000,
                )
            ]

    now = captured + timedelta(minutes=2)
    first = await mod.label(database, Provider(), now)
    assert first[STATUS_MATURE_VALID] == 1
    second = await mod.label(database, Provider(), now)
    assert second[STATUS_MATURE_VALID] == 0
    async with database.session_factory() as s:
        row = (
            await s.execute(
                select(ScanSnapshotLabelORM).where(
                    ScanSnapshotLabelORM.snapshot_id == "s1",
                    ScanSnapshotLabelORM.horizon == "1m",
                )
            )
        ).scalar_one()
    assert row.horizon == "1m"
    assert row.label_version == "label-v2"
    assert row.maturation_status == STATUS_MATURE_VALID
    assert row.usable_for_training is True
    assert round(row.long_gross_bps, 6) == 100.0
    assert round(row.long_net_bps, 6) == 78.0
    assert row.cost_version is not None and row.cost_version.startswith("label-cost-v2")


def test_collector_reuses_canonical_state_feed():
    source = (ROOT / "scripts/ml_collector.py").read_text()
    assert "OKXPublicMarketFeed" in source
    assert "state_provider=lambda symbol: feed.states.get(symbol)" in source
    assert "state_prefetch=prefetch" in source
    assert "OkxHistoricalCandleProvider" in source
    assert "prices(" not in source


async def test_label_observer_receives_truthful_status(database):
    from datetime import UTC, datetime

    from crypto_trader.ml_labels import STATUS_MATURE_VALID, Candle
    from crypto_trader.persistence.models import ScanSnapshotORM

    captured = datetime(2026, 1, 1, tzinfo=UTC)
    async with database.session_factory() as s:
        s.add(
            ScanSnapshotORM(
                snapshot_id="observer",
                captured_at=captured,
                cycle_id="c1",
                symbol="BTCUSDT",
                candidate=True,
                control=False,
                features_json={"price": 100.0},
                outcome_status="PENDING",
            )
        )
        await s.commit()

    class Provider:
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

    observed = []
    counts = await mod.label(
        database, Provider(), captured + timedelta(days=1), observer=observed.append
    )
    assert counts[STATUS_MATURE_VALID] == 6
    assert observed[-1]["snapshot_id"] == "observer"
    assert observed[-1]["symbol"] == "BTCUSDT"
    assert observed[-1]["horizon"] == "4h"
    assert observed[-1]["status"] == STATUS_MATURE_VALID
