#!/usr/bin/env bash
set -euo pipefail
# External PostgreSQL runtime qualification script.
# Requires: DATABASE_URL set to a PostgreSQL database.
cd "$(dirname "$0")/.."
if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL is required (postgresql+asyncpg://...)" >&2
  exit 2
fi
.venv/bin/python -m alembic -c alembic.ini upgrade head
.venv/bin/python -m pytest tests/evolution/test_learning_persistence.py \
  tests/evolution/test_hierarchical_persistence.py -q
echo "POSTGRES_RUNTIME_QUALIFICATION_SMOKE_OK"
