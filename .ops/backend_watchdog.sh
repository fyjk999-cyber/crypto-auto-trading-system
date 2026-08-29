#!/bin/bash
# Detached watchdog: revives the PAPER backend when an external sweep SIGTERMs it.
REPO="/Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-local-current"
export PATH="$HOME/.local/bin:$PATH"
LOG="$REPO/.ops/backend_watchdog.log"
while true; do
  sleep 60
  if ! curl -s -m 5 http://127.0.0.1:8000/health > /dev/null 2>&1; then
    cd "$REPO"
    python3 /dev/stdin << 'PYEOF'
import sqlite3
try:
    conn = sqlite3.connect("data/crypto_trader.db")
    conn.execute("DELETE FROM runtime_leases")
    conn.commit()
    conn.close()
except Exception:
    pass
PYEOF
    nohup uv run python -m crypto_trader.runtime.local_runner --host 127.0.0.1 --port 8000 >> "$REPO/.ops/backend_direct.log" 2>&1 &
    echo "$(date -u +%FT%TZ) watchdog revived backend" >> "$LOG"
  fi
done
