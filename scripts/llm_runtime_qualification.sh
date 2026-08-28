#!/usr/bin/env bash
# Manual, inert LLM qualification. It never reads or prints an API key.
set -euo pipefail

LLM_RUNTIME_BASE_URL="${LLM_RUNTIME_BASE_URL:-http://127.0.0.1:8000}"
STATUS_URL="${LLM_RUNTIME_BASE_URL}/llm/status"
QUALIFICATION_URL="${LLM_RUNTIME_BASE_URL}/llm/qualification"

status="$(curl --fail --silent --show-error --max-time 15 "$STATUS_URL")"
python3 - "$status" <<'PY'
import json
import sys

status = json.loads(sys.argv[1])
if not status.get("configured"):
    print("LLM_PROVIDER_RUNTIME_VALIDATED=NO")
    print("Reason: no configured LLM provider")
    raise SystemExit(2)
print(f"LLM status: {status.get('health', 'UNKNOWN')}")
PY

result="$(curl --fail --silent --show-error --max-time 180 -X POST "$QUALIFICATION_URL")"
python3 - "$result" <<'PY'
import json
import sys

result = json.loads(sys.argv[1])
for check in result.get("checks", []):
    print(
        f"{check.get('route')}: {'PASS' if check.get('ok') else 'FAIL'} "
        f"provider={check.get('provider') or '--'} model={check.get('model') or '--'} "
        f"latency_ms={check.get('latency_ms', 0)} tokens={check.get('total_tokens', 0)} "
        f"error={check.get('error_code') or '--'}"
    )
print("LLM_PROVIDER_RUNTIME_VALIDATED=" + ("YES" if result.get("ok") else "NO"))
raise SystemExit(0 if result.get("ok") else 1)
PY
