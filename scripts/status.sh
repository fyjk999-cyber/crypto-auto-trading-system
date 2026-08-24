#!/usr/bin/env bash
cd "$(dirname "$0")/.."
echo "== Crypto Paper Runtime Status =="
if [ -f data/paper-runtime.pid ]; then
  PID="$(cat data/paper-runtime.pid)"
  if kill -0 "$PID" 2>/dev/null; then echo "Process: RUNNING (pid $PID)"; else echo "Process: STOPPED"; fi
else
  echo "Process: STOPPED"
fi
BASE="http://127.0.0.1:8000"
for path in health ready runtime version exchange-health; do
  echo "--- /$path ---"
  curl -sS --max-time 3 "$BASE/$path" || echo "unreachable"
  echo
done
