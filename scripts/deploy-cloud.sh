#!/usr/bin/env bash
# Cloud deployment/update script (run on the cloud server, repo checkout).
# Safe flow: freeze SHA -> backup -> build -> migrate -> up -> health gate
# -> rollback (application images only; migrations are NOT auto-downgraded).
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/crypto-auto-trading-system}"
DEPLOY_REF="${1:-main}"            # approved SHA or main
COMPOSE="docker compose -f deploy/docker-compose.yml --env-file ../.env.cloud"

cd "$REPO_DIR"

echo "== 1. freeze deployed SHA =="
git fetch origin
git checkout --detach "$DEPLOY_REF"
git pull --ff-only "origin" "$DEPLOY_REF" 2>/dev/null || true
SHA="$(git rev-parse HEAD)"
echo "DEPLOYED_SHA=$SHA" | tee .deployed_sha
[ -n "$(git status --short)" ] && echo "WARNING: dirty tree during deploy" && git status --short

echo "== 2. pre-upgrade DB backup =="
docker exec crypto-paper-crypto-postgres-1 \
  pg_dump -U crypto_trader -d crypto_trader -Fc \
  -f "/backups/pre_upgrade_${SHA}_${$(date -u +%Y%m%dT%H%M%SZ)}.dump" \
  2>/dev/null || echo "backup container not running yet (first deploy) — skipped"

echo "== 3. build images =="
$COMPOSE build

echo "== 4. apply migrations (once, in backend container context) =="
$COMPOSE run --rm crypto-backend alembic upgrade head

echo "== 5. start stack =="
$COMPOSE up -d

echo "== 6. health gate =="
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:8000/ready" >/dev/null 2>&1; then READY=1; break; fi
  sleep 5
done
READY="${READY:-0}"
if [ "$READY" != "1" ]; then
  echo "HEALTH GATE FAILED — rolling back application images (DB untouched)"
  docker compose -f deploy/docker-compose.yml down
  git checkout "$(cat .deployed_sha.previous 2>/dev/null || echo main)" 2>/dev/null || true
  $COMPOSE build && $COMPOSE up -d
  echo "ROLLBACK COMPLETE — investigate before retry"
  exit 1
fi

echo "$(cat .deployed_sha)" > .deployed_sha.previous
echo "DEPLOY OK: $SHA"
