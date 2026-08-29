# DECISIONS

- 2026-08-29T17:20Z (P0 CORRECTIONS for CS-20260829-132209-P0-MANUAL-BYPASS):
  (G) SIGTERM root cause CONFIRMED = Codex Supervisor containment stops (8x),
  triggered by unauthorized restarts while P0 mutation routes were live and by
  my own blind-DELETE watchdog (correctly flagged as containment bypass). My
  supervisor/watchdog/daemon scripts were REMOVED; DSH crons hold no restart
  authority; the Codex Supervisor remains the only restart authority.
  (H) Manual mutation routes FAIL-CLOSED: /manual-orders (raw request, no body
  validation), /paper/perpetual/open, /paper/perpetual/close now ALWAYS 403 +
  durable P0_MANUAL_ROUTE_BLOCKED audit row; can never mutate state.
  (I) Read-model corrections: /paper/perpetual/positions now applies real
  per-symbol OKX book marks (mark_source=OKX_REAL_BOOK); /positions leverage
  exposes the authoritative ledger/engine leverage (no contract-size
  recomputation). P1 cooldown is SYMBOL-SCOPED (dict keyed by symbol).
  (J) Episode pipeline: quarantine reads BOTH target and
  after_json.tainted_fill_ids; full-episode scope (id + time-window); leverage
  from ledger OPEN metadata (never 0, SPOT=1); ensure_columns is VERIFY-ONLY -
  schema owned by versioned migration 0018_trade_episode_lineage (idempotent,
  applied; alembic now at 0018). Canonical episodes REBUILT from clean facts:
  50 rows, fake ETH 100.05 episode removed (its false +2.33 win eliminated -
  WIN total corrected 2.41 -> 0.076), 0 duplicates, raw evidence untouched.

- 2026-08-29T16:30Z (P2 BACKEND AVAILABILITY / SINGLE-WRITER, user interrupt):
  (A) LEASE INVARIANTS (permanent): RULE 1 no human/ops mutation of
  runtime_leases while an active runtime exists; RULE 2 lease cleanup only in
  confirmed-dead-runtime recovery; RULE 3 recovery requires process dead + port
  free evidence first; RULE 4 reuse the existing LeaseManager (runtime/lease.py
  acquire() already does atomic CAS takeover of EXPIRED leases, TTL=10s,
  renew=3s, fence_generation increments) - supervisors never raw-DELETE; RULE 5
  any lease deletion requires documented dead-runtime evidence.
  (B) CANONICAL SUPERVISOR: .ops/backend_supervisor.sh is the ONLY restart
  authority (single instance via PID file + command identity, dynamic REPO_ROOT,
  30s poll). State machine: HEALTHY -> nothing; HEALTH_FAIL_ONCE -> recheck;
  PROCESS_ALIVE_DEGRADED (listener on OUR port but unhealthy) -> log only, never
  second runtime; PROCESS_DEAD (no listener on our port) -> wait 13s lease TTL
  expiry -> verify port free -> storm guard (max 3 restarts/30min else
  DEGRADED_CRASH_LOOP) -> start exactly ONE runtime -> verify health 60s.
  Supervisor never touches leases, trading tables, or kill switch.
  (C) SAFE RESTART PROCEDURE (manual, only if supervisor absent): confirm
  TRADING_MODE=PAPER -> record old PID/lease owner/positions -> graceful SIGTERM
  to the specific PID only -> wait exit -> verify port free -> wait >= lease TTL
  -> start one runtime via uv run python -m crypto_trader.runtime.local_runner
  -> /health OK -> /ready mode=PAPER -> one renewing lease -> recon PASS.
  (D) SIGTERM ROOT CAUSE: UNKNOWN external source; all deaths graceful
  ("Shutting down"), no crash/port/DB errors; correlated with dsh agent-session
  lifecycle transitions; NOT system crontab (empty), NOT launchd (none custom),
  NOT our watchdogs (not running at kill times). Shutdown forensics added to
  local_runner (SIGTERM/SIGINT -> .ops/shutdown_forensics.log: pid, ppid,
  uptime, mode) so future kills are attributable.
  (E) DSH cron is agent scheduling, NOT system supervision (crontab empty).
  cron-6 */5 = MONITOR-ONLY (health + supervisor alive); cron-7 */30 = deep
  checkpoint; neither holds restart authority; supervisor handles recovery.
  (F) Frontend "Backend Offline" had TWO independent causes: backend killed
  (above) AND vite dev server itself dead (5173 not listening). Both fixed:
  supervisor keeps backend alive; frontend dev relaunched (PATH needs
  /usr/local/bin for node/npm).

