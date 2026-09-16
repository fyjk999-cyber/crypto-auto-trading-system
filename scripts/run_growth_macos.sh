#!/bin/zsh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${ML_PYTHON:-__PYTHON__}"
export PYTHONPATH="$REPO/src"
export RUNNING_SHA="${RUNNING_SHA:-unknown}"
mkdir -p "$REPO/data/growth/logs" "$REPO/data/growth/reports" "$REPO/data/growth/advisories"
GROWTH_DB="${GROWTH_DB:-$REPO/data/ml/scan_dataset.db}"
exec "$PYTHON" "$REPO/scripts/growth_worker.py" "$GROWTH_DB" "$REPO/data/growth" "${GROWTH_INTERVAL_SECONDS:-300}"
