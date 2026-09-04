#!/bin/bash
set +x
set -euo pipefail
# Python performs the staged privilege checks, including read-only non-root preflight.
TASK_ROOT=$(cd "$(dirname "$0")/.." && pwd)
exec "$TASK_ROOT/.venv/bin/python" -I -B "$TASK_ROOT/deploy/macos/install.py" "$@"
