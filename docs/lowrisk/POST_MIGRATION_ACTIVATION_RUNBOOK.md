# Post-migration activation runbook — NOT authorization to deploy

STOP unless the separate, factual storage-controller receipt explicitly contains:

MIGRATION_ACCEPTANCE=PASS, SPACE_RECOVERY_ACCEPTANCE=PASS,
SHARED_HISTORY_RECOVERY_ACCEPTANCE=PASS, READY_FOR_POST_MIGRATION_ACTIVATION=YES.

Then obtain explicit authorization for the exact final candidate SHA and controlled
LowRisk-only deployment. Engineering preparation is not runtime acceptance.

1. Verify candidate full SHA and clean worktree against candidate receipt; no amend,
   unreviewed commits, historical SHA assumption, or force-push.
2. Obtain fresh Shared History facts: RESOURCE_STATE=NORMAL, writer_count=1,
   API healthy, INCREMENTAL_REFRESH=ACTIVE. HTTP200/OK alone is insufficient.
   Missing explicit resource state is NOT_VERIFIED, not inferred NORMAL.
3. Discover current complete eligible universe from canonical public metadata/API.
   Record actual count and exact IDs. No fixed historic count; no healthy-only sample.
4. Obtain current per-symbol1m freshness for ALL eligible IDs: finite nonnegative
   lag<=300s, OUTSIDE_300S=0, no missing/extra/duplicate ID. Bind raw health snapshot
   timestamps (<=60s old) and current source/service SHA. Empty collections cannot PASS.
5. Verify Shared History canonical factual Parquet filter upstream rejects AppleDouble,
   hidden/.tmp files, wrong extension, zero length, nonregular/unreadable and unsafe
   symlinks. LowRisk must not open Parquet/DuckDB/admin/writer paths to verify it.
6. Verify candidate read-only consumer and GET-only transport; redirects forbidden,
   no inherited proxy. Construction/default-off reads generate no network I/O.
   Enable shared_history_enabled only through separately approved deployment config
   once actual endpoint schema includes explicit current resource/health provenance.
7. Deploy the exact frozen LowRisk candidate with existing release tooling; controlled
   restart ONLY LowRisk if authorized. No other service restart or migration DB access.
8. Verify running /version SHA, process cwd/PYTHONPATH/entrypoint and full process
   identity against exact candidate (not merely release directory HEAD).
9. Verify PAPER only, LIVE false; `/runtime` and `/llm/health` both show existing
   provider pause. Do not call provider readiness inference, enable LLM, change
   deepseek-flash, clear kill switches or change offline/fail-closed controls.
10. Verify Risk/execution/strategy fingerprint/settings unchanged; Chief direction
    remains authoritative, Factors/Experts/ML/Growth/Memory only evidence.
11. `/historical-evidence/health` must be noncached-current and truthful. Critical,
    stale, unavailable, malformed or missing health evidence returns unavailable.
    This is data availability, not a replacement trading safety authority.
12. Symbol memory flag stays false. No real backend/index/embeddings/backfill/Stage B.
    A future authorized integration supplies exact lowrisk/<symbol> namespace,
    factual as-of and actual strategy/factor/model/source/schema versions. Missing
    provenance remains missing, not invented. Outage!=no prior experience.
13. Separate authorized controller runs independent operational preflight; every
    current invariant must be measured anew, including lease/writer topology.
14. Only after separate explicit authorization and fresh preflight PASS run new
    qualification/soak. Invalid prior soak and failed qualification credit stay0.

Stop on unknown, schema mismatch, degraded state, ownership doubt, paused provider
unexpectedly resuming, SHA mismatch or non-read-only access. Never relax freshness,
exclude symbols, create acceptance rows or reuse historical PASS to proceed.

## Isolated engineering test scope

Use scripts/lowrisk_candidate_tests.sb with the existing venv and PYTHONPATH=src.
The profile blocks external lake/ResearchArchive/source DB reads and production
Application Support state, all nonfixture writes, credentials command, launchctl,
and remote-network outbound. Tests may use tmp SQLite/loopback mocks only.
Host integration cases that require real network, production canonical directory
creation, credential installer/platform Unix sockets are not applicable here;
record exact excluded node IDs in the test receipt. No blanket claim full runtime
qualification from hermetic tests.
