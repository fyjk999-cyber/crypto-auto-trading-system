#!/usr/bin/env bash
set -euo pipefail

TASK_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
UI_HOST="127.0.0.1"
UI_PORT="5173"
UI_URL="http://${UI_HOST}:${UI_PORT}/"
VITE_PID=""
VITE_LISTENER_PID=""

listener_pids() {
  lsof -nP -iTCP:"$UI_PORT" -sTCP:LISTEN -t 2>/dev/null | sort -u
}

print_port_conflict() {
  local pids
  pids=$(listener_pids || true)

  echo "UI ERROR: port $UI_PORT is already in use." >&2
  echo "Occupying process:" >&2
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    echo "  PID $pid: $(ps -p "$pid" -o command= 2>/dev/null || echo unknown)" >&2
    echo "  Stop command: kill $pid" >&2
  done <<< "$pids"
  echo "Resolution:" >&2
  echo "  Stop the listed process with the command above." >&2
  echo "  Then rerun: ./scripts/start-ui.sh" >&2
}

cleanup() {
  if [[ -n "$VITE_LISTENER_PID" ]] && kill -0 "$VITE_LISTENER_PID" 2>/dev/null; then
    kill "$VITE_LISTENER_PID" 2>/dev/null || true
    wait "$VITE_LISTENER_PID" 2>/dev/null || true
  fi
  if [[ -n "$VITE_PID" ]] && kill -0 "$VITE_PID" 2>/dev/null; then
    kill "$VITE_PID" 2>/dev/null || true
    wait "$VITE_PID" 2>/dev/null || true
  fi
}

if [[ -n "$(listener_pids || true)" ]]; then
  print_port_conflict
  exit 1
fi

cd "$TASK_ROOT/frontend"

if [[ ! -d node_modules ]]; then
  npm install
fi

trap cleanup EXIT INT TERM

npm run dev -- --host "$UI_HOST" --port "$UI_PORT" --strictPort &
VITE_PID=$!

for _ in {1..60}; do
  if ! kill -0 "$VITE_PID" 2>/dev/null; then
    wait "$VITE_PID"
    exit $?
  fi

  http_code=$(curl --silent --show-error --max-time 2 --output /dev/null \
    --write-out '%{http_code}' "$UI_URL" 2>/dev/null || true)
  if [[ "$http_code" == "200" ]]; then
    VITE_LISTENER_PID=$(listener_pids | head -n 1)
    echo
    echo "UI READY:"
    echo "$UI_URL"
    wait "$VITE_PID"
    exit $?
  fi

  sleep 0.5
done

echo "UI ERROR: Vite started but $UI_URL did not return HTTP 200 within 30 seconds." >&2
exit 1
