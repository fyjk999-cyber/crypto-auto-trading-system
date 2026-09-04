#!/usr/bin/env bash
# Compatibility entry point; the former raw-Keychain loader has been retired.
set +x
set -euo pipefail
TASK_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
case "${1:-}" in
  update) exec "$TASK_ROOT/scripts/okx-vault.sh" save ;;
  save|verify|run|delete) exec "$TASK_ROOT/scripts/okx-vault.sh" "$1" ;;
  *) echo "Use okx-vault.sh {save|verify|run|delete}. Raw export is unavailable." >&2; exit 64 ;;
esac
