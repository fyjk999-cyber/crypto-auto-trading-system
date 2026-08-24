#!/usr/bin/env bash
# PostgreSQL backup -> checksum -> R2 upload. Requires wrangler v4+ and pg_dump.
set -euo pipefail

DB_URL="${DATABASE_URL:?DATABASE_URL required}"
R2_BUCKET="${R2_BUCKET:-crypto-trading-backups}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="backup-${TS}.sql.gz"
CHECKSUM_FILE="${FILE}.sha256"

pg_dump "${DB_URL}" | gzip > "${FILE}"
shasum -a 256 "${FILE}" > "${CHECKSUM_FILE}"

npx wrangler r2 object put "${R2_BUCKET}/${FILE}" --file "${FILE}"
npx wrangler r2 object put "${R2_BUCKET}/${CHECKSUM_FILE}" --file "${CHECKSUM_FILE}"

echo "backup uploaded: ${FILE}"
