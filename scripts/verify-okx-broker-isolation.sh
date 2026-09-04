#!/bin/bash
set +x
set -euo pipefail
TASK_BASE='/Library/Application Support/CryptoOKXBroker'
if [[ ! -x "$TASK_BASE/runtime/bin/python3" ]]; then
  echo 'OS_LEVEL_UNREADABILITY = NOT_INSTALLED'
  exit 1
fi
exec "$TASK_BASE/runtime/bin/python3" -I "$TASK_BASE/verify.py" "$@"
