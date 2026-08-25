# DISASTER RECOVERY REPORT

- RPO target: <= 1 hour (database backups).
- RTO target: <= 4 hours (restore + restart + reconcile).
- Backup scope: database, config metadata, AI memory, strategy versions,
  coin profiles, shadow campaign state, incident history, decision replay data,
  human override logs.
- Secrets are NOT included in plain-text backups.
- Backup/restore orchestration implemented in operating_system/backup.py.
- Corrupt-backup detection not yet implemented (future work).
