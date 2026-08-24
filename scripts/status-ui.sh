#!/usr/bin/env bash
set -u

UI_PORT="5173"
UI_URL="http://127.0.0.1:${UI_PORT}/"
BACKEND_URL="http://127.0.0.1:8000/ready"
STATUS=0

listener_pids=$(lsof -nP -iTCP:"$UI_PORT" -sTCP:LISTEN -t 2>/dev/null | sort -u || true)
if [[ -n "$listener_pids" ]]; then
  echo "UI LISTEN: YES (port $UI_PORT)"
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    echo "  PID $pid: $(ps -p "$pid" -o command= 2>/dev/null || echo unknown)"
  done <<< "$listener_pids"
else
  echo "UI LISTEN: NO (port $UI_PORT)"
  STATUS=1
fi

ui_http_code=$(curl --silent --show-error --max-time 3 --output /dev/null \
  --write-out '%{http_code}' "$UI_URL" 2>/dev/null || true)
if [[ "$ui_http_code" == "200" ]]; then
  echo "UI HTTP: OK (HTTP 200)"
else
  echo "UI HTTP: FAILED (HTTP ${ui_http_code:-000})"
  STATUS=1
fi

backend_http_code=$(curl --silent --show-error --max-time 3 --output /dev/null \
  --write-out '%{http_code}' "$BACKEND_URL" 2>/dev/null || true)
if [[ "$backend_http_code" =~ ^[1-5][0-9][0-9]$ ]]; then
  echo "BACKEND: REACHABLE ($BACKEND_URL, HTTP $backend_http_code)"
else
  echo "BACKEND: UNREACHABLE ($BACKEND_URL)"
  STATUS=1
fi

exit "$STATUS"
