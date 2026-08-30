# CLOUD DEPLOYMENT — 24x7 PAPER (Runbook)

Target: Ubuntu 24.04 LTS, 4 vCPU / 8 GB RAM / 80 GB SSD.
Mode: **PAPER only**, real public OKX market data, **NO real money, NO private OKX orders**.

> ⚠️ **BASELINE WARNING (recorded 2026-08-30)**: `origin/main` was observed at
> `784216a` ("night journal"). The Phase 1-4 repair stream (TRX stale-epoch
> bridge fix, runtime policy layer, market observer, tool journal, episodes
> decimal contract, diary generator) lives on branch
> `codex/non-strategy-infra-repair` (HEAD `9554806` at last local check) and is
> **NOT yet on main**. Deploying `main` ships the pre-Phase-1 runtime. Decide
> deliberately: (a) deploy `main` as directed, or (b) authorize merging the
> codex branch first. The repository HEAD at deploy time is authoritative —
> record it (§ runbook step 1).

## 1. Server baseline (one-time, root)

```bash
apt update && apt -y upgrade
apt -y install git curl ca-certificates unattended-upgrades chrony
# Docker Engine + Compose plugin (official repo)
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu noble stable" > /etc/apt/sources.list.d/docker.list
apt update && apt -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker chrony
dpkg-reconfigure -f noninteractive unattended-upgrades
```

User + repo (no root runtime):

```bash
useradd -m -s /bin/bash deployer
sudo -iu deployer
git clone https://github.com/fyjk999-cyber/crypto-auto-trading-system.git /opt/crypto-auto-trading-system
cd /opt/crypto-auto-trading-system
git fetch origin && git checkout main && git pull --ff-only origin main
git rev-parse HEAD; git status --short; git log -5 --oneline   # record & freeze
```

Firewall (UFW) — only 22/80/443 public; deny 5432/8000/5173:

```bash
ufw default deny incoming && ufw allow OpenSSH && ufw allow 80,443/tcp && ufw enable
```

SSH hardening: keys only (`PasswordAuthentication no`).

## 2. Environment + secrets

```bash
mkdir -p server-data/llm server-data/backups server-data/logs
cp deploy/.env.cloud.example .env.cloud
$EDITOR .env.cloud            # APP_ENV=production, PAPER contract, POSTGRES_PASSWORD, DOMAIN
# Transfer LLM SecretStore from the local machine (NEVER cat/print contents):
scp data/.llm-secrets.json data/.llm-master-key deployer@SERVER:/opt/crypto-auto-trading-system/server-data/llm/
chmod 600 server-data/llm/.llm-secrets.json server-data/llm/.llm-master-key
chown deployer:deployer server-data/llm/.llm-*
```

`.env.cloud` sets `LLM_SECRET_STORE_PATH=/app/secrets/.llm-secrets.json` and
`LLM_MASTER_KEY_PATH=/app/secrets/.llm-master-key`; compose mounts
`../server-data/llm:/app/secrets` (repository Settings truth, no code change).

## 3. Data migration (SQLite -> PostgreSQL, one-time)

```bash
# 3.1 bring up postgres only
docker compose -f deploy/docker-compose.yml --env-file ../.env.cloud up -d crypto-postgres
# 3.2 schema on PG (repository migrations are portable: 76/76 tables compile on PG dialect)
DATABASE_URL=postgresql+asyncpg://crypto_trader:PW@127.0.0.1:5432/crypto_trader \
  docker compose -f deploy/docker-compose.yml --env-file ../.env.cloud run --rm crypto-backend alembic upgrade head
# 3.3 controlled copy (preserves IDs/timestamps; refuses non-empty unless --truncate)
python3 -m venv /tmp/mig && /tmp/mig/bin/pip install "sqlalchemy>=2.0" "psycopg2-binary>=2.9"
/tmp/mig/bin/python scripts/sqlite_to_postgres_migrate.py \
  --source data/crypto_trader.db \
  --destination postgresql+psycopg2://crypto_trader:PW@127.0.0.1:5432/crypto_trader \
  --report docs/CLOUD_DATA_MIGRATION_REPORT.md
# 3.4 verify row counts in docs/CLOUD_DATA_MIGRATION_REPORT.md — all rows must read OK
```

## 4. First deployment

```bash
chmod +x scripts/deploy-cloud.sh
./scripts/deploy-cloud.sh main          # or the approved SHA
```

## 5. Qualification gates

```bash
./scripts/postgres_runtime_qualification.sh     # must PASS
./scripts/llm_runtime_qualification.sh          # must be 6/6 PASS (never prints keys)
```

Smoke (short, unattended-safe):
`/ready /health /llm/status /market /market/sources /runtime /risk /exploration/status` = 200;
frontend `https://DOMAIN` = 200; WS `wss://DOMAIN/ws` = CONNECTED.

No deterministic test trades are injected during qualification ⇒ no
DEPLOYMENT_FIXTURE-tagged samples are created; natural Stage-A samples
continue (§28 satisfied: zero fixtures).

## 6. Reboot test (controlled)

```bash
sudo reboot
# after restart, WITHOUT any manual shell: docker ps → all Up(healthy);
# backend auto-ran wait_for_postgres → alembic upgrade head → single uvicorn;
# lease recovers; scheduler resumes. Verify: curl 127.0.0.1:8000/ready inside net.
docker exec crypto-paper-crypto-backend-1 curl -fsS http://127.0.0.1:8000/ready
```

## 7. Update / rollback

Use `scripts/deploy-cloud.sh <sha>` always (backup → build → migrate → up →
health gate → app rollback). DB migrations are never auto-downgraded.

## 8. Access security (before public exposure)

Cloudflare Access **or** Tailscale (recommended): expose the proxy only to the
VPN; plain HTTP-IP access is NOT an acceptable final state. No `CORS: *`.

## 9. Backups & secrets

`crypto-backup` service runs daily pg_dump (7 daily + 4 weekly) into
`server-data/backups`. The encrypted LLM SecretStore lives on the host volume
`server-data/llm`; include that directory (and `.llm-master-key`) in the host
backup. Without `.llm-master-key` the SecretStore is unrecoverable.
