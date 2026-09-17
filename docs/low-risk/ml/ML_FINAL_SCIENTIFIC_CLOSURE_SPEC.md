# LOW-RISK ML — FINAL SCIENTIFIC CLOSURE SPEC

Status: FROZEN TARGET CONTRACT
Repository: fyjk999-cyber/crypto-auto-trading-system
Baseline branch: codex/low-risk-v2-ml-closure
Baseline SHA: 8dc0ca43451372b877f95bf7bc054170492a04ec
Scope: Low-Risk ML subsystem only
Authority: LEARNING_ONLY / EVIDENCE_ONLY
Trading mode: PAPER only until final integrated system acceptance

This document defines the final target for the Low-Risk ML subsystem. It refines the ML portions of `docs/low-risk/LOW_RISK_V2_MASTER_SPEC.md`; it does not replace the Low-Risk V2 constitution.

The implementation must evolve the existing ML collector/trainer/registry/expert-evidence architecture in place. Do not build a parallel trading stack. Do not alter Growth authority, Risk authority, ExecutionAuthority, Core-LLM authority, or live-trading policy.

---

## 0. VERIFIED BASELINE AND WHY THIS SPEC EXISTS

The baseline already has substantial autonomous ML engineering:

- durable scan snapshot collection;
- candidate/control sampling;
- readiness evaluation;
- immutable dataset freeze;
- model registry;
- chronological walk-forward utilities;
- post-cost validation;
- shadow storage;
- trainer/orchestrator;
- macOS launchd wrappers;
- autonomous collector/trainer services.

However, final scientific closure is not yet complete on the baseline.

Verified gaps at the baseline include:

1. `scripts/ml_collector.py` writes `label-v1` using the price observed at label-processing time after maturity rather than reconstructing the exact factual price/path for each `T0 + horizon`; it also sets `future_high == future_low == current price`.
2. `src/crypto_trader/ml_orchestrator.py` creates “shadow” predictions from the tail of the already-known historical training dataset. This is not true forward shadow.
3. `OpportunityScannerService._collect_ml_snapshots()` calls `decision_time_features(facts)` without passing the 1–24 expert evidence into the persisted snapshot, so `model_evidence` required by the #25 meta pipeline is not factually frozen.
4. #21 and #25 in `src/crypto_trader/factors/expert/models.py` are still marked `PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED`; an ACTIVE registry artifact is not yet the live evidence source.
5. #25 training currently uses the project logistic fitter; the V2 target requires an actual XGBoost meta forecast.
6. Final promotion/cutover has not yet been proven through factual forward observations.

Therefore:

```
AUTONOMOUS_ML_INFRASTRUCTURE = IMPLEMENTED
ML_FINAL_SCIENTIFIC_CLOSURE = NOT_YET_COMPLETE
```

---

# 1. NON-NEGOTIABLE AUTHORITY AND SAFETY

## 1.1 Authority

Models #21 and #25 are evidence only.

They may NOT:

- create an order;
- originate OPEN / ADD / HEDGE / REVERSE;
- choose leverage;
- choose position size;
- bypass Core LLM;
- bypass Risk protections;
- bypass ExecutionAuthority;
- change Base Exit;
- directly promote themselves.

The canonical authority remains:

```
market facts
  -> expert evidence
  -> Core LLM
  -> TradePlan / structured intent
  -> execution safety
  -> PAPER broker/runtime
```

## 1.2 No fabricated evidence

Forbidden:

- synthetic labels presented as factual;
- clock acceleration;
- fake forward-shadow rows;
- replayed historical samples counted as forward shadow;
- forced promotion;
- fabricated model results;
- fake ACTIVE artifact;
- synthetic fills/trades solely for acceptance.

## 1.3 Preserve parallel Growth work

This ML task runs in parallel with Growth/Memory.

Do NOT modify:

