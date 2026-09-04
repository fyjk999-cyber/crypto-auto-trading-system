#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
HOST="${PAPER_RUNTIME_HOST:-127.0.0.1}"
PORT="${PAPER_RUNTIME_PORT:-8000}"
if [ ! -d .venv ]; then
  python3.12 -m venv .venv 2>/dev/null || python3 -m venv .venv
fi
. .venv/bin/activate
python -m ensurepip --upgrade 2>/dev/null || true
python -m pip install -e '.[dev]' -q
mkdir -p data
alembic upgrade head >/dev/null 2>&1 || true
export TRADING_MODE=PAPER
export PAPER_MODE=PAPER_REAL_MARKET
export LIVE_TRADING_ENABLED=false
export RUNNING_SHA="$(git rev-parse HEAD)"
echo "Trading Mode: PAPER"
echo "Market Data Mode: PAPER_REAL_MARKET"
echo "Market Provider: OKX_PUBLIC"
echo "Execution: PAPER / LOCAL_SIMULATOR"
echo "Live Trading: DISABLED"
export AUTO_START_RUNTIME=true
nohup python -m crypto_trader.runtime.local_runner --host "$HOST" --port "$PORT" > data/paper-runtime.log 2>&1 &
echo $! > data/paper-runtime.pid
echo "Paper runtime starting on http://$HOST:$PORT (pid $(cat data/paper-runtime.pid))"
