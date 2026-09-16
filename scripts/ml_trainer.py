# ruff: noqa: E402
# Autonomous trainer loop (no LLM, no orders, no credentials).
import asyncio
import os
import signal
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from crypto_trader.ml_orchestrator import MLOrchestrator
from crypto_trader.persistence import Database

STOP = False


def _sig(*_):
    global STOP
    STOP = True


async def main(db_path: str, base_dir: str) -> None:
    database = Database(f"sqlite+aiosqlite:///{db_path}")
    await database.init_schema()
    orchestrator = MLOrchestrator(
        database.session_factory, base_dir, code_sha=os.environ.get("RUNNING_SHA", "")
    )
    while not STOP:
        try:
            await orchestrator.run_once()
        except Exception as exc:
            orchestrator._save(
                state=orchestrator.state.state, last_error=f"{type(exc).__name__}: {exc}"[:200]
            )
        await asyncio.sleep(60)
    await database.close()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    db = sys.argv[1] if len(sys.argv) > 1 else "data/ml/scan_dataset.db"
    base = sys.argv[2] if len(sys.argv) > 2 else "data/ml"
    asyncio.run(main(db, base))
