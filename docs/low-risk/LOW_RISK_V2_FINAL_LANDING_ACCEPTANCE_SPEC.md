# LOW-RISK V2 — FINAL LANDING, SECONDARY ACCEPTANCE & OPERATIONAL CLOSURE SPEC

Status: FROZEN MASTER LANDING CONTRACT  
Audit date: 2026-09-17  
Repository: `fyjk999-cyber/crypto-auto-trading-system`  
Spec branch: `codex/low-risk-final-landing-spec`  
Spec base / audited integration SHA: `19b97849f0f0aad151e70bcfc9911010ceff34a8`  
Audited integration branch: `codex/low-risk-final-convergence`  
Default branch at audit: `main = 784216a926ac2af1431e517efc95ddb1c8e6ace4`  
Trading mode for this entire contract: **PAPER ONLY**  
LIVE authorization: **NO**

---

# 0. PURPOSE

This is the final project-wide implementation, convergence, secondary-review, deployment, natural-evidence, soak and landing contract for Low-Risk V2.

It replaces the practice of treating subsystem receipts as equivalent to final-system acceptance.

The mission is to produce one directly deployable Low-Risk V2 tree with:

- one canonical runtime;
- one migration head;
- one Core-LLM authority path;
- one execution writer;
- factual market data;
- deterministic Risk / ExecutionAuthority safety;
- Growth, News and ML as evidence/learning only;
- independent position-leg accounting where enabled;
- durable macOS operation;
- no fabricated runtime evidence;
- exact-SHA acceptance;
- a complete natural PAPER lifecycle under the final SHA;
- at least 72 hours of continuous final-candidate operation;
- a truthful final receipt.

A prior subsystem `PASS` is not automatically accepted here. Every previously completed subsystem marked **SECONDARY_ACCEPTANCE_REQUIRED** must be rechecked against the final integrated tree.

---

# 1. SOURCES OF TRUTH AUDITED

## 1.1 Current integration candidate

`codex/low-risk-final-convergence`

Audited SHA:

`19b97849f0f0aad151e70bcfc9911010ceff34a8`

The integration commit states that it combines:

- ML final scientific engineering branch;
- News external evidence branch;
- provider durability;
- Runtime Constitution behavior;
- configurable position-leg execution;
- final convergence migration;
- cross-subsystem tests.

This SHA is an **integration candidate**, not yet a final accepted landing SHA.

## 1.2 Default branch divergence

At audit time:

`main = 784216a926ac2af1431e517efc95ddb1c8e6ace4`

Remote comparison reports:

- final-convergence ahead of main: 345 commits;
- final-convergence behind main: 192 commits;
- status: DIVERGED;
- merge base: `889ccc74c45f439830b4c1287032a9191a5e3500`.

Therefore **main MUST NOT be merged blindly into final-convergence and final-convergence MUST NOT be force-pushed over main**.

Every main-only commit must be classified before final landing.

## 1.3 Current important branch heads

At the audit:

- Growth: `01c58a3a1ead1827a09660bbcef10da0a21a9196`
- Core Runtime Constitution: `ad1379cfd933f54e291e2306ceb076450edf987b`
- ML: `f345cee4250bf60fcc5830b1c58b3c580dab51db`
- News: `3fe837bbecfb9d718c2fdb3a3c73389096aa5b02`
- Provider durability: `60e80dd9e3722818559c5a74af6a26455fde9d62`
- Hedge branch tip: `b01e01f714d571a3a7da9b19d88e8f032b69c484`

The Hedge branch tip contains a later documentation commit referring to `deepseek-chat`. It is NOT automatically a valid source for final convergence. The already integrated/accepted Hedge implementation must be evaluated by behavior, not by blindly merging that branch tip.

## 1.4 Open pull requests requiring disposition

The repository currently has open PRs that predate this final convergence and must not remain ambiguous during landing:

- PR #2 — `Close Live-LLM plan acceptance gaps`, head `72e10e63d9860ce87c634d3fbd348040f36eed98`;
- PR #3 — `Integrate Growth V2 into core candidate`, head `b3873d015b40916066dc19243e7d005be5ae3f5b`;
- PR #4 — `Round-2 correctness hardening: fenced publication, exact input/import/retrieval semantics`, head `46c91fc44e63dd72615f4e52b73c2a31336efc77`;
- PR #5 — `test(cleanup): quarantine legacy parallel stacks`, head `9144c9887157c6ef6f1ccd14f538bec1b2ea6e4d`.

All four are unmerged. Some are draft. They MUST be audited for unique behavior before final landing and then either:

- port unique still-required behavior into the landing candidate; or
- record `SUPERSEDED_BY_FINAL_LANDING` with exact evidence; and close/archive them.

No open PR may be merged merely because it has an older PASS receipt.

---

# 2. GLOBAL NON-NEGOTIABLE INVARIANTS

These rules apply to every phase.

## 2.1 Trading safety

- PAPER ONLY.
- LIVE trading remains disabled.
- No forced trade.
- No fake fill.
- No fake exit.
- No fake hedge.
- No fake News event.
- No fabricated ML forward sample.
- No fabricated champion/promotion history.

## 2.2 Authority

Core LLM remains the sole intelligence that may originate new directional risk.

Growth:

`LEARNING_ONLY / EVIDENCE_ONLY`

News:

`EVIDENCE_ONLY`

Model #21:

`LEARNING_ONLY / EVIDENCE_ONLY`

Model #25:

`LEARNING_ONLY / EVIDENCE_ONLY`

Risk:

must not become a pre-trade strategy selector.

ExecutionAuthority:

retains deterministic hard safety gates.

## 2.3 New-risk hard contract

Every new-risk child must remain within the existing constitutional limits:

- allocation <= 25% equity;
- leverage <= 20x;
- invalid TradePlan is rejected, not silently resized;
- new-risk entry requires valid Strategy + TradePlan + Base Exit;
- stale LLM response cannot execute after material state change;
- `UNKNOWN != FAILED` and must reconcile before replacement.

