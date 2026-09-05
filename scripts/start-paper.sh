#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
HOST="${PAPER_RUNTIME_HOST:-127.0.0.1}"
PORT="${PAPER_RUNTIME_PORT:-8000}"
PID_FILE="data/paper-runtime.pid"
LOG_FILE="data/paper-runtime.log"

if command -v lsof >/dev/null 2>&1; then
  LISTENER_PID="$(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1 || true)"
  if [ -n "$LISTENER_PID" ]; then
    echo "PAPER_RUNTIME_START_FAILED: port $PORT is already in use by pid $LISTENER_PID" >&2
    echo "Stop the existing runtime with ./scripts/stop-paper.sh, then retry." >&2
    exit 1
  fi
fi
if [ ! -d .venv ]; then
  python3.12 -m venv .venv 2>/dev/null || python3 -m venv .venv
fi
. .venv/bin/activate
python -m ensurepip --upgrade 2>/dev/null || true
python -m pip install -e '.[dev]' -q
mkdir -p data
if ! alembic upgrade head; then
  echo "PAPER_RUNTIME_START_FAILED: database migration failed" >&2
  exit 1
fi
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
nohup python -m crypto_trader.runtime.local_runner --host "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &
PID=$!
printf '%s\n' "$PID" > "$PID_FILE"

for _ in $(seq 1 60); do
  if ! kill -0 "$PID" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "PAPER_RUNTIME_START_FAILED: runtime process exited during startup" >&2
    echo "Sanitized diagnostics are available in $LOG_FILE" >&2
    exit 1
  fi
  if curl -fsS --max-time 1 "http://$HOST:$PORT/ready" >/dev/null 2>&1; then
    echo "PAPER RUNTIME READY: http://$HOST:$PORT (pid $PID)"
    exit 0
  fi
  sleep 0.5
done

kill -TERM "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
echo "PAPER_RUNTIME_START_FAILED: /ready did not become healthy within 30 seconds" >&2
echo "Sanitized diagnostics are available in $LOG_FILE" >&2
exit 1
