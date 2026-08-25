# AI FUND MANAGER RUNBOOK

- Startup: scripts/start-paper.sh (PAPER_REAL_MARKET mode)
- Shutdown: scripts/stop-paper.sh
- Status: scripts/status.sh
- Database migration: python -m alembic -c alembic.ini upgrade head
- Backup/restore: operating_system.backup.BackupOrchestrator (orchestration API)
- Start/pause/resume shadow: ShadowCampaignManager.start/pause/resume
- System health: GET /health, GET /ready
- Incidents: monitor via standardized incident events
- Emergency stop: Kill Switch remains authoritative
- Decision replay: DecisionSnapshot.replay_ready()