## 2.4 Position management

- no deterministic max-holding-time forced exit;
- time/horizon events wake Core LLM reassessment;
- Risk / Fast Profit / Base Exit protection remains active while LLM is unavailable or thinking;
- old Base Exit remains until atomic replacement succeeds.

## 2.5 Credentials

Never read, print, log, export, paste or expose API secrets.

Credential existence may be tested only through approved wrappers/health interfaces.

## 2.6 Runtime ownership

Final runtime must preserve:

- one execution lease;
- one writer;
- no duplicate lifecycle owner;
- no hidden cron/service with trading-runtime start authority;
- durable user-level launchd;
- no sudo requirement;
- no `/tmp` canonical state.

---

# 3. STATUS CLASSIFICATION

Use only these categories in this mission:

- `SECONDARY_ACCEPTANCE_REQUIRED` — implementation was previously accepted in isolation, but must be re-proven on the final integrated tree.
- `IMPLEMENTATION_REQUIRED` — concrete code/work remains.
- `RUNTIME_VERIFICATION_REQUIRED` — code may exist, but current real process state has not been factually verified.
- `NATURAL_EVIDENCE_REQUIRED` — engineering can pass, but nature/time must produce evidence; never force it.
- `BLOCKED` — cannot proceed without resolving a safety/correctness blocker.
- `PASS` — accepted on the exact final candidate SHA.

---

# 4. CURRENT PROJECT CLOSURE MATRIX

| Area | Current state at audit | Final landing requirement |
|---|---|---|
| Core Runtime Constitution | Previously engineering PASS | SECONDARY_ACCEPTANCE_REQUIRED |
| Growth / Memory | Previously engineering/deployment PASS | SECONDARY_ACCEPTANCE_REQUIRED |
| DeepSeek Flash High policy | Previously PASS | SECONDARY_ACCEPTANCE_REQUIRED |
| Provider durability / single runtime owner | Previously PASS | SECONDARY_ACCEPTANCE_REQUIRED |
| Risk / ExecutionAuthority / Base Exit / Fast Profit | Previously PASS | SECONDARY_ACCEPTANCE_REQUIRED |
| News N5–N10 engineering | Receipt PASS | SECONDARY_ACCEPTANCE_REQUIRED |
| News natural ingestion | Factual evidence exists | SECONDARY_ACCEPTANCE_REQUIRED |
| News real canonical reassessment dispatch | Existing receipt has a dispatch caveat | RUNTIME_VERIFICATION_REQUIRED |
| ML M2–M10 engineering | Receipt PASS | SECONDARY_ACCEPTANCE_REQUIRED |
| ML #21 scientific closure | `CONTINUE_SHADOW` / natural samples pending | NATURAL_EVIDENCE_REQUIRED |
| ML #25 scientific closure | `CONTINUE_SHADOW` / natural samples pending | NATURAL_EVIDENCE_REQUIRED |
| Hedge H0–H7 engineering | Receipt PASS | SECONDARY_ACCEPTANCE_REQUIRED |
| Hedge H8 natural PAPER | accumulating | NATURAL_EVIDENCE_REQUIRED |
| Same-symbol LONG+SHORT execution | configurable but default OFF | IMPLEMENTATION/OPERATIONAL CLOSURE REQUIRED |
| Position-leg backend/API | previously PASS | SECONDARY_ACCEPTANCE_REQUIRED |
| Position-leg frontend | no `position-legs` / `leg_id` wiring found in current App | IMPLEMENTATION_REQUIRED |
| Final migration convergence | test asserts `0042_final_convergence_merge` | SECONDARY_ACCEPTANCE_REQUIRED |
| Final exact-SHA Python full suite | no final-candidate Actions run; no final exact-SHA receipt | REQUIRED |
| Final exact-SHA Ruff | no final exact-SHA receipt | REQUIRED |
| Frontend test/typecheck/build | not covered by Python subsystem receipts | REQUIRED |
| GitHub Actions on final-convergence | zero runs observed | REQUIRED / CI CLOSURE |
| Champion provenance/fingerprint | not found in latest runtime audit | BLOCKED |
| REAL_PROMOTION_GATE | not confirmed | BLOCKED |
| LLM full-pause state | user requested pause; actual pause was not confirmed | RUNTIME_VERIFICATION_REQUIRED |
| Zero-provider-call pause semantics | current offline router can auto-probe | IMPLEMENTATION/VERIFICATION REQUIRED |
| Market service health | latest runtime audit: NOT_VERIFIED | RUNTIME_VERIFICATION_REQUIRED |
| production runner topology | latest runtime audit: per-symbol runners NOT_OBSERVED | RUNTIME_VERIFICATION_REQUIRED |
| Final acceptance harness | no dedicated final soak/acceptance package observed | IMPLEMENTATION_REQUIRED |
| Final complete natural PAPER lifecycle | not yet proven under final candidate SHA | NATURAL_EVIDENCE_REQUIRED |
| >=72h final-candidate soak | not started on a frozen final SHA | NATURAL_EVIDENCE_REQUIRED |
| main reconciliation | main diverged 345/192 | IMPLEMENTATION_REQUIRED |
| final main landing | not done | REQUIRED LAST STEP |

---

# 5. COMPLETED COMPONENTS — MANDATORY SECONDARY ACCEPTANCE

Do NOT rewrite these systems unless the integrated audit finds a concrete defect.

## 5.1 Core Runtime Constitution

Re-prove on final candidate:

- no `TIME_STOP_SAFETY_FALLBACK` behavior;
- holding horizon causes reassessment rather than deterministic close;
- stale-state LLM response rejection;
- fresh-state recontextualization;
- Base Exit continuity / atomic replacement;
- protection precedence;
- offline new-risk prohibition;
- restart behavior.

Expected final flag:

