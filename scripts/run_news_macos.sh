# News worker user-level launchd entry (called via /bin/zsh from the plist).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${ML_PYTHON:-${NEWS_PYTHON:-$REPO/.venv/bin/python}}"
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
export RUNNING_SHA="${RUNNING_SHA:-unknown}"
export NEWS_ENABLED="${NEWS_ENABLED:-1}"
NEWS_DIR="${NEWS_DIR:-$REPO/data/news}"
mkdir -p "$NEWS_DIR/logs"
DB_PATH="${NEWS_DB_PATH:-$NEWS_DIR/news.db}"
INTERVAL="${NEWS_POLL_INTERVAL_SECONDS:-180}"
exec "$PYTHON" "$REPO/scripts/news_worker.py" "$DB_PATH" "$INTERVAL"
