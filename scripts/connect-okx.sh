#!/usr/bin/env bash
set -euo pipefail

TASK_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
API_BASE_URL="${OKX_AUTO_CONNECT_API_URL:-http://127.0.0.1:8000}"
STATUS_URL="${API_BASE_URL}/exchange/okx/status"
VALIDATE_URL="${API_BASE_URL}/exchange/okx/validate"

if [[ -x "$TASK_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$TASK_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=$(command -v python3)
else
  echo "OKX AUTO CONNECT ERROR: Python 3 is required." >&2
  exit 1
fi

read_field() {
  local field=$1
  "$PYTHON_BIN" -c \
    'import json,sys; value=json.load(sys.stdin).get(sys.argv[1]); print(str(value).lower() if isinstance(value,bool) else (value or ""))' \
    "$field"
}

status_payload=""
for _ in {1..60}; do
  status_payload=$(curl --silent --show-error --max-time 2 "$STATUS_URL" 2>/dev/null || true)
  if [[ -n "$status_payload" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$status_payload" ]]; then
  echo "OKX AUTO CONNECT ERROR: backend status endpoint is unavailable." >&2
  exit 1
fi

configured=$(read_field configured <<< "$status_payload")
authenticated=$(read_field authenticated <<< "$status_payload")

if [[ "$configured" != "true" ]]; then
  echo "OKX AUTO CONNECT: credentials are not configured; use the System page once."
  exit 0
fi

if [[ "$authenticated" == "true" ]]; then
  echo "OKX AUTO CONNECT READY: existing DEMO connection is healthy."
  exit 0
fi

validation_payload=$(curl --silent --show-error --fail --max-time 45 \
  --request POST "$VALIDATE_URL")
authenticated=$(read_field authenticated <<< "$validation_payload")
health=$(read_field health <<< "$validation_payload")
reason=$(read_field reason_code <<< "$validation_payload")

if [[ "$authenticated" == "true" && "$health" == "HEALTHY" ]]; then
  echo "OKX AUTO CONNECT READY: DEMO credentials verified."
  exit 0
fi

echo "OKX AUTO CONNECT FAILED: ${reason:-UNKNOWN}; open the System page for diagnostics." >&2
exit 1