`CORE_RUNTIME_SECONDARY_ACCEPTANCE = PASS`

## 5.2 Growth / Memory

Re-prove:

- factual lifecycle ingestion;
- all required review types;
- K3 -> G1 -> G2 -> H / memory ladder behavior;
- as-of retrieval;
- no future leakage;
- decision lineage;
- Growth cannot trade;
- autonomous worker durability;
- final candidate runtime reads only authorized Growth context.

Expected:

`GROWTH_SECONDARY_ACCEPTANCE = PASS`

## 5.3 DeepSeek / provider policy

Re-prove:

- production canonical model resolves to `deepseek-flash`;
- thinking = true;
- reasoning effort = high;
- `TRADING_LLM_MODEL` owns production selection;
- generic `LLM_MODEL` cannot silently change trading model;
- `deepseek-v4-pro` is forbidden;
- `deepseek-flash-high` is not a literal model id;
- configured/effective/last-successful diagnostics remain distinct and truthful;
- strict JSON bounded repair behavior remains intact;
- no hidden provider path can create an order.

Expected:

`FLASH_HIGH_SECONDARY_ACCEPTANCE = PASS`

`PROVIDER_DURABILITY_SECONDARY_ACCEPTANCE = PASS`

## 5.4 Risk / execution / exits

Re-prove:

- ExecutionAuthority hard contract;
- allocation/leverage hard bounds;
- new-risk authority;
- reduce-only behavior;
- UNKNOWN reconciliation;
- duplicate-order prevention;
- oversell prevention;
- Base Exit persistence;
- Fast Profit Protection can only reduce/close and only under constitutional conditions;
- Risk cannot become strategy/sizing authority.

Expected:

`EXECUTION_SAFETY_SECONDARY_ACCEPTANCE = PASS`

## 5.5 News N5–N10

Existing component evidence is strong, including factual provider ingestion, material events, outcome review and read-only API.

Re-prove on the final integrated candidate:

- materiality/freshness/novelty/contradiction;
- as-of bounded Chief context;
- prompt-injection boundary;
- decision refs;
- reassessment dedup;
- stale response protection;
- worker heartbeat/cursor restart safety;
- backpressure;
- News has zero order/new-risk/exit authority;
- provider degradation is truthful;
- live natural request actually traverses the canonical final runtime dispatch path when such a request exists.

The existing receipt caveat that natural requests were queued and exactly-once dispatch was proven on a copied request set MUST be closed by final-runtime evidence when naturally available.

Expected:

`NEWS_SECONDARY_ACCEPTANCE = PASS`

Operational state may remain:

`NEWS_NATURAL_CANONICAL_DISPATCH = AUTONOMOUSLY_ACCUMULATING`

if no natural material dispatch occurs during the observation window.

## 5.6 ML M2–M10 engineering

Existing receipt states engineering PASS for:

- #01–#24 decision-time evidence freeze;
- label-v2 final training eligibility;
- #21 chronological training;
- #21 true-forward machinery;
- #21 promotion/cutover machinery;
- literal XGBoost #25;
- #25 true-forward machinery;
- #25 promotion/cutover machinery;
- autonomous retrain/rollback.

Re-prove all of those on the final integrated tree.

Do NOT require natural promotion to call engineering PASS.

Expected:

`ML_ENGINEERING_SECONDARY_ACCEPTANCE = PASS`

Scientific status remains factual:

`ML_FINAL_SCIENTIFIC_CLOSURE = PASS | AUTONOMOUSLY_ACCUMULATING`

## 5.7 Hedge / position-leg backend

Re-prove H0–H7 behavior:

- canonical independent leg rows;
- order allocation;
- fill allocation;
- partial fills;
- independent exits;
- fees/funding/PnL;
- reconcile/restart;
- orphan-fill detection;
- UNKNOWN duplicate protection;
- reverse lineage;
- gross-risk view;
- read-only leg API;
- Growth leg lineage.

Expected:

`HEDGE_ENGINEERING_SECONDARY_ACCEPTANCE = PASS`

H8 remains natural evidence until proven under final candidate.

---

# 6. GAP A — FINAL INTEGRATED TEST EVIDENCE DOES NOT YET EXIST

Subsystem test receipts are not a substitute for final-tree tests.

At audit time:

- no GitHub Actions run exists for `codex/low-risk-final-convergence`;
- CI workflow triggers only on `push: main` and `pull_request`;
- there is no final exact-SHA full regression receipt tied to `19b97849...`.

Before any final candidate freeze, run from a clean integrated worktree:

- focused convergence tests;
- all Low-Risk tests;
- all News tests;
- all ML tests;
- all Hedge/leg tests;
- Growth tests;
- provider/LLM tests;
- full `pytest tests -q`;
- `ruff check src scripts tests`;
- migration head check;
- clean DB migration upgrade test;
- upgrade from a realistic existing DB backup copy;
- frontend `npm ci`;
- frontend `npm test`;
- frontend `npm run typecheck`;
- frontend `npm run build`.

Fresh counts only.

## 6.1 CI closure

Choose one auditable path:

A. create a PR from the final landing branch so existing `pull_request` CI actually runs; or

B. minimally extend CI with `workflow_dispatch` / final-landing branch trigger and run it.

Do not claim CI PASS merely because local tests passed.

Expected:

`FINAL_INTEGRATED_PYTEST = PASS`

`FINAL_INTEGRATED_RUFF = PASS`

`FINAL_FRONTEND_CHECK = PASS`

`FINAL_CI = PASS`

---

# 7. GAP B — CHAMPION PROVENANCE / FINGERPRINT / REAL PROMOTION GATE

Latest runtime audit reported:

- `CHAMPION_ID = NOT_FOUND`;
- `STORED_FINGERPRINT = NOT_FOUND`;
- `RECOMPUTED_FINGERPRINT = NOT_COMPUTED`;
- `FINGERPRINT_MATCH = NOT_VERIFIED`;
- `REAL_PROMOTION_GATE = cannot be confirmed`.

