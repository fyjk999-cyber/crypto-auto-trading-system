#!/bin/zsh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="__PYTHON__"
export PYTHONPATH="$REPO/src"
export RUNNING_SHA="${RUNNING_SHA:-unknown}"
mkdir -p "$REPO/data/ml/logs" "$REPO/data/ml/datasets" "$REPO/data/ml/models" "$REPO/data/ml/shadow"
exec "$PYTHON" "$REPO/scripts/ml_trainer.py" "$REPO/data/ml/scan_dataset.db" "$REPO/data/ml"
