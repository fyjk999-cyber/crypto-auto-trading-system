#!/usr/bin/env bash
# Restore PostgreSQL from an R2 backup artifact, then run integrity checks.
set -euo pipefail

DB_URL="${DATABASE_URL:?DATABASE_URL required}"
R2_BUCKET="${R2_BUCKET:-crypto-trading-backups}"
FILE="${1:?usage: restore.sh <backup-file.sql.gz>}"

npx wrangler r2 object get "${R2_BUCKET}/${FILE}" --file "${FILE}"
gunzip -c "${FILE}" | psql "${DB_URL}"

python -m alembic upgrade head
echo "restore complete: ${FILE}"
