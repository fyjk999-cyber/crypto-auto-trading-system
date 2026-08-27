# EVOLUTION ARCHITECTURE

Phase 3B: DAILY LEARNING persistence is durable.
- SqlEvidenceBackend: DecisionEvidence, DailyReviewResult, PatternCandidate, Lesson.
- SqlMemoryBackend: lesson listing + status updates.
- ReviewJobStore: idempotency state per review:daily:{UTC_DATE}.
- PostgreSQL-compatible SQLAlchemy; SQLite only for tests/local.
