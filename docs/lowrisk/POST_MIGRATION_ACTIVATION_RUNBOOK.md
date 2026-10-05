# Post-migration activation runbook — NOT authorization to deploy

STOP unless the separate, factual storage-controller receipt explicitly contains:

MIGRATION_ACCEPTANCE=PASS, SPACE_RECOVERY_ACCEPTANCE=PASS,
SHARED_HISTORY_RECOVERY_ACCEPTANCE=PASS, READY_FOR_POST_MIGRATION_ACTIVATION=YES.

Deployment requires human authorization and an exact final candidate receipt.
The current MASTER EXECUTION DIRECTIVE supplies gated landing authorization;
engineering preparation alone is not runtime acceptance.

1. Verify candidate full SHA and clean worktree against candidate receipt; no amend,
   unreviewed commits, historical SHA assumption, or force-push.
2. Obtain fresh Shared History facts: RESOURCE_STATE=NORMAL, writer_count=1,
   API healthy, operational_health schema_version=1, scheduler running/current,
   incremental.last_outcome=PASS. PASS is an evaluated outcome, not ACTIVE.
   Missing explicit resource state is NOT_VERIFIED, not inferred NORMAL.
3. Discover current complete eligible universe from canonical public metadata/API.
   Record actual count and exact IDs. No fixed historic count; no healthy-only sample.
4. Obtain current per-symbol1m freshness for ALL eligible IDs: finite nonnegative
   lag<=300s, OUTSIDE_300S=0, no missing/extra/duplicate ID. Bind operational resource
   and scheduler source timestamps (<=60s old), publication/generation consistency,
   and source/service SHA. Legacy aggregate clock is not a 60s operational clock.
   Empty collections cannot PASS; a heartbeat cannot refresh market timestamps.
5. Verify Shared History canonical factual Parquet filter upstream rejects AppleDouble,
   hidden/.tmp files, wrong extension, zero length, nonregular/unreadable and unsafe
   symlinks. LowRisk must not open Parquet/DuckDB/admin/writer paths to verify it.
6. Verify candidate read-only consumer and GET-only transport; redirects forbidden,
   no inherited proxy. Construction/default-off reads generate no network I/O.
   Enable shared_history_enabled only through the authorized gated deployment config
   once actual endpoint schema includes explicit current resource/health provenance.
7. Deploy the exact frozen LowRisk candidate with existing release tooling; controlled
   restart ONLY LowRisk if authorized. No other service restart or migration DB access.
8. Verify running /version SHA, process cwd/PYTHONPATH/entrypoint and full process
   identity against exact candidate (not merely release directory HEAD).
9. Initial startup: verify PAPER only, LIVE false; `/runtime` and `/llm/health` both
   show provider pause. Only after stable runtime acceptance may the authorized
   LLM restoration phase resume the approved provider/model through the existing
   secure mechanism. Never change the model, clear safety kill switches, or weaken
   offline/fail-closed behavior to obtain healthy status.
10. Verify Risk/execution/strategy fingerprint/settings unchanged; Chief direction
    remains authoritative, Factors/Experts/ML/Growth/Memory only evidence.
11. `/historical-evidence/health` must be noncached-current and truthful. Critical,
    stale, unavailable, malformed or missing health evidence returns unavailable.
    This is data availability, not a replacement trading safety authority.
12. Symbol memory flag stays false. No real backend/index/embeddings/backfill/Stage B.
    A future authorized integration supplies exact lowrisk/<symbol> namespace,
    factual as-of and actual strategy/factor/model/source/schema versions. Missing
    provenance remains missing, not invented. Outage!=no prior experience.
13. Run independent operational preflight under the landing authorization; every
    current invariant must be measured anew, including lease/writer topology.
14. Only after fresh preflight, deployed runtime and approved LLM restoration PASS
    run new qualification/soak under the landing authorization. Invalid prior
    soak and failed qualification credit stay0.

Stop on unknown, schema mismatch, degraded state, ownership doubt, paused provider
unexpectedly resuming, SHA mismatch or non-read-only access. Never relax freshness,
exclude symbols, create acceptance rows or reuse historical PASS to proceed.

## Current landing authorization and exact-SHA binding

Historical candidate6eda82c8 is immutable provenance, not deployable final state.
This new candidate starts from6eda82c8; its exact target SHA is the commit containing
this runbook and must equal the signed-off external engineering/preflight receipt,
clean source HEAD, and origin branch SHA. Never deploy an assumed branch tip.
The human MASTER EXECUTION DIRECTIVE authorizes gated producer-first deployment,
then PAPER-only consumer startup with LLM paused, secure approved-provider resume
after runtime acceptance, fresh qualification and the final >=72h soak specified
by docs/low-risk/LOW_RISK_V2_FINAL_LANDING_ACCEPTANCE_SPEC.md. It does not permit
LIVE, memory activation, forced trades, weaker safety or historical soak credit.

Rollback uses verified prior runtime source6ced1da3008edf49eac086596ff4f208ee7b0821
and the pre-deploy saved LaunchAgent/configuration. Verify process exit before
loading the rollback, exact /version/source/PAPER and paused LLM on startup.
Producer rollback source is76d083085c6b19a524c5525fc4321b960465f436. Preserve canonical
storage/writer ownership and all state; no deletion/backfill/DB repair by rollback.

## Isolated engineering test scope

Use scripts/lowrisk_candidate_tests.sb with the existing venv and PYTHONPATH=src.
The profile blocks external lake/ResearchArchive/source DB reads and production
Application Support state, all nonfixture writes, credentials command, launchctl,
and remote-network outbound. Tests may use tmp SQLite/loopback mocks only.
Host integration cases that require real network, production canonical directory
creation, credential installer/platform Unix sockets are not applicable here;
record exact excluded node IDs in the test receipt. No blanket claim full runtime
qualification from hermetic tests.