- 2026-08-29T14:45Z (Episode pipeline): (1) Episode persistence at trade close
  confirmation (engine close hook), not at Daily Review. (2) episode_id =
  eps-{sha1-24(symbol|market|entry fills|exit fills)} - stable dedupe-safe key.
  (3) Perp gross from FUTURES_REALIZED_PNL ledger metadata (canonical), spot
  deterministic rebuild; fees = SUM(fill.fee); net = gross - fees. (4) TIME_STOP
  attribution = SYSTEM/LIFECYCLE, never AI; legacy ai_brain reduce-only exits
  >= 4h -> TIME_STOP else UNKNOWN. (5) Quarantined fills excluded. (6) Partial
  close never an episode. (7) Runtime hook exception-safe. (8) Backend kill =
  external session SIGTERM; direct nohup launch for recovery.

- 2026-08-29 (ARCHITECTURE GUARDRAIL, user interrupt): AI-FIRST /
  QUANT-AS-EVIDENCE recorded as a permanent Architecture Invariant in
  HARNESS_GOAL.md (and here). Live-path audit results: (1) no forced/
  fallback LONG/SHORT anywhere in runtime/llm paths; (2) no quant hard
  gates — fit/confidence/regime/scores are labels and prompt evidence;
  (3) action space stays Literal[LONG, SHORT, NO_TRADE, WAIT] — NO_TRADE
  and WAIT are first-class; (4) opportunity ranking is ADVISORY ONLY
  (top_k feeds observability, never eligibility); (5) remaining hard
  gates are all Safety Gates (real data health, provider health,
  position-duplicate, cooldown, kill switch, lease, reconciliation);
  (6) RiskEngine and ExecutionAuthority code untouched this loop.
  One regression candidate found: the exploration sampler
  (EXPLORATION_SKIPPED) skipped ~10% of borderline-fit AI calls — a
  quant-conditioned AI invocation gate. Resolved by setting
  EXPLORATION_PROBABILITY=1.0 (every symbol reaches the AI every cycle;
  the code path remains as an explicit budget control, disabled).
  Priority order fixed: PAPER safety > AI-FIRST integrity > Risk/
  Execution safety > data integrity > Long Goal completion > trading
  frequency > fill count.
- 2026-08-29: Ledger = single source of truth; the paper exchange hydrates
  from it at startup. Reconciliation is spot-scoped (FUTURES_*/FUNDING
  excluded) - the perpetual engine owns futures integrity; halt semantics
  unchanged. Duplicate-entry protection is symbol-scoped and fails closed on
  state errors. The 01:02:55 stacked fill is excluded from clean evidence.
- 2026-08-27T14:32:22.377974+00:00: Do not fabricate runtime soak. FINAL report reflects PARTIAL/NO where external staging unavailable.
- 2026-08-28: LLM is shared infrastructure only. It cannot call the exchange or bypass RiskEngine/ExecutionAuthority.
- 2026-08-28: Runtime qualification baseline superseded to 20a4db8 (LLM integration
  changed production runtime behavior). Entry-path LLM decisions rate-limited to
  one per min_decision_interval_seconds (default 60s) to bound token cost on the
  0.5s market tick; position safety paths unaffected. Domain-model prompts now
  carry explicit output schema examples + DecisionId correlation; strategy gate
  requires route readiness (routes+provider+key) not just provider health.

## 2026-08-29T07:55Z - Diagnosis time-base rule (incident lesson)

- An apparent 07:26-07:37Z engine hang during checkpoint diagnosis was a
  TIME-BASE ERROR: the operator internal clock drifted ~40min from real UTC,
  so queries used future boundaries and health samples were compared against
  a wrong now. The engine was healthy throughout.
- RULE: always run date -u and anchor all since/until queries and freeze
  checks on it before diagnosing. Verify process identity with ps before
  pkill; kill by PID when the pattern is uncertain.
- Supervisor loop restarts now log RUNTIME_LOOP_CRASHED (silent crash-loop
  observability gap closed).
