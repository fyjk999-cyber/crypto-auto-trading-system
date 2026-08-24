#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PID_FILE="data/paper-runtime.pid"
if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE")"
  if kill -0 "$PID" 2>/dev/null; then
    kill -TERM "$PID"
    sleep 2
    if kill -0 "$PID" 2>/dev/null; then kill -KILL "$PID" || true; fi
    echo "Stopped paper runtime (pid $PID)"
  else
    echo "Paper runtime not running"
  fi
  rm -f "$PID_FILE"
else
  echo "No paper runtime pid file"
fi