- `codex/low-risk-growth-memory-autonomous-v2`;
- Growth migrations;
- Growth worker/service;
- Growth retrieval;
- `com.lowrisk.growth`;
- Growth runtime DB.

ML may consume no Growth authority. Growth may later consume ML evidence only through the final integrated system.

## 1.4 Flash High out of scope

Canonical DeepSeek Flash High policy is a separate completed engineering line and is not to be reimplemented here.

This task must not redo:

- model resolver;
- DeepSeek model policy;
- thinking/reasoning configuration;
- Flash High diagnostics.

Final branch convergence is a later system-integration task.

---

# 2. FINAL DEFINITION OF DONE

The ML subsystem is scientifically closed only when the following factual chain exists:

```
REAL OKX decision-time market data
    ->
immutable scan snapshot
    ->
1–24 expert evidence frozen at decision time
    ->
exact historical label-v2 at T0+horizon
    ->
immutable dataset-v2
    ->
#21 chronological walk-forward training
    ->
post-cost validation
    ->
TRUE forward shadow on snapshots created after model cutoff
    ->
deterministic #21 promotion
    ->
ACTIVE #21 artifact used by ExpertEvidenceEngine
    ->
#25 XGBoost meta dataset using decision-time 1–24 evidence + #21 output
    ->
chronological #25 training/validation
    ->
TRUE forward shadow
    ->
deterministic #25 promotion
    ->
ACTIVE #25 artifact used by ExpertEvidenceEngine
    ->
runtime evidence remains LEARNING_ONLY / EVIDENCE_ONLY
```

No Harness/manual promotion may be required after deployment.

---

# 3. PHASE A — LABEL-V2 EXACT FACTUAL OUTCOME ENGINE

## 3.1 Preserve label-v1 but exclude it

Do not delete historical `label-v1`.

It must remain as archival evidence of the previous implementation.

But:

```
label-v1 MUST NOT be used for final #21/#25 training,
validation,
shadow maturity,
promotion,
or final scientific acceptance.
```

The trainer/readiness gate must fail closed if only label-v1 is available.

## 3.2 Required label identity

Canonical identity:

```
snapshot_id
+ horizon
+ label_version
```

Final version:

```
label_version = label-v2
```

Labels are append-only/versioned. Never silently rewrite label-v1 into label-v2.

## 3.3 Required horizons

Required initial horizons:

- 1m
- 5m
- 15m
- 30m
- 1h
- 4h

12h / 24h may be added as additive horizons but must not delay initial #21/#25 closure unless explicitly selected by the final model contract.

## 3.4 Exact historical reconstruction

For each snapshot captured at `T0` and horizon `H`:

```
target_ts = T0 + H
```

The label engine must reconstruct factual OKX history for the exact interval.

No use of:

- “current ticker price” when the labeler wakes;
- future information beyond target_ts;
- a later arbitrary price as a substitute;
- current market state as fallback.

Persist at minimum:

- requested_target_ts;
- actual_target_ts;
- alignment_error_seconds;
- endpoint_policy;
- data_gap;
- factual source;
- path_start_ts;
- path_end_ts;
- future_high;
- future_low;
- realized volatility;
- long_gross_bps;
- short_gross_bps;
- long_net_bps;
- short_net_bps;
- all_in_cost_bps;
- cost_version;
- maturity status;
- usable_for_training.

## 3.5 Strict no-lookahead endpoint

Only information fully available at or before `target_ts` may enter the label.

A bar whose close/end occurs after `target_ts` must not contribute its final high/low/close.

If exact endpoint resolution is impossible:

- use latest fully factual endpoint at/before target if alignment policy permits; or
- mark the label inconclusive.

Never consume post-horizon information.

## 3.6 Historical pagination

The labeler must fetch enough historical data to reconstruct old snapshots.

No fixed “latest 300 bars” assumption may be used as final scientific behavior.

Required:

- bounded historical pagination;
- timestamp de-duplication;
- chronological sorting;
- closed candles only;
- retry policy;
- explicit data-gap handling;
- window-aware cache.

