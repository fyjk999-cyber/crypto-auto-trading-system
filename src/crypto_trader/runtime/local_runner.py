"""One-command local runtime.

Usage:
    python -m crypto_trader.runtime.local_runner [--host 0.0.0.0] [--port 8000]

Starts Trading Engine + API + Scheduler + Review + Learning through the single
RuntimeBootstrap path. PAPER mode is the default and hard-coded safe:
LIVE_TRADING_ENABLED must remain false.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import time

import uvicorn

from crypto_trader.api.app import create_app
from crypto_trader.config import Settings
from crypto_trader.runtime.bootstrap import build_system

_START_TS = time.time()


def _write_shutdown_forensics(reason: str) -> None:
    """Ops observability only: record who stopped us and in what state.

    No secrets, no trading-state mutation. Best-effort; never raises.
    """
    try:
        ops_dir = os.path.join(os.getcwd(), ".ops")
        os.makedirs(ops_dir, exist_ok=True)
        entry = {
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "reason": reason,
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "uptime_seconds": round(time.time() - _START_TS, 1),
            "mode": os.environ.get("TRADING_MODE", "PAPER"),
        }
        with open(os.path.join(ops_dir, "shutdown_forensics.log"), "a") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crypto Automated Trading local runtime")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args()


async def main_async(host: str, port: int) -> None:
    settings = Settings()
    if settings.trading_mode.value == "LIVE":
        raise RuntimeError("LIVE mode is not allowed in local runner")
    bundle = await build_system(settings)
    app = create_app(bundle.app_state)
    config = uvicorn.Config(app, host=host, port=port, log_level=settings.log_level.lower())
    server = uvicorn.Server(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _write_shutdown_forensics, f"signal:{sig.name}")

    await server.serve()


def main() -> None:
    args = parse_args()
    asyncio.run(main_async(args.host, args.port))


if __name__ == "__main__":
    main()
