#!/usr/bin/env bash
# Canonical secure PAPER runtime launcher for Low-Risk V2.
# DEEPSEEK_API_KEY is read from macOS Keychain in memory only and exported to the
# child process; it is never written to plist, disk, logs, diagnostics or argv.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

HOST="${PAPER_RUNTIME_HOST:-127.0.0.1}"
PORT="${PAPER_RUNTIME_PORT:-8010}"
HELPER="$ROOT/scripts/deepseek-keychain.swift"
SWIFT_BIN="${LOWRISK_KEYCHAIN_SWIFT:-$(command -v swift || true)}"
PYTHON_BIN="${LOWRISK_PYTHON:-$ROOT/.venv/bin/python}"

export TRADING_MODE=PAPER
export PAPER_MODE=PAPER_REAL_MARKET
export LIVE_TRADING_ENABLED=false
export AUTO_START_RUNTIME=true
export LLM_PROVIDER=deepseek
export TRADING_LLM_MODEL=deepseek-flash
unset LLM_MODEL || true
export LLM_BASE_URL="${LLM_BASE_URL:-https://api.deepseek.com}"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export RUNNING_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"

PROVIDER_STATE="PROVIDER_UNCONFIGURED"
PROVIDER_STATUS_CODE=0
if [ -n "${SWIFT_BIN:-}" ] && [ -f "$HELPER" ]; then
  DEEPSEEK_KEY=""
  if DEEPSEEK_KEY="$("$SWIFT_BIN" "$HELPER" load 2>/dev/null)"; then
    if [ -n "$DEEPSEEK_KEY" ]; then
      export DEEPSEEK_API_KEY="$DEEPSEEK_KEY"
      PROVIDER_STATE="PROVIDER_CONFIGURED"
    else
      unset DEEPSEEK_API_KEY || true
      PROVIDER_STATUS_CODE=1
    fi
  else
    unset DEEPSEEK_API_KEY || true
    PROVIDER_STATUS_CODE=1
  fi
  unset DEEPSEEK_KEY
else
  unset DEEPSEEK_API_KEY || true
  PROVIDER_STATUS_CODE=1
fi

# Explicit, non-secret state; absence of the credential is observable and the
# runtime continues in fail-closed LLM_OFFLINE_MODE rather than crash-looping.
echo "LLM_PROVIDER_STATE=$PROVIDER_STATE" >&2
echo "LLM_PROVIDER=deepseek TRADING_LLM_MODEL=deepseek-flash FAIL_CLOSED_NEW_RISK=true" >&2
if [ "$PROVIDER_STATUS_CODE" != "0" ]; then
  echo "PROVIDER_UNCONFIGURED: DEEPSEEK_API_KEY not loaded from Keychain; new risk remains blocked." >&2
fi

if [ "${LOWRISK_SKIP_MIGRATIONS:-0}" != "1" ] && [ -x "$ROOT/.venv/bin/alembic" ] && [ -f "$ROOT/alembic.ini" ]; then
  "$ROOT/.venv/bin/alembic" -c "$ROOT/alembic.ini" upgrade head >&2
fi

exec "$PYTHON_BIN" -m crypto_trader.runtime.local_runner --host "$HOST" --port "$PORT"