This is a final acceptance blocker.

## 7.1 Required forensic work

Search canonical:

- source;
- DB schema/data;
- model registry;
- strategy registry;
- promotion receipts;
- deployment receipts;
- runtime diagnostics;
- Git history;
- artifact manifests.

Determine whether a factual promoted champion exists.

If one exists:

- identify champion source of truth;
- recover stored fingerprint;
- recover canonical fingerprint algorithm/version;
- independently recompute from canonical inputs;
- compare;
- prove promotion gate with valid and tampered cases.

If no historical fingerprint ever existed:

- do NOT fabricate it;
- implement prospective atomic champion identity + fingerprint persistence;
- implement independent verifier;
- require the next factual promotion to produce first valid persisted evidence;
- historical state remains `UNAVAILABLE`.

Required final flags:

`CHAMPION_SOURCE_OF_TRUTH = ...`

`FINGERPRINT_CONTRACT = PASS`

`FINGERPRINT_MATCH = YES | NOT_APPLICABLE_NO_HISTORICAL_CHAMPION`

`REAL_PROMOTION_GATE = PASS`

A fabricated old fingerprint is P0.

---

# 8. GAP C — LLM FULL-PAUSE SEMANTICS MUST BE REAL

A user-level operational instruction requested that all Low-Risk LLM provider calls be paused while preserving market data, Risk, PAPER runtime, lease and single writer.

The last attempted local handoff did not execute, so current pause state must be treated as:

`LLM_PAUSE_STATE = UNVERIFIED`

Do not assume paused and do not assume resumed.

## 8.1 Static code concern

The current `CoreLLMRouter` offline mechanism uses timed probe windows. When an offline probe window is reached it attempts provider recovery.

Therefore `LLM_OFFLINE_MODE` by itself is not necessarily equivalent to a user-requested **zero outbound provider calls** pause.

## 8.2 Required pause gate

Implement or verify an explicit runtime-level provider-call pause gate that:

- blocks DeepSeek calls;
- blocks GLM calls;
- blocks automatic provider probes;
- returns fail-closed/offline semantics to trading logic;
- keeps market data alive;
- keeps Risk alive;
- keeps deterministic exits alive;
- keeps PAPER runtime alive;
- keeps lease held;
- keeps single writer;
- does not change model selection;
- does not change strategy parameters;
- does not read credentials;
- is observable through diagnostics;
- survives runtime restart when intentionally configured;
- can only be resumed through an explicit operator action.

Tests must prove zero provider method invocations while paused, including after the normal offline probe duration passes.

Expected:

`LLM_PROVIDER_PAUSE_GATE = PASS`

`PAUSE_BLOCKS_PRIMARY = PASS`

`PAUSE_BLOCKS_BACKUP = PASS`

`PAUSE_BLOCKS_AUTO_PROBES = PASS`

`PAUSE_PRESERVES_MARKET_RISK_RUNTIME = PASS`

No LLM provider call may be resumed during this mission without explicit user authorization.

---

# 9. GAP D — HEDGE / POSITION-LEG OPERATIONAL CLOSURE

Final convergence makes leg execution configurable, but default remains OFF.

This is safer than silently enabling it, but it means the final project does not yet have factual operational proof of true same-symbol LONG + SHORT execution under the integrated candidate.

## 9.1 Before enabling in PAPER

Prove:

- position-leg rows are canonical truth;
- net position is view only;
- every new leg order requires leg_id + decision + plan lineage;
- fills allocate exactly once;
- partial fills are independent;
- exits cap to leg remaining quantity;
- UNKNOWN blocks replacement;
- restart/reconcile safe;
- net-zero does not hide gross risk;
- API gross view correct;
- risk and execution guards operate on correct gross exposure.

## 9.2 PAPER activation

Only after the above secondary acceptance passes may the final candidate run with:

`LEG_EXECUTION_ENABLED=true`

in PAPER.

This is not LIVE authorization.

Do not force a HEDGE or REVERSE decision.

Wait for a natural same-symbol dual-leg event.

Required natural evidence:

- independent LONG and SHORT leg identities;
- independent TradePlans;
- independent Base Exits;
- order/fill lineage;
- quantities;
- fees/funding;
- PnL;
- reconciliation;
- at least one natural close/reduce path without cross-leg corruption.

Expected:

`HEDGE_ENGINEERING = PASS`

`HEDGE_OPERATIONAL_EVIDENCE = PASS | AUTONOMOUSLY_ACCUMULATING`

Natural absence is not P0.

---

# 10. GAP E — POSITION-LEG FRONTEND IS MISSING

Current final-convergence `frontend/src/App.tsx` contains no direct `position-legs` or `leg_id` integration.

Backend-only visibility is insufficient for a directly operable final project.

Implement a read-only leg view in the control center.

Minimum UI:

- symbol;
- leg_id;
- LONG/SHORT;
- status;
- quantity / remaining quantity;
- avg entry;
- mark;
- unrealized PnL;
- realized PnL;
- fees;
- funding;
- TradePlan id;
- decision id;
- Base Exit state;
- reconciliation state;
- order/fill count;
- reverse lineage where applicable;
- explicit gross exposure summary when both sides coexist.

UI MUST NOT create new order authority.

Use existing read-only position-leg APIs.

Tests:

- dual leg rendering;
- single leg rendering;
- net-zero/gross-risk warning;
- empty state;
- backend unavailable;
- stale/degraded state;
- no write endpoint invoked.

Expected:

`POSITION_LEG_FRONTEND = PASS`

---

# 11. GAP F — ML SCIENTIFIC CLOSURE IS NATURAL, NOT ENGINEERING

Current ML engineering receipt is acceptable as a prior isolated result, but final scientific closure is still naturally accumulating.

Do not change thresholds merely to reach PASS.

For #21 final PASS requires factual:

