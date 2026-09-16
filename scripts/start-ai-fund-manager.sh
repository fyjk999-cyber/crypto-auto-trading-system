#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
export TRADING_MODE=PAPER
export PAPER_MODE=PAPER_REAL_MARKET
export LIVE_TRADING_ENABLED=false
export AUTO_START_RUNTIME=true
export RUNNING_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
echo "Trading Mode: PAPER"
echo "Market Provider: OKX_PUBLIC"
echo "Execution: PAPER / LOCAL_SIMULATOR"
echo "Live Trading: DISABLED"
# Canonical secure path: scripts/run_low_risk_paper_secure.sh loads the DeepSeek
# Keychain credential in memory and execs crypto_trader.runtime.local_runner.
# No alternate path may start the runtime with an implicit/unsecure provider.
exec "$ROOT/scripts/run_low_risk_paper_secure.sh"
