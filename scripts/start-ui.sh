#!/usr/bin/env bash
set -euo pipefail

TASK_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$TASK_ROOT/frontend"

if [[ ! -d node_modules ]]; then
  npm install
fi

exec npm run dev -- --host 127.0.0.1
