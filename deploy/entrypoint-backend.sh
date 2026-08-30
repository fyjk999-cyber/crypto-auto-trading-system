#!/bin/sh
# Cloud backend entrypoint (single canonical PAPER runtime).
# 1. wait for PostgreSQL  2. run migrations  3. start ONE uvicorn process.
set -e

echo "[entrypoint] waiting for PostgreSQL..."
python scripts/wait_for_postgres.py

echo "[entrypoint] running alembic upgrade head..."
alembic upgrade head

echo "[entrypoint] starting single canonical runtime (uvicorn, 1 worker)..."
exec uvicorn crypto_trader.api.app:app --host 0.0.0.0 --port 8000