- label-v2 training;
- chronological validation;
- post-cost validation;
- true-forward minimum;
- deterministic promotion;
- ACTIVE registry artifact;
- final runtime actually uses ACTIVE artifact.

For #25 final PASS requires factual:

- frozen #01–#24 evidence;
- versioned #21 dependency;
- literal XGBoost;
- chronological validation;
- post-cost validation;
- true-forward minimum;
- deterministic promotion;
- ACTIVE registry artifact;
- final runtime actually uses ACTIVE XGBoost artifact.

If not enough natural data:

`ML_FINAL_SCIENTIFIC_CLOSURE = AUTONOMOUSLY_ACCUMULATING`

This does not block engineering deployment, but the final receipt must disclose it.

---

# 12. GAP G — NEWS FINAL-RUNTIME DISPATCH PROOF

Existing News evidence proves ingestion, events, evidence and natural reassessment requests.

The prior acceptance receipt states that natural canonical reassessment requests were queued until the next canonical runtime tick and that exactly-once dispatch was proven on a copy of the natural request rows.

Final landing should observe the actual final runtime consuming a natural queued request through:

News event
-> NewsEvidence
-> NewsReassessmentRequest
-> canonical runtime tick
-> fresh state
-> Core LLM request or fail-closed paused state
-> decision/ref persistence

If LLM provider calls are intentionally paused, the correct proof is that the request reaches the canonical dispatcher and fails closed without outbound LLM call; after explicit resume, a future natural request can prove full LLM dispatch.

Never manufacture a headline.

Expected:

`NEWS_FINAL_RUNTIME_DISPATCH = PASS | AUTONOMOUSLY_ACCUMULATING`

---

# 13. GAP H — MARKET/RUNNER RUNTIME TOPOLOGY NOT VERIFIED

Latest runtime evidence reported:

- BTC runner: NOT_OBSERVED;
- ETH runner: NOT_OBSERVED;
- SOL runner: NOT_OBSERVED;
- XRP runner: NOT_OBSERVED;
- market service health: NOT_VERIFIED.

Do not assume one process per symbol.

For the final runtime, document the factual topology:

- one shared process vs per-symbol workers;
- launchd owner;
- PID(s);
- listening endpoint(s);
- running SHA;
- market feed health;
- opportunity scanner health;
- lease;
- single writer;
- kill switch;
- DB path;
- service heartbeats.

Expected:

`PRODUCTION_RUNNER_TOPOLOGY = VERIFIED`

`MARKET_SERVICE_HEALTH = PASS`

---

# 14. GAP I — FINAL ACCEPTANCE / SOAK HARNESS

No dedicated, finalized 72-hour acceptance harness package was observed in the final-convergence tree during this audit.

Build one before freezing the final candidate.

Recommended canonical package:

`scripts/acceptance/`

or another single clearly documented path.

## 14.1 Harness properties

It must be read-only with respect to strategy behavior.

It may:

- query health endpoints;
- query DB read-only;
- inspect launchd/process state;
- inspect logs;
- calculate metrics;
- detect P0 invariants;
- write acceptance evidence files.

It may NOT:

- force trades;
- change strategy parameters;
- change model thresholds;
- promote ML manually;
- create fake News;
- repair production DB silently;
- place/cancel orders;
- enable LIVE.

## 14.2 Monitor at minimum

- exact running SHA;
- uptime / restart gaps;
- PAPER mode;
- lease;
- single writer;
- kill switch;
- market data freshness;
- scanner health;
- News worker;
- Growth worker;
- ML collector/trainer;
- provider pause status;
- provider configured/effective model when resumed;
- LLM latency/outcomes when calls are authorized;
- decisions;
- plans;
- orders;
- fills;
- partial fills;
- UNKNOWN states;
- reconciliation;
- Base Exit;
- deterministic exits;
- hedge legs;
- Growth lineage;
- ML registry/artifacts;
- News lineage.

## 14.3 Automatic P0 detection

At minimum flag:

- duplicate order;
- oversell;
- stale decision executed;
- offline/paused LLM creating new risk;
- >25% child allocation;
- >20x leverage;
- missing TradePlan;
- missing Base Exit;
- ghost fill;
- exit qty > leg remaining;
- unresolved UNKNOWN followed by replacement;
- multiple execution writers;
- lease loss with continued order creation;
- LIVE enabled;
- runtime SHA drift;
- destructive DB migration;
- fake/synthetic evidence represented as factual;
- unapproved provider/model drift.

Expected:

`FINAL_ACCEPTANCE_HARNESS_ENGINEERING = PASS`

---

# 15. GAP J — OPEN PR / LEGACY PARALLEL STACK DISPOSITION

Before final candidate freeze:

## 15.1 PR #2

Audit every unique behavioral fix from head `72e10e63d9860ce87c634d3fbd348040f36eed98` against the final landing tree, especially:

- one wall-clock Chief/tool budget;
- OKX SWAP volume semantics;
- exact-symbol retrieval;
- research applicability fail-closed;
- versioned tool contracts;
- execution-cost evidence semantics;
- position-review concurrency/deadline.

Port anything missing. Otherwise record exact tests/code proving supersession.

## 15.2 PR #3

Audit Growth V2 integration behavior and migration semantics against current Growth/Low-Risk final tree.

Do not merge old migration lineage blindly.

## 15.3 PR #4

This PR explicitly records a previous `CHANGES_REQUIRED` remediation. Audit unique behaviors such as:

- fenced atomic knowledge publication;
- exact job input/revision binding;
- attempt recovery;
- no-publish-input semantics;
- provider exception durability;
- correct revoke/expire known_at;
- proposition identity;
- real DB import binding;
- authorized rollback;
- scoped retrieval fail-closed;
- serialized evidence budget;
- canonical trace path.

If current final Growth implementation does not contain an equivalent, port it before landing.

Do not import its old migration chain blindly.