## 3.7 Maturity statuses

At minimum:

- IMMATURE
- MATURE_VALID
- INCONCLUSIVE_DATA_GAP
- INCONCLUSIVE_ALIGNMENT
- TRANSIENT_SOURCE_ERROR

Only `MATURE_VALID` labels may be used for training/shadow outcome scoring.

Transient source failure must remain retryable.

## 3.8 Post-cost economics

The target is probability of post-cost return, not raw price direction.

Cost calculation must be versioned and auditable.

Use available factual/decision-time economics, including where applicable:

- fee schedule;
- spread;
- estimated slippage;
- funding over the relevant period;
- any existing canonical all-in cost estimate.

A hardcoded 22 bps constant may not remain the final universal scientific label definition.

If a component is unavailable, record the missing/estimated status explicitly.

## 3.9 Label-v2 acceptance

Required tests:

- exact T+horizon price selection;
- horizon-specific path;
- post-horizon spike cannot change label;
- historical reconstruction beyond 300 bars;
- data gap becomes inconclusive;
- transient failure retries;
- no current-price fallback;
- label-v1 excluded from final training;
- duplicate prevention;
- restart idempotency.

---

# 4. PHASE B — FREEZE DECISION-TIME 1–24 EXPERT EVIDENCE

## 4.1 Goal

Every ML snapshot used by #25 must contain the factual expert evidence actually available at the snapshot time.

The snapshot collector already supports `model_evidence`; the canonical scanner must actually supply it.

## 4.2 Required frozen evidence

For each applicable model #01–#24 persist at least:

- model_id;
- model_version;
- family;
- available;
- direction;
- direction_score;
- confidence;
- data_quality;
- freshness;
- core metrics used by the model;
- factual source refs where available.

Also freeze:

- market regime;
- costs/economics;
- candidate/control status;
- scanner score/rank;
- symbol;
- timestamp;
- feature_version;
- evidence version.

## 4.3 Same decision-time contract

Candidate and control rows must use the same feature/evidence schema.

No #25 label/result may be included in its own input.

No later Growth knowledge or future outcome may be injected into the frozen snapshot.

## 4.4 Evidence completeness

A #25 training row is eligible only if the declared required decision-time evidence is present.

Missing evidence must be represented explicitly, not filled with hindsight.

Acceptance must prove non-zero factual #25-eligible snapshots from the real collector.

---

# 5. PHASE C — MODEL #21 ORDER FLOW ML

## 5.1 Target

#21 estimates the probability that the selected future post-cost return exceeds the configured minimum edge.

It uses factual decision-time order-flow/microstructure features.

## 5.2 Dataset

Training dataset requirements:

- label-v2 only;
- MATURE_VALID only;
- usable_for_training=true;
- immutable dataset_version;
- feature_version recorded;
- label_version recorded;
- code SHA recorded;
- chronological time range recorded.

No random-shuffle cross-validation.

## 5.3 Features

Use factual order-flow features available at decision time, including where available:

- CVD;
- taker buy/sell flow;
- L1/L5 imbalance;
- microprice;
- spread;
- trade count;
- trade notional/activity;
- price velocity;
- relative volume;
- OI/funding context where scientifically justified.

Every feature must have an availability-time contract.

## 5.4 Training

Algorithm may remain a simple calibrated/logistic model if it passes the stated scientific contract; #21 is not required to be XGBoost.

Requirements:

- chronological walk-forward;
- >=2 valid folds;
- no train/validation overlap;
- preprocessing fitted on train only within each fold;
- leakage tests;
- versioned hyperparameters;
- deterministic seed where applicable.

## 5.5 Metrics

At minimum:

- AUC;
- precision;
- recall;
- F1;
- calibration/Brier where practical;
- OOS sample count;
- post-cost mean edge for accepted probability band;
- per-fold metrics;
- validation windows.

AUC alone is not enough.

## 5.6 Promotion gate

