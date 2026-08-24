#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -d .venv ]; then
  python3.12 -m venv .venv 2>/dev/null || python3 -m venv .venv
fi
. .venv/bin/activate
python -m ensurepip --upgrade 2>/dev/null || true
python -m pip install -e '.[dev]' -q
mkdir -p data
alembic upgrade head >/dev/null 2>&1 || true
export TRADING_MODE=PAPER
export LIVE_TRADING_ENABLED=false
export AUTO_START_RUNTIME=true
nohup python -m crypto_trader.runtime.local_runner --host 127.0.0.1 --port 8000 > data/paper-runtime.log 2>&1 &
echo $! > data/paper-runtime.pid
echo "Paper runtime starting on http://127.0.0.1:8000 (pid $(cat data/paper-runtime.pid))"
