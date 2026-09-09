#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${PAPER_RUNTIME_HOST:-127.0.0.1}"
PORT="${PAPER_RUNTIME_PORT:-8001}"
OUT="$ROOT/.ops/ai-native-remediation/runtime_evidence.log"
mkdir -p "$(dirname "$OUT")"
{
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) port=$PORT ==="
  echo "version: $(curl -fsS -m 5 "http://$HOST:$PORT/version")"
  echo "health: $(curl -fsS -m 5 "http://$HOST:$PORT/health")"
  echo "runtime: $(curl -fsS -m 5 "http://$HOST:$PORT/runtime")"
  echo "llm: $(curl -fsS -m 5 "http://$HOST:$PORT/llm/health")"
  echo "market: $(curl -fsS -m 5 "http://$HOST:$PORT/market")"
} >> "$OUT"
echo "RUNTIME_EVIDENCE_APPENDED=$OUT"
