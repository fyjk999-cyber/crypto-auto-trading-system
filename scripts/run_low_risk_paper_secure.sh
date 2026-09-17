#!/usr/bin/env bash
# CLASSIFICATION: CANONICAL_RUNTIME_ENTRY (single lifecycle owner)
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
# Explicit provider-call pause gate: defaults to PAUSED. Resume only through
# an explicit operator launchd/env authorization by setting LLM_CALLS_PAUSED=false.
export LLM_CALLS_PAUSED="${LLM_CALLS_PAUSED:-true}"
export LLM_CALLS_PAUSED_REASON="${LLM_CALLS_PAUSED_REASON:-OPERATOR_PAUSE_REQUEST}"
# News is evidence-only. The dedicated News DB target must be supplied by the
# launch environment; enabling context/reassessment keeps the dispatch seam live.
export NEWS_ENABLED="${NEWS_ENABLED:-1}"
# H0-H7 secondary acceptance passed: PAPER-only independent leg execution is
# enabled for natural hedge/reverse evidence accumulation. LIVE remains false.
export LEG_EXECUTION_ENABLED="${LEG_EXECUTION_ENABLED:-true}"
unset LLM_MODEL || true
export LLM_BASE_URL="${LLM_BASE_URL:-https://api.deepseek.com}"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
if [ -z "${RUNNING_SHA:-}" ]; then
  RUNNING_SHA="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || true)"
fi
export RUNNING_SHA="${RUNNING_SHA:-unknown}"

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
echo "LLM_CALLS_PAUSED=${LLM_CALLS_PAUSED} LLM_CALLS_PAUSED_REASON=${LLM_CALLS_PAUSED_REASON}" >&2
if [ "$PROVIDER_STATUS_CODE" != "0" ]; then
  echo "PROVIDER_UNCONFIGURED: DEEPSEEK_API_KEY not loaded from Keychain; new risk remains blocked." >&2
fi

# Durable-state preflight: canonical PAPER runtime may not store its DB under /tmp.
if [ "${LOWRISK_ALLOW_EPHEMERAL_DB:-0}" != "1" ]; then
  case "${DATABASE_URL:-}" in
    *:////private/tmp/*|*:////tmp/*|*:////private/var/tmp/*|*:////var/tmp/*)
      echo "EPHEMERAL_CANONICAL_DB=BLOCKED reason=DATABASE_URL_UNDER_EPHEMERAL_TMP" >&2
      exit 1
      ;;
  esac
fi
# The configured durable parent must exist before alembic/runtime startup.
case "${DATABASE_URL:-}" in
  *:////*)
    DB_FILE="${DATABASE_URL#*:////}"
    DB_DIR=$(dirname "$DB_FILE")
    mkdir -p "$DB_DIR"
    ;;
esac

if [ "${LOWRISK_SKIP_MIGRATIONS:-0}" != "1" ] && [ -x "$ROOT/.venv/bin/alembic" ] && [ -f "$ROOT/alembic.ini" ]; then
  "$ROOT/.venv/bin/alembic" -c "$ROOT/alembic.ini" upgrade head >&2
fi

exec "$PYTHON_BIN" -m crypto_trader.runtime.local_runner --host "$HOST" --port "$PORT"