Promotion policy must be deterministic, versioned and auditable.

No manual “looks good” promotion.

---

# 6. PHASE D — TRUE FORWARD SHADOW

## 6.1 Definition

A prediction counts as forward shadow only if:

```
snapshot.captured_at > model.training_cutoff_ts
AND
prediction.created_at <= snapshot decision-time processing boundary
AND
future label was UNKNOWN when prediction was written
```

Historical replay of known samples does not count.

## 6.2 Prediction record

Persist:

- prediction_id;
- model_id;
- model_version;
- artifact_hash;
- snapshot_id;
- symbol;
- snapshot_ts;
- prediction_created_at;
- probability;
- predicted direction/class;
- expected edge;
- confidence;
- feature_version;
- label_version expected;
- training_cutoff_ts;
- authority=LEARNING_ONLY;
- is_order=false.

## 6.3 Outcome attachment

After natural label-v2 maturity, attach:

- outcome label;
- net_bps;
- outcome_ts;
- maturity quality.

The prediction row must exist before the outcome becomes known.

## 6.4 Forward gate

Promotion may require a configurable minimum number of valid forward samples.

Initial reference threshold may remain 30, but it must be configurable and versioned.

Promotion cannot use historical replay rows to satisfy forward sample minimum.

## 6.5 Restart safety

Forward shadow must survive restart and continue attaching outcomes without duplicating predictions.

---

# 7. PHASE E — MODEL #25 XGBOOST META FORECAST

## 7.1 Target

#25 is an actual XGBoost meta model.

It estimates:

```
P(NetReturn_horizon > MinimumEdge)
```

It is NOT a hand-weighted proxy and NOT the current project logistic fitter.

## 7.2 Dependency

Use a pinned, supported XGBoost dependency.

If XGBoost is unavailable in the current environment:

- add the dependency in the canonical project dependency mechanism;
- verify installation in the isolated implementation/test environment;
- do not silently substitute logistic regression.

## 7.3 Eligibility

#25 training begins only after #21 has a scientifically valid artifact under the final policy.

The exact gate must be explicit; final promotion of #25 requires an ACTIVE/promoted #21 artifact.

## 7.4 Meta features

Use only decision-time information:

- frozen #01–#24 outputs;
- family consensus;
- raw long/short/neutral counts;
- disagreement/opposition;
- effective independent evidence;
- #21 probability/output from the applicable artifact;
- market regime;
- execution-cost context;
- liquidity/data-quality context;
- other versioned decision-time meta features.

No future outcome, later review or later memory may leak into training features.

## 7.5 Training and validation

Required:

- label-v2;
- chronological walk-forward;
- train-only preprocessing;
- deterministic seed;
- versioned XGBoost hyperparameters;
- post-cost validation;
- immutable artifact;
- dataset hash/version;
- code SHA;
- feature schema hash.

## 7.6 True forward shadow

#25 must complete its own true forward-shadow phase after artifact creation.

The same no-replay rule applies.

---

# 8. PHASE F — ACTIVE ARTIFACT CUTOVER INTO EXPERT EVIDENCE

## 8.1 Registry is the model authority for artifacts

The registry determines which #21/#25 artifact is ACTIVE.

Artifact activation must be deterministic and recorded.

## 8.2 Runtime expert evidence

When an ACTIVE artifact exists:

#21 and #25 evidence in the live ExpertEvidenceEngine must be generated from that artifact.

Required runtime metadata:

- artifact_status = ACTIVE_TRAINED_ARTIFACT;
- model_id;
- model_version;
- artifact_hash;
- dataset_version;
- feature_version;
- label_version;
- training_cutoff_ts;
- probability/output;
- data quality.

## 8.3 Proxy semantics

Current provisional proxies may remain only as explicit degraded compatibility fallback.

They must report:

```
artifact_status = PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED
quality = DEGRADED
```

and must never masquerade as promoted ML.

