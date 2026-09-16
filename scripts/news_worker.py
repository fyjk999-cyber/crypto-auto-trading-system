# ruff: noqa: E402
"""Autonomous News worker loop (evidence only, no orders, restart-safe)."""

import asyncio
import os
import signal
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from crypto_trader.news.config import NewsConfig
from crypto_trader.news.worker import NewsWorker
from crypto_trader.persistence import Database

STOP = False


def _sig(*_):
    global STOP
    STOP = True


async def main(db_path: str, interval: float) -> None:
    database = Database(f"sqlite+aiosqlite:///{db_path}")
    await database.init_schema()
    config = NewsConfig.from_env(REPO)
    config.database_url = f"sqlite+aiosqlite:///{db_path}"
    worker = NewsWorker(
        database.session_factory,
        config,
        code_sha=os.environ.get("RUNNING_SHA", ""),
    )
    worker.save_state(state="STARTING")
    while not STOP:
        try:
            await worker.run_once()
            worker.save_state(state="RUNNING")
        except Exception as exc:
            worker.save_state(
                state="DEGRADED",
                last_error=f"{type(exc).__name__}: {exc}"[:500],
            )
        await asyncio.sleep(interval)
    worker.save_state(state="STOPPED")
    await worker.close()
    await database.close()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    db = sys.argv[1] if len(sys.argv) > 1 else str(REPO / "data" / "news" / "news.db")
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else float(
        os.environ.get("NEWS_POLL_INTERVAL_SECONDS", "180")
    )
    asyncio.run(main(db, interval))
