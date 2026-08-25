# PRODUCTION DEPLOYMENT GUIDE

- Updated: 2026-08-25T16:10:41.520418+00:00
- Prerequisites: Python 3.12, PostgreSQL 16, Node 20+ for frontend build.
- Backend startup: scripts/start-ai-fund-manager.sh (runs Alembic upgrade head,
  then uvicorn on 127.0.0.1:8000). LIVE_TRADING_ENABLED=false by default.
- Frontend startup: cd frontend && npm ci && npm run build && npm run preview.
- Full stack: docker-compose up --build (uses .env; no live trading).
- Migration: python -m alembic -c alembic.ini upgrade head
- Backup/restore: BackupOrchestrator verifies SHA-256 manifest before restore.
- Real LLM configuration (future only): set LLM_PROVIDER, LLM_MODEL, LLM_API_KEY.