Final runtime acceptance with an ACTIVE artifact must prove the active artifact path is used rather than the proxy.

## 8.4 Hot/restart loading

Artifact loading must be safe across:

- process restart;
- model promotion;
- rollback;
- missing/corrupt artifact.

If the active artifact is corrupt/missing:

- degrade model evidence;
- do not place orders;
- do not silently use an unverified different artifact.

## 8.5 Evidence-only invariant

Even ACTIVE #21/#25 remain evidence only.

No model artifact may gain execution authority.

---

# 9. PHASE G — AUTONOMOUS LIFECYCLE / STATE MACHINE

Required state semantics must distinguish at least:

- WAITING_FOR_DATA
- DATA_ACCUMULATING
- DATA_READY
- TRAINING_MODEL_21
- VALIDATING_MODEL_21
- SHADOW_MODEL_21
- MODEL_21_PROMOTED
- MODEL_21_ACTIVE
- TRAINING_MODEL_25
- VALIDATING_MODEL_25
- SHADOW_MODEL_25
- MODEL_25_PROMOTED
- MODEL_25_ACTIVE
- ML_CLOSURE_PASS
- VALIDATION_FAILED
- DEGRADED
- ROLLED_BACK

State must reflect reality, not merely the existence of code.

## 9.1 Trainer fail-closed rule

The autonomous trainer must not train/promote final models on label-v1.

Until sufficient label-v2 data exists:

```
state = WAITING_FOR_LABEL_V2_DATA / DATA_ACCUMULATING
```

or equivalent explicit reason.

## 9.2 Retraining

Retraining triggers must be versioned and bounded.

Examples:

- minimum new sample count;
- elapsed time;
- drift;
- degraded forward performance.

No rapid retrain loop.

## 9.3 Rollback

If active artifact performance degrades beyond deterministic policy:

- retain prior artifact;
- transition current artifact appropriately;
- rollback only through registry policy;
- record reason.

No deletion of historical artifacts.

---

# 10. PHASE H — AUTONOMOUS RUNTIME AND STORAGE

Prefer evolving existing services:

- `com.lowrisk.mlcollector`
- `com.lowrisk.mltrainer`

Add another daemon only if a proven responsibility cannot safely fit existing services.

Requirements:

- user-level launchd;
- no sudo;
- no `/tmp` canonical runtime state;
- durable storage;
- absolute paths;
- graceful SIGTERM/SIGINT;
- heartbeat;
- restart-safe cursors;
- bounded work per cycle;
- atomic state writes.

Canonical runtime data remains under the durable Low-Risk ML runtime directory.

Never delete current factual dataset during migration.

Back up before schema migration/cutover.

---

# 11. PHASE I — OBSERVABILITY

Provide a truthful ML status surface, file and/or API.

At minimum report:

## Collector
- pid;
- runtime_sha;
- cycles;
- snapshots;
- candidates;
- controls;
- errors;
- latest snapshot timestamp.

## Labels
- label-v1 count;
- label-v2 count;
- valid/inconclusive/transient by horizon;
- label-v2 maturity lag.

## Readiness
- ready;
- reasons;
- eligible label-v2 samples;
- symbol count;
- time coverage;
- feature completeness.

## #21
- state;
- model_version;
- artifact_hash;
- dataset_version;
- training cutoff;
- validation metrics;
- forward shadow count;
- matured forward count;
- promotion result;
- runtime artifact status.

## #25
- state;
- XGBoost version/hyperparameters;
- model_version;
- artifact_hash;
- decision-time evidence row count;
- validation metrics;
- forward shadow count;
- promotion result;
- runtime artifact status.

## Authority
- LEARNING_ONLY;
- is_order=false;
- Core LLM authority unchanged;
- Risk authority unchanged;
- Execution authority unchanged.

---

# 12. DATASET / VERSION CONTRACT

Every final training artifact must be reconstructable from:

