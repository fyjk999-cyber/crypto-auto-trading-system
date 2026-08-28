#!/usr/bin/env bash
set -euo pipefail

TASK_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8000"
BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}/ready"
UI_PORT="5173"
UI_URL="http://127.0.0.1:${UI_PORT}/"
RUNTIME_DIR="${TMPDIR:-/tmp}/crypto-auto-trading-system-local"
BACKEND_LAUNCHER_PID=""
FRONTEND_LAUNCHER_PID=""
OKX_CONNECT_PID=""

listener_pids() {
  local port=$1
  lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | sort -u
}

print_port_conflict() {
  local service=$1
  local port=$2
  local pids
  pids=$(listener_pids "$port" || true)

  echo "$service ERROR: port $port is already in use." >&2
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    echo "  PID $pid: $(ps -p "$pid" -o command= 2>/dev/null || echo unknown)" >&2
    echo "  Stop command: kill $pid" >&2
  done <<< "$pids"
  echo "Resolution: stop the listed process with the command above, then rerun this script." >&2
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM

  if [[ -n "$FRONTEND_LAUNCHER_PID" ]] && kill -0 "$FRONTEND_LAUNCHER_PID" 2>/dev/null; then
    kill "$FRONTEND_LAUNCHER_PID" 2>/dev/null || true
    wait "$FRONTEND_LAUNCHER_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_LAUNCHER_PID" ]] && kill -0 "$BACKEND_LAUNCHER_PID" 2>/dev/null; then
    kill "$BACKEND_LAUNCHER_PID" 2>/dev/null || true
    wait "$BACKEND_LAUNCHER_PID" 2>/dev/null || true
  fi
  if [[ -n "$OKX_CONNECT_PID" ]] && kill -0 "$OKX_CONNECT_PID" 2>/dev/null; then
    kill "$OKX_CONNECT_PID" 2>/dev/null || true
    wait "$OKX_CONNECT_PID" 2>/dev/null || true
  fi

  exit "$exit_code"
}

wait_for_http_200() {
  local name=$1
  local url=$2
  local launcher_pid=$3
  local log_file=$4

  for _ in {1..120}; do
    if ! kill -0 "$launcher_pid" 2>/dev/null; then
      echo "$name ERROR: process exited before becoming ready." >&2
      tail -n 30 "$log_file" >&2 || true
      return 1
    fi

    local http_code
    http_code=$(curl --silent --show-error --max-time 2 --output /dev/null \
      --write-out '%{http_code}' "$url" 2>/dev/null || true)
    if [[ "$http_code" == "200" ]]; then
      return 0
    fi
    sleep 0.5
  done

  echo "$name ERROR: $url did not return HTTP 200 within 60 seconds." >&2
  tail -n 30 "$log_file" >&2 || true
  return 1
}

if [[ -n "$(listener_pids "$BACKEND_PORT" || true)" ]]; then
  print_port_conflict "BACKEND" "$BACKEND_PORT"
  exit 1
fi
if [[ -n "$(listener_pids "$UI_PORT" || true)" ]]; then
  print_port_conflict "UI" "$UI_PORT"
  exit 1
fi

mkdir -p "$RUNTIME_DIR" "$TASK_ROOT/data"
BACKEND_LOG="$RUNTIME_DIR/backend.log"
FRONTEND_LOG="$RUNTIME_DIR/frontend.log"
: > "$BACKEND_LOG"
: > "$FRONTEND_LOG"

trap cleanup EXIT INT TERM

cd "$TASK_ROOT"
if [[ -z "${GIT_SHA:-}" ]] && command -v git >/dev/null 2>&1; then
  GIT_SHA=$(git -C "$TASK_ROOT" rev-parse HEAD 2>/dev/null || true)
  export GIT_SHA
fi
if [[ -x "$TASK_ROOT/.venv/bin/alembic" && -x "$TASK_ROOT/.venv/bin/uvicorn" ]]; then
  "$TASK_ROOT/.venv/bin/alembic" upgrade head >> "$BACKEND_LOG" 2>&1
  "$TASK_ROOT/.venv/bin/python" -m crypto_trader.runtime.local_runner \
    --host "$BACKEND_HOST" --port "$BACKEND_PORT" >> "$BACKEND_LOG" 2>&1 &
elif command -v uv >/dev/null 2>&1; then
  uv run alembic upgrade head >> "$BACKEND_LOG" 2>&1
  uv run python -m crypto_trader.runtime.local_runner \
    --host "$BACKEND_HOST" --port "$BACKEND_PORT" >> "$BACKEND_LOG" 2>&1 &
else
  echo "BACKEND ERROR: install project dependencies in .venv or install uv first." >&2
  exit 1
fi
BACKEND_LAUNCHER_PID=$!

wait_for_http_200 "BACKEND" "$BACKEND_URL" "$BACKEND_LAUNCHER_PID" "$BACKEND_LOG"

"$TASK_ROOT/scripts/connect-okx.sh" >> "$BACKEND_LOG" 2>&1 &
OKX_CONNECT_PID=$!

"$TASK_ROOT/scripts/start-ui.sh" >> "$FRONTEND_LOG" 2>&1 &
FRONTEND_LAUNCHER_PID=$!
wait_for_http_200 "UI" "$UI_URL" "$FRONTEND_LAUNCHER_PID" "$FRONTEND_LOG"

backend_pid=$(listener_pids "$BACKEND_PORT" | head -n 1)
frontend_pid=$(listener_pids "$UI_PORT" | head -n 1)

if [[ "$(uname -s)" == "Darwin" ]] && command -v open >/dev/null 2>&1; then
  open "$UI_URL"
fi

echo
echo "LOCAL SYSTEM READY"
echo "Backend PID: $backend_pid"
echo "Frontend PID: $frontend_pid"
echo "Backend: $BACKEND_URL"
echo "Frontend: $UI_URL"
echo "Logs: $RUNTIME_DIR"
echo "Press Ctrl+C to stop the local system."

while kill -0 "$BACKEND_LAUNCHER_PID" 2>/dev/null \
  && kill -0 "$FRONTEND_LAUNCHER_PID" 2>/dev/null; do
  sleep 2
done

echo "LOCAL SYSTEM ERROR: backend or frontend exited. Check logs in $RUNTIME_DIR." >&2
exit 1