## 15.4 PR #5

Audit the legacy-stack quarantine proposal.

Determine whether any currently active duplicate/ghost stack remains importable/executable in the final tree.

If the current final tree still contains dangerous parallel runtime stacks, implement a safe quarantine/removal with import-smoke/compile/full-suite evidence.

If not needed, document why PR #5 is superseded.

## 15.5 Closure

After evidence is written, every stale PR must be classified:

- `PORTED`
- `SUPERSEDED`
- `REJECTED_WITH_REASON`

and no ambiguous old PR should remain a possible promotion source.

Expected:

`OPEN_PR_DISPOSITION = PASS`

---

# 16. GAP K — MAIN DIVERGENCE / FINAL LANDING STRATEGY

Because main is 345 commits behind and 192 commits ahead relative to final-convergence, landing must be deliberate.

## 16.1 Main-only audit

Produce a machine-generated list of all main-only commits since merge base.

Classify each into:

- REQUIRED_RUNTIME_BEHAVIOR;
- REQUIRED_SECURITY_FIX;
- REQUIRED_DATA/MIGRATION;
- REQUIRED_DOC/EVIDENCE;
- HISTORICAL/JOURNAL_ONLY;
- SUPERSEDED;
- CONFLICTING/REQUIRES_DECISION.

Do not discard a main-only security or correctness fix.

Do not import historical journal state into canonical runtime logic merely because it is newer on main.

## 16.2 Landing branch

Create a dedicated implementation branch from the audited final integration tree, for example:

`codex/low-risk-final-landing`

Port/reconcile required main-only behavior into this branch.

Resolve all migrations to one head.

Run full acceptance there.

## 16.3 Do not merge to main before soak

The SHA used for the 72-hour acceptance must be frozen.

Only after the final candidate passes engineering and natural acceptance should it be promoted to main.

If the main merge creates a different commit SHA, verify tree identity and run post-merge exact-SHA regression before calling `MAIN_LANDING = PASS`.

No force push to main.

---

# 17. PHASE ORDER — REQUIRED EXECUTION PLAN

## Phase 0 — Safety / factual baseline

Record without mutation:

- current local worktrees;
- current branch/SHA;
- runtime SHA;
- PAPER mode;
- DB paths;
- DB backups;
- launchd jobs/PIDs;
- market health;
- lease;
- single writer;
- kill switch;
- LLM pause state;
- configured/effective provider/model only through diagnostics;
- News/Growth/ML service state.

Never print credentials.

## Phase 1 — Repository forensics

Audit:

- current integration tree;
- main-only commits;
- PR #2–#5 unique behavior;
- migration graph;
- duplicate runtime paths;
- stale provider/model paths;
- champion/promotion source of truth.

Produce an auditable matrix before changing behavior.

## Phase 2 — Secondary acceptance of already completed systems

Re-run exact integrated tests and static authority checks for:

- Runtime Constitution;
- Growth;
- Flash/provider durability;
- Risk/Execution/Exits;
- News;
- ML engineering;
- Hedge backend/API;
- migrations.

Fix only concrete regressions.

## Phase 3 — Implement remaining engineering gaps

Required work includes, where confirmed by Phase 1:

- champion fingerprint + promotion gate closure;
- explicit zero-call LLM pause gate;
- final acceptance harness;
- position-leg frontend;
- any missing PR #2/#4 correctness behavior;
- duplicate-stack quarantine if still necessary;
- final CI path;
- main reconciliation;
- leg execution operational readiness.

## Phase 4 — Integrated exact-SHA engineering acceptance

Run all backend, frontend, migration, lint, authority and chaos tests.

No deployment until PASS.

## Phase 5 — Freeze `FINAL_LOW_RISK_CANDIDATE`

After all code changes stop:

- commit;
- push;
- verify remote SHA;
- verify worktree clean;
- create detached exact-SHA worktree;
- repeat acceptance;
- generate candidate receipt.

The candidate SHA is immutable for soak.

## Phase 6 — Deploy exact final candidate in PAPER

Backup DBs first.

Deploy exact SHA.

Verify:

- PAPER;
- launchd ownership;
- running SHA;
- migrations;
- market health;
- lease;
- single writer;
- Risk;
- deterministic exits;
- News;
- Growth;
- ML;
- position-leg backend;
- frontend.

Preserve LLM pause unless explicit user authorization to resume has been given.

## Phase 7 — Controlled LLM resume gate

Only execute this phase after explicit operator authorization.

When authorized:

- resume canonical provider calls without model switch;
- configured model must remain `deepseek-flash`;
- verify effective successful call from actual canonical runtime;
- no `deepseek-chat`;
- no `deepseek-v4-pro`;
- observe natural decisions only.

If authorization is absent:

stay paused and fail closed.

## Phase 8 — Natural PAPER lifecycle

Require at least one complete natural lifecycle under the exact candidate SHA:

market fact
-> opportunity
-> evidence
-> Core LLM decision when calls are authorized
-> TradePlan
-> Base Exit
-> execution
-> fill
-> open position
-> position management
-> natural/deterministic valid exit
-> close
-> reconciliation
-> episode
-> Growth review lineage

No forced lifecycle.

If hedge/reverse naturally occurs, capture H8 evidence.

## Phase 9 — 72-hour continuous soak

Official clock starts only after:

- exact final candidate frozen;
- engineering gates PASS;
- exact candidate deployed;
- acceptance harness active.

Requirements:

- >=72 continuous hours on same candidate tree;
- no unresolved P0;
- service interruptions documented;
- if a natural lifecycle starts near the end and closes after 72h, continue until closure;
- if 72h passes with no natural complete trade, soak health can PASS but final lifecycle acceptance remains incomplete and observation continues.

## Phase 10 — Final main landing

Only after required acceptance:

- finalize main-only reconciliation evidence;
- create/review landing PR;
- CI PASS;
- merge without force;
- verify final main tree;
- rerun post-merge exact-SHA regression if SHA/tree changed;
- do NOT automatically enable LIVE.

