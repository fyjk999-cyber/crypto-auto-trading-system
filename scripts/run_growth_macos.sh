#!/bin/zsh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${ML_PYTHON:-__PYTHON__}"
export PYTHONPATH="$REPO/src"
export RUNNING_SHA="${RUNNING_SHA:-unknown}"
mkdir -p "$REPO/data/growth/logs" "$REPO/data/growth/reports" "$REPO/data/growth/advisories"
DERIVED_DB="${GROWTH_DERIVED_DB:-$REPO/data/growth/growth.db}"
exec "$PYTHON" "$REPO/scripts/growth_worker.py" "$DERIVED_DB" "$REPO/data/growth" "${GROWTH_INTERVAL_SECONDS:-300}"
