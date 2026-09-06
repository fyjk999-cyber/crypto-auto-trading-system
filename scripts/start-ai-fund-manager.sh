#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f .venv/bin/python ]; then
  echo "Missing .venv/bin/python. Run: uv sync" >&2
  exit 1
fi
if [ -f alembic.ini ]; then
  .venv/bin/python -m alembic -c alembic.ini upgrade head
fi
export TRADING_MODE=PAPER
export PAPER_MODE=PAPER_REAL_MARKET
export LIVE_TRADING_ENABLED=false
export AUTO_START_RUNTIME=true
export RUNNING_SHA="$(git rev-parse HEAD)"
echo "Trading Mode: PAPER"
echo "Market Provider: OKX_PUBLIC"
echo "Execution: PAPER / LOCAL_SIMULATOR"
echo "Live Trading: DISABLED"
exec .venv/bin/python -m crypto_trader.runtime.local_runner --host 127.0.0.1 --port 8000
