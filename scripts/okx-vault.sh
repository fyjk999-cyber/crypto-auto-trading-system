#!/usr/bin/env bash
set +x
set -euo pipefail
TASK_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$TASK_ROOT"
ulimit -c 0
exec "$TASK_ROOT/.venv/bin/python" -m crypto_trader.okx_vault.cli "$@"
