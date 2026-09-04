#!/bin/bash
set +x
set -euo pipefail
if [[ $(uname -s) != Darwin || $EUID != 0 || -z ${SUDO_USER:-} ]]; then
  echo 'MACOS_ADMIN_OS_ISOLATION_REQUIRED: run this installer with sudo in your terminal.' >&2
  exit 1
fi
TASK_ROOT=$(cd "$(dirname "$0")/.." && pwd)
exec "$TASK_ROOT/.venv/bin/python" -I "$TASK_ROOT/deploy/macos/install.py"
