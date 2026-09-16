#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
HELPER="$ROOT/scripts/deepseek-keychain.swift"

require_macos() {
  [[ "$(uname -s)" == "Darwin" ]] || { echo "macOS Keychain is required." >&2; exit 1; }
  command -v swift >/dev/null || { echo "Swift is required for secure Keychain access." >&2; exit 1; }
}

case "${1:-}" in
  save|update)
    require_macos
    IFS= read -r -s -p "DeepSeek API key: " key
    printf '\n'
    [[ -n "$key" ]] || { echo "No key entered." >&2; exit 1; }
    printf '%s' "$key" | swift "$HELPER" save
    unset key
    echo "DeepSeek credential saved to macOS Keychain."
    ;;
  verify)
    require_macos
    if swift "$HELPER" exists; then echo "DeepSeek credential exists in macOS Keychain."; else echo "DeepSeek credential is not configured."; exit 1; fi
    ;;
  run)
    # One canonical secure PAPER path: the wrapper loads the Keychain credential
    # in memory, pins deepseek-flash and starts fail-closed when it is absent.
    exec "$ROOT/scripts/run_low_risk_paper_secure.sh"
    ;;
  delete)
    require_macos
    swift "$HELPER" delete
    echo "DeepSeek credential deleted from macOS Keychain."
    ;;
  *)
    echo "Usage: $0 {save|update|verify|run|delete}" >&2
    exit 64
    ;;
esac
