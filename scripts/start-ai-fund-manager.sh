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
echo "LIVE_TRADING_ENABLED=${LIVE_TRADING_ENABLED:-false}"
.venv/bin/python -m uvicorn crypto_trader.api.app:app --host 127.0.0.1 --port 8000