- code SHA;
- dataset_version;
- dataset hash;
- label_version=label-v2;
- feature_version;
- feature schema hash;
- training window;
- validation windows;
- hyperparameters;
- random seed;
- artifact hash.

Dataset freeze must be immutable.

A later source DB change must not mutate an existing frozen dataset version.

---

# 13. SCIENTIFIC ANTI-LEAKAGE RULES

Forbidden leakage includes:

- using a price observed after T0+horizon;
- using future candle high/low that extends past target time;
- using later Growth reviews/memory in decision-time ML features;
- using outcome labels when writing forward predictions;
- fitting preprocessing on validation/future rows;
- random shuffle CV;
- using later model version output in an earlier snapshot;
- backfilling model_evidence from hindsight and presenting it as decision-time evidence.

Any unavoidable reconstruction must be marked derived/historical and excluded from decision-time acceptance if provenance cannot prove availability.

---

# 14. CURRENT DATA PRESERVATION

The existing factual ML DB and runtime artifacts must be preserved.

Requirements:

- no DB reset;
- no deletion of label-v1;
- no destruction of raw snapshots;
- no synthetic replacement;
- schema migration must be backward-compatible;
- create backup before first runtime migration;
- prove row counts before/after.

Existing raw snapshots remain valuable even when old label-v1 is scientifically invalid for final training.

Where decision-time #1–24 evidence was not originally frozen, do not fabricate it retroactively.

Those rows may remain eligible for #21 if their required factual features are truly decision-time facts, but are not eligible for #25 meta training unless the evidence provenance is valid.

---

# 15. PARALLEL WORK / BRANCH ISOLATION

Implementation must use an isolated ML branch/worktree.

Suggested implementation branch:

```
codex/low-risk-ml-final-scientific-closure
```

Base it from the branch containing this spec.

Do not merge into Growth while Growth is in progress.

Do not modify the Growth branch.

Final Low-Risk convergence happens after both ML and Growth independently reach their acceptance gates.

---

# 16. EXACT-SHA ACCEPTANCE DISCIPLINE

Every checkpoint:

1. implement;
2. focused tests;
3. ruff;
4. commit;
5. push;
6. verify remote SHA;
7. create clean detached worktree at the pushed SHA;
8. rerun checkpoint acceptance from the exact pushed SHA.

No receipt may be based only on the intended editor/worktree state.

Final claims must be supported by `git show FINAL_SHA` and detached exact-SHA tests.

---

# 17. REQUIRED CHECKPOINTS

Recommended sequence:

## M0 — forensic baseline + safety gate
- verify current service/source DB paths;
- verify branch SHA;
- map existing ML modules;
- prevent invalid label-v1 final promotion.

## M1 — label-v2
- exact historical maturer;
- cost versioning;
- validity statuses;
- readiness v2.

## M2 — decision-time expert evidence freeze
- wire #1–24 evidence into scan snapshots;
- verify factual non-zero eligible rows.

## M3 — #21 final trainer
- label-v2 only;
- chronological walk-forward;
- final metrics/artifact.

## M4 — #21 true forward shadow
- post-cutoff predictions only;
- natural maturity;
- deterministic promotion.

## M5 — #21 ACTIVE runtime cutover
- ExpertEvidenceEngine loads active artifact;
- proxy only degraded fallback.

## M6 — #25 XGBoost
- actual XGBoost;
- #1–24 + #21 meta features;
- chronological validation.

## M7 — #25 true forward shadow + promotion
- natural post-cutoff predictions;
- deterministic gate.

## M8 — #25 ACTIVE runtime cutover
- live evidence path uses promoted artifact.

## M9 — autonomous lifecycle / rollback / observability
- launchd;
- restart;
- state machine;
- status.

## M10 — final exact-SHA regression and runtime acceptance

---

# 18. REQUIRED TEST MATRIX

At minimum:

## Labels
- exact horizon;
- no lookahead;
- historical pagination;
- duplicate/idempotent;
- transient retry;
- data gap;
- cost version;
- label-v1 excluded.