---

# 18. EXACT TEST MATRIX

The final landing candidate must run at least:

## Backend

- `pytest tests/low_risk -q`
- `pytest tests/news -q`
- focused Growth suites
- focused ML suites
- focused Hedge suites
- focused provider/LLM suites
- focused runtime constitution suites
- focused reconciliation/execution suites
- `pytest tests -q`
- `ruff check src scripts tests`

## Migrations

- assert exactly one head;
- fresh DB `upgrade head`;
- upgrade from production-like copied DB;
- downgrade only if project migration policy requires and is safe;
- verify row-count/data preservation for critical tables.

## Frontend

From `frontend/`:

- `npm ci`
- `npm test`
- `npm run typecheck`
- `npm run build`

## Static authority

Prove no direct order path from:

- Growth;
- News;
- #21;
- #25;
- scanner;
- expert evidence engine.

## Pause

Prove provider-call pause suppresses:

- primary call;
- backup call;
- offline auto-probe;
- News-triggered LLM call;
- position-review LLM call;
- opportunity LLM call.

while market/Risk/runtime stay alive.

## Concurrency / safety

Prove:

- single writer;
- lease loss safe;
- stale response safe;
- duplicate order safe;
- UNKNOWN safe;
- partial fill safe;
- position leg safe;
- restart safe.

---

# 19. REQUIRED FINAL ACCEPTANCE HARNESS OUTPUT

Every sample/interval should be timestamped and bound to:

- candidate SHA;
- process PID;
- runtime source path;
- DB path;
- PAPER mode.

Final evidence package should include:

- `baseline.json`;
- `service_topology.json`;
- `migration_status.json`;
- `test_receipt.json`;
- `frontend_receipt.json`;
- `llm_pause_resume_receipt.json`;
- `provider_diagnostics.json` without secrets;
- `champion_promotion_receipt.json`;
- `natural_lifecycle.json`;
- `hedge_evidence.json` when naturally available;
- `ml_scientific_status.json`;
- `news_runtime_status.json`;
- `growth_status.json`;
- `soak_samples.ndjson`;
- `p0_events.ndjson`;
- `final_receipt.md`.

File names may differ, but equivalent evidence is mandatory.

---

# 20. P0 BLOCKERS

Any of these blocks final PASS:

- LIVE trading enabled;
- credentials exposed/read into logs;
- multiple execution writers;
- lease bypass;
- stale LLM decision executes;
- LLM offline/paused state originates new risk;
- user-requested full pause still allows provider auto-probe;
- model/provider drift to unapproved model;
- duplicate order;
- ghost fill;
- oversell;
- unresolved UNKNOWN replaced;
- >25% new-risk child;
- >20x leverage;
- missing TradePlan/Base Exit for entry;
- corrupt leg accounting causing cross-leg exit/qty corruption;
- destructive migration/data loss;
- future leakage into ML/Growth/News evidence;
- historical replay counted as ML true forward;
- #25 not literal XGBoost while represented as such;
- fabricated champion fingerprint;
- fabricated promotion;
- promotion gate not factually verifiable;
- fake natural trade/news/ML evidence;
- main merge discards unidentified required commits;
- final runtime SHA differs from accepted candidate without re-acceptance.

---

# 21. P1 / NON-BLOCKING ACCUMULATION STATES

These can remain after engineering PASS if truthfully disclosed:

- insufficient natural #21 forward samples;
- insufficient natural #25 forward samples;
- no natural same-symbol hedge yet;
- no natural material News dispatch during observation;
- sparse regime coverage;
- degraded News provider coverage with at least one factual provider healthy;
- final natural trade lifecycle still waiting after otherwise healthy soak.

They do not justify lowering thresholds or manufacturing evidence.

---

# 22. FINAL CANDIDATE DEFINITION

A SHA may be named `FINAL_LOW_RISK_CANDIDATE` only when:

1. all IMPLEMENTATION_REQUIRED items are closed or explicitly removed by documented project decision;
2. all SECONDARY_ACCEPTANCE_REQUIRED components pass on the integrated tree;
3. champion/promotion gate blocker is closed;
4. LLM pause gate exists and user-requested pause semantics are honored;
5. one migration head;
6. backend full suite PASS;
7. Ruff PASS;
8. frontend check PASS;
9. CI path PASS;
10. worktree clean;
11. remote SHA exact;
12. detached exact-SHA acceptance PASS;
13. PAPER deployment procedure exists and DB backups are defined;
14. acceptance harness engineering PASS.

Natural evidence may still be accumulating at the moment of freeze, but must be truthfully represented.

---

# 23. FINAL SYSTEM PASS DEFINITION

`FINAL_LOW_RISK_SYSTEM = PASS` requires all engineering gates plus:

- exact candidate deployed in PAPER;
- market/risk/runtime/lease/single-writer healthy;
- provider state consistent with explicit operator pause/resume instruction;
- at least one complete natural PAPER lifecycle under the exact final candidate SHA;
- >=72 hours continuous candidate soak;
- no unresolved P0;
- if ML natural promotion thresholds are still not met, overall system engineering/operational PASS may coexist with `ML_FINAL_SCIENTIFIC_CLOSURE = AUTONOMOUSLY_ACCUMULATING`, but this must be explicit;
- if no natural hedge occurred, `HEDGE_OPERATIONAL_EVIDENCE = AUTONOMOUSLY_ACCUMULATING` must remain explicit;
- main landing completed with no unreviewed main-only behavior loss.

LIVE remains disabled after PASS unless a separate explicit LIVE authorization project is performed.

---

# 24. REQUIRED FINAL RECEIPT

Return exact values for:

