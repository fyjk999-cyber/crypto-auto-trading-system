#!/usr/bin/env bash
# Restart the Low-Risk V2 acceptance soak runtime (window #4) WITHOUT destroying evidence.
#
# Difference vs the original fresh-window launch (recorded in shell history):
#   the original did `rm -f data/crypto_trader.db*` to start a clean window.
#   This script MUST NOT delete the DB: the existing DB is the Phase 5/6/7 acceptance
#   evidence (natural lifecycle, episodes, reviews, top10). It only restarts the process.
#
# Same runtime identity as window #4: worktree /tmp/lr2-soak2 @ 1ef721d6d491, port 8010.
set -euo pipefail

SOAK_DIR=/tmp/lr2-soak2
V=/Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-canonical/.venv
KEYCHAIN=/Users/huhongjie/Documents/ChatGPT/crypto-low-risk-v2/scripts/deepseek-keychain.swift
EXPECTED_SHA=1ef721d6d491

PORT=8010
LOG="$SOAK_DIR/data/low-risk-paper.log"

if lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "SOAK_RESTART_ABORTED: port $PORT already has a listener" >&2
  exit 1
fi

cd "$SOAK_DIR"
HEAD_SHA="$(git rev-parse HEAD)"
case "$HEAD_SHA" in
  "$EXPECTED_SHA"*) ;;
  *) echo "SOAK_RESTART_ABORTED: HEAD=$HEAD_SHA expected $EXPECTED_SHA" >&2; exit 1 ;;
esac

if [ ! -f data/crypto_trader.db ]; then
  echo "SOAK_RESTART_ABORTED: acceptance DB missing (refusing to create a blank one)" >&2
  exit 1
fi

KEY="$(swift "$KEYCHAIN" load 2>/dev/null || true)"
if [ -z "$KEY" ]; then
  echo "SOAK_RESTART_ABORTED: DeepSeek key unavailable from Keychain" >&2
  exit 1
fi

# alembic upgrade is idempotent; DB is already at 0028_opportunity_outcomes.
PYTHONPATH="$SOAK_DIR/src" "$V/bin/python" -m alembic upgrade head >/dev/null 2>&1 || {
  echo "SOAK_RESTART_ABORTED: alembic upgrade failed" >&2; exit 1; }

{
  echo "===== SOAK RESTART $(date '+%Y-%m-%dT%H:%M:%S%z') sha=$EXPECTED_SHA (DB preserved) ====="
} >> "$LOG"

nohup env \
  PYTHONPATH="$SOAK_DIR/src" \
  DEEPSEEK_API_KEY="$KEY" \
  LLM_PROVIDER=deepseek LLM_MODEL=deepseek-v4-pro LLM_BASE_URL=https://api.deepseek.com \
  TRADING_MODE=PAPER PAPER_MODE=PAPER_REAL_MARKET LIVE_TRADING_ENABLED=false \
  AUTO_START_RUNTIME=true RUNNING_SHA="$EXPECTED_SHA" \
  "$V/bin/python" -m crypto_trader.runtime.local_runner --host 127.0.0.1 --port "$PORT" \
  >> "$LOG" 2>&1 &

PID=$!
printf '%s\n' "$PID" > data/low-risk-paper.pid
echo "LAUNCHED pid=$PID sha=$EXPECTED_SHA db_preserved=true"
