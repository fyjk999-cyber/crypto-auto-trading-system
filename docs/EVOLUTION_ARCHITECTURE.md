# EVOLUTION ARCHITECTURE

Phase 3: DAILY LEARNING BRAIN is COMPLETE at pipeline-foundation level.
- Durable SSOT stores are in-memory append-only facades with serialization.
- HistoricalReplayEngine uses stored evidence, never recomputes latest factors.
- DailyReviewPipeline is idempotent per review:daily:{UTC_DATE}.
- Weekly/Monthly/Yearly scheduled capabilities remain for Phase 4.
