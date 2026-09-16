# ruff: noqa: E402
# Autonomous Growth worker loop (no LLM, no orders, restart-safe).
import asyncio
import os
import signal
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from crypto_trader.exchange.okx import OKXAdapter
from crypto_trader.learning.growth_worker import GrowthWorker
from crypto_trader.persistence import Database

STOP = False


def _sig(*_):
    global STOP
    STOP = True


async def main(db_path: str, growth_dir: str, interval: float) -> None:
    database = Database(f"sqlite+aiosqlite:///{db_path}")
    await database.init_schema()
    worker = GrowthWorker(
        database.session_factory,
        growth_dir,
        OKXAdapter(),
        code_sha=os.environ.get("RUNNING_SHA", ""),
        scan_source_db=os.environ.get("GROWTH_SCAN_SOURCE_DB"),
    )
    while not STOP:
        try:
            await worker.run_once()
        except Exception as exc:
            worker._save(state="DEGRADED", last_error=f"{type(exc).__name__}: {exc}"[:200])
        await asyncio.sleep(interval)
    worker._save(state="STOPPED")
    await database.close()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    db = sys.argv[1] if len(sys.argv) > 1 else "data/ml/scan_dataset.db"
    growth = sys.argv[2] if len(sys.argv) > 2 else "data/growth"
    interval = float(sys.argv[3]) if len(sys.argv) > 3 else 300.0
    asyncio.run(main(db, growth, interval))