```text
AUDIT_UTC =
SPEC_SHA =
STARTING_INTEGRATION_SHA = 19b97849f0f0aad151e70bcfc9911010ceff34a8
LANDING_BRANCH =
FINAL_LOW_RISK_CANDIDATE_SHA =
REMOTE_SHA_MATCH =
WORKTREE_CLEAN =
DETACHED_EXACT_SHA_ACCEPTANCE =

MAIN_SHA_BEFORE = 784216a926ac2af1431e517efc95ddb1c8e6ace4
MAIN_DIVERGENCE_AUDITED =
MAIN_ONLY_COMMITS_CLASSIFIED =
MAIN_LANDING_SHA =
MAIN_TREE_MATCH =

OPEN_PR_2_DISPOSITION =
OPEN_PR_3_DISPOSITION =
OPEN_PR_4_DISPOSITION =
OPEN_PR_5_DISPOSITION =
OPEN_PR_DISPOSITION =

CORE_RUNTIME_SECONDARY_ACCEPTANCE =
GROWTH_SECONDARY_ACCEPTANCE =
FLASH_HIGH_SECONDARY_ACCEPTANCE =
PROVIDER_DURABILITY_SECONDARY_ACCEPTANCE =
EXECUTION_SAFETY_SECONDARY_ACCEPTANCE =
NEWS_SECONDARY_ACCEPTANCE =
ML_ENGINEERING_SECONDARY_ACCEPTANCE =
HEDGE_ENGINEERING_SECONDARY_ACCEPTANCE =
MIGRATION_SECONDARY_ACCEPTANCE =

POSITION_LEG_FRONTEND =
HEDGE_OPERATIONAL_EVIDENCE =
NEWS_FINAL_RUNTIME_DISPATCH =
ML_FINAL_SCIENTIFIC_CLOSURE =

CHAMPION_SOURCE_OF_TRUTH =
CHAMPION_ID =
STORED_FINGERPRINT =
RECOMPUTED_FINGERPRINT =
FINGERPRINT_MATCH =
REAL_PROMOTION_GATE =

LLM_PAUSE_STATE =
LLM_PROVIDER_PAUSE_GATE =
PAUSE_BLOCKS_PRIMARY =
PAUSE_BLOCKS_BACKUP =
PAUSE_BLOCKS_AUTO_PROBES =
LLM_PROVIDER_CALLS_DURING_PAUSE =

LLM_RESUME_AUTHORIZED =
CONFIGURED_PROVIDER =
CONFIGURED_MODEL =
EFFECTIVE_PROVIDER =
EFFECTIVE_MODEL =
DEEPSEEK_CHAT_NEW_CALLS =
DEEPSEEK_V4_PRO_NEW_CALLS =

PAPER =
LIVE_TRADING_ENABLED = false
RUNTIME_RUNNING =
RUNNING_SHA =
PRODUCTION_RUNNER_TOPOLOGY =
MARKET_SERVICE_HEALTH =
LEASE =
SINGLE_WRITER =
KILL_SWITCH =

GROWTH_SERVICE =
NEWS_SERVICE =
ML_COLLECTOR_SERVICE =
ML_TRAINER_SERVICE =
HEARTBEATS_ADVANCING =

MIGRATION_HEAD =
MIGRATION_COUNT =
DB_BACKUPS =

FOCUSED_LOW_RISK_TESTS =
FOCUSED_NEWS_TESTS =
FOCUSED_ML_TESTS =
FOCUSED_HEDGE_TESTS =
FOCUSED_GROWTH_TESTS =
FOCUSED_PROVIDER_TESTS =
FULL_TEST_SUITE =
RUFF =
FRONTEND_TESTS =
FRONTEND_TYPECHECK =
FRONTEND_BUILD =
CI =

FINAL_ACCEPTANCE_HARNESS_ENGINEERING =
NATURAL_COMPLETE_PAPER_LIFECYCLE =
NATURAL_LIFECYCLE_ID =
NATURAL_LIFECYCLE_ENTRY_TS =
NATURAL_LIFECYCLE_EXIT_TS =

SOAK_START_UTC =
SOAK_END_UTC =
SOAK_CONTINUOUS_HOURS =
SOAK_RESTART_GAPS =
SOAK_P0_COUNT =
SOAK_STATUS =

P0_BLOCKERS =
P1_ISSUES =

FINAL_ENGINEERING_STATUS = PASS | PARTIAL | BLOCKED
FINAL_OPERATIONAL_STATUS = PASS | AUTONOMOUSLY_ACCUMULATING | PARTIAL | BLOCKED
FINAL_LOW_RISK_SYSTEM = PASS | PARTIAL | BLOCKED
```

---

# 25. EXECUTION DISCIPLINE

Harness/Codex must continue phase-to-phase autonomously for ordinary engineering work.

Do not stop merely to report a normal checkpoint.

Stop only for a genuine P0, destructive-data risk, credential exposure risk, an unresolved architectural contradiction, or an action that explicitly requires user authorization.

Actions that require explicit user authorization in this contract include:

- resuming LLM provider calls after a user-requested pause;
- enabling LIVE trading;
- destructive DB operations;
- force-pushing protected/canonical history;
- changing strategy risk policy/parameters beyond bug-compatible implementation.

Natural data/time insufficiency is not a P0.

---

# 26. DEFINITION OF DONE

The project is directly landable when there is no remaining ambiguous parallel source of truth and the following chain is factual:

```text
AUDITED FINAL TREE
-> all prior completed subsystems secondarily accepted
-> all concrete code gaps closed
-> champion/promotion provenance verified
-> explicit zero-call LLM pause gate verified
-> backend + frontend + migration + CI PASS
-> exact final candidate frozen
-> exact final candidate deployed PAPER-only
-> factual runtime topology/health verified
-> optional LLM resume only with explicit authorization
-> natural complete PAPER lifecycle
-> >=72h continuous acceptance soak
-> final evidence package
-> reconciled main landing
-> post-merge verification
```

No receipt, previous branch PASS, historical test count, or synthetic episode may substitute for this chain.
