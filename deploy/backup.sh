#!/bin/sh
# Daily pg_dump with 7 daily + 4 weekly retention. Runs inside the compose
# network; backups land in ../server-data/backups on the host.
# NOTE: LLM API keys are NOT stored in PostgreSQL (encrypted SecretStore is
# file-based), so pg_dump does not contain plaintext provider secrets.
set -eu
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DAILY_DIR=/backups/daily
WEEKLY_DIR=/backups/weekly
mkdir -p "$DAILY_DIR" "$WEEKLY_DIR"

pg_dump -h crypto-postgres -U crypto_trader -d crypto_trader -Fc \
  -f "$DAILY_DIR/crypto_trader_${STAMP}.dump"

# Weekly snapshot every Sunday (UTC).
if [ "$(date -u +%u)" = "7" ]; then
  cp "$DAILY_DIR/crypto_trader_${STAMP}.dump" \
     "$WEEKLY_DIR/crypto_trader_week_${STAMP}.dump"
fi

# Retention: 7 daily, 4 weekly.
ls -1t "$DAILY_DIR"/crypto_trader_*.dump 2>/dev/null | tail -n +8 | xargs -r rm -f
ls -1t "$WEEKLY_DIR"/crypto_trader_week_*.dump 2>/dev/null | tail -n +5 | xargs -r rm -f

# Rotate the encrypted LLM SecretStore backup (file copy, stays encrypted;
# master key backup is handled by the operator runbook, NOT by cron copies).
if [ -d /app/secrets ] && [ -f /app/secrets/.llm-secrets.json ]; then
  : # intentionally skipped: secrets live on a mounted host volume, which is
    # itself included in the host-level backup procedure (CLOUD_DEPLOYMENT.md §9)
fi

echo "[backup] $(date -u +%FT%TZ) OK"
