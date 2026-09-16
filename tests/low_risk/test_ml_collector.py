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


async def test_label_maturity_and_idempotency(database):
    from crypto_trader.persistence.models import ScanSnapshotLabelORM, ScanSnapshotORM

    async with database.session_factory() as s:
        s.add(
            ScanSnapshotORM(
                snapshot_id="s1",
                captured_at=datetime.now(UTC),
                cycle_id="c1",
                symbol="BTCUSDT",
                candidate=True,
                control=False,
                features_json={"price": 100.0},
                outcome_status="PENDING",
            )
        )
        await s.commit()
    now = datetime.now(UTC) + timedelta(minutes=2)
    assert await mod.label(database, {"BTCUSDT": 101.0}, now) == 1
    assert await mod.label(database, {"BTCUSDT": 101.0}, now) == 0
    async with database.session_factory() as s:
        rows = (await s.execute(select(ScanSnapshotLabelORM))).scalars().all()
    assert [r.horizon for r in rows] == ["1m"]
    assert rows[0].long_net_bps == 78.0
    assert rows[0].label_version == "label-v1"
