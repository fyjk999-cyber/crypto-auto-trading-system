#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../frontend"
npm install
npm run typecheck
npm run build
npm test
npm run dev -- --host 127.0.0.1 &
DEV_PID=$!
sleep 3
curl -sSf http://127.0.0.1:5173/ >/dev/null || (kill $DEV_PID; exit 1)
kill $DEV_PID
echo "FRONTEND_VERIFY_OK"