## Snapshot evidence
- model evidence present;
- model IDs #01–#24;
- evidence frozen at decision time;
- candidate/control same schema;
- #25 not self-injected.

## #21
- chronological folds;
- no preprocessing leakage;
- label-v2 only;
- artifact reproducibility;
- post-cost metric gate.

## Forward shadow
- historical replay rejected;
- only post-cutoff snapshots count;
- prediction precedes outcome;
- restart-safe;
- duplicate-safe;
- maturity attachment.

## #25
- XGBoost object/artifact proven;
- no logistic substitution;
- #21 gate;
- #1–24 evidence required;
- chronological folds;
- post-cost validation;
- forward shadow.

## Runtime artifacts
- ACTIVE #21 loaded;
- ACTIVE #25 loaded;
- artifact hash/version match registry;
- proxy degraded if no active artifact;
- corrupt artifact fail-degrades;
- no order authority.

## Lifecycle
- restart;
- retrain;
- degraded state;
- rollback;
- prior artifact retained.

## Authority
- model cannot submit order;
- Core LLM remains sole intelligence originating new risk;
- Risk/Execution unchanged.

---

# 19. FINAL REGRESSION

Before final candidate acceptance run fresh:

```
pytest <focused ML tests> -q
pytest tests/low_risk -q
pytest tests -q
ruff check src scripts tests
```

Do not reuse previous test counts.

Repeat acceptance from clean detached FINAL_SHA.

---

# 20. DEPLOYMENT ACCEPTANCE

Only after engineering tests pass:

1. record existing ML service PIDs and DB row counts;
2. backup ML DB/runtime metadata;
3. deploy exact pushed candidate;
4. restart only ML services required for this cutover;
5. do not restart Growth;
6. verify launchd ownership;
7. verify heartbeats advance;
8. verify label-v2 accumulation;
9. verify trainer is label-v2 fail-closed;
10. verify forward predictions are written only after artifact cutoff.

No forced training or promotion.

---

# 21. FINAL SCIENTIFIC ACCEPTANCE

There are two distinct final statuses.

## 21.1 Engineering pass

May be:

```
ML_ENGINEERING = PASS
FINAL_STATUS = AUTONOMOUSLY_ACCUMULATING
```

when all code/services are correct but natural forward samples are still accumulating.

## 21.2 Scientific closure pass

Requires factual evidence of:

- non-zero valid label-v2 rows;
- #21 training on label-v2;
- chronological validation pass;
- #21 true forward shadow with policy-minimum natural samples;
- #21 deterministic promotion;
- ACTIVE #21 runtime artifact evidence;
- #25 factual meta rows with frozen 1–24 evidence;
- actual XGBoost #25 artifact;
- #25 chronological validation pass;
- #25 true forward shadow with policy-minimum natural samples;
- #25 deterministic promotion;
- ACTIVE #25 runtime artifact evidence;
- no model authority escalation.

Then:

```
ML_FINAL_SCIENTIFIC_CLOSURE = PASS
```

If natural data is insufficient, do not reduce thresholds.

---

# 22. FINAL RECEIPT CONTRACT

Return at minimum:

```
STARTING_SHA
SPEC_SHA
FINAL_SHA
REMOTE_SHA_MATCH
WORKTREE_CLEAN
DETACHED_EXACT_SHA_ACCEPTANCE

ML_DB
ML_DB_BACKUP
MIGRATION_HEAD

LABEL_V1_ROWS
LABEL_V2_ROWS
LABEL_V2_VALID_ROWS
LABEL_V2_INCONCLUSIVE_ROWS
LABEL_V2_BY_HORIZON
LABEL_V1_EXCLUDED_FROM_FINAL_TRAINING

EXACT_HORIZON_ALIGNMENT
STRICT_NO_LOOKAHEAD
HISTORICAL_RECONSTRUCTION
POST_COST_LABEL_VERSION

MODEL_EVIDENCE_FROZEN
MODEL_EVIDENCE_01_24_COUNT
MODEL_25_ELIGIBLE_SNAPSHOTS

MODEL_21_DATASET_VERSION
MODEL_21_LABEL_VERSION
MODEL_21_MODEL_VERSION
MODEL_21_ARTIFACT_HASH
MODEL_21_WALK_FORWARD
MODEL_21_POST_COST_VALIDATION
MODEL_21_FORWARD_SHADOW_COUNT
MODEL_21_MATURE_FORWARD_COUNT
MODEL_21_PROMOTION
MODEL_21_REGISTRY_STATE
MODEL_21_RUNTIME_ARTIFACT_STATUS

MODEL_25_ALGORITHM
MODEL_25_XGBOOST_VERSION
MODEL_25_DATASET_VERSION
MODEL_25_LABEL_VERSION
MODEL_25_MODEL_VERSION
MODEL_25_ARTIFACT_HASH
MODEL_25_WALK_FORWARD
MODEL_25_POST_COST_VALIDATION
MODEL_25_FORWARD_SHADOW_COUNT
MODEL_25_MATURE_FORWARD_COUNT
MODEL_25_PROMOTION
MODEL_25_REGISTRY_STATE
MODEL_25_RUNTIME_ARTIFACT_STATUS

TRUE_FORWARD_SHADOW_21
TRUE_FORWARD_SHADOW_25
HISTORICAL_REPLAY_COUNTED_AS_FORWARD = NO

ACTIVE_ARTIFACT_CUTOVER_21
ACTIVE_ARTIFACT_CUTOVER_25
PROXY_USED_WHEN_ACTIVE_ARTIFACT_EXISTS = NO

AUTONOMOUS_TRAINER
AUTONOMOUS_PROMOTION
AUTONOMOUS_ROLLBACK
HARNESS_REQUIRED_FOR_ML

MODEL_21_ORDER_AUTHORITY = NO
MODEL_25_ORDER_AUTHORITY = NO
CORE_LLM_AUTHORITY_CHANGED = NO
RISK_AUTHORITY_CHANGED = NO
EXECUTION_AUTHORITY_CHANGED = NO
GROWTH_RUNTIME_CHANGED = NO

ML_COLLECTOR_SERVICE
ML_TRAINER_SERVICE
ML_COLLECTOR_PID
ML_TRAINER_PID
HEARTBEAT_ADVANCING

FOCUSED_TESTS
LOW_RISK_TESTS
FULL_TEST_SUITE
RUFF

P0_BLOCKERS
P1_ISSUES

ML_ENGINEERING =
PASS | PARTIAL | BLOCKED

ML_FINAL_SCIENTIFIC_CLOSURE =
PASS | AUTONOMOUSLY_ACCUMULATING | PARTIAL | BLOCKED
```

---

# 23. PROHIBITED SHORTCUTS

Do not:

- shorten readiness merely to finish the task;
- count label-v1 toward final model training;
- count historical replay as forward shadow;
- retroactively fabricate #1–24 evidence for #25;
- use logistic regression while calling it XGBoost;
- promote without deterministic gates;
- force a model to ACTIVE;
- rewrite proxy output as trained output;
- reset/delete current ML data;
- disturb Growth;
- grant #21/#25 order authority;
- enable live trading.

---

# 24. FINAL GOAL

The final Low-Risk ML subsystem is not merely “a trainer that can run.”

It must be a factual autonomous learning system whose entire lineage is auditable:

```
what facts existed
-> what features/evidence were available
-> what exact future outcome matured
-> what immutable dataset was trained
-> what model was validated
-> what prediction was made before the future was known
-> what factual future outcome followed
-> why promotion/rollback occurred
-> which exact ACTIVE artifact generated runtime evidence
```

All of this must remain subordinate to the Core LLM trading authority.

That is the definition of LOW-RISK ML FINAL SCIENTIFIC CLOSURE.
