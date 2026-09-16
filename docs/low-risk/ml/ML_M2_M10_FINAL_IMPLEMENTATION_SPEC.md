# LOW-RISK V2 — ML M2–M10 FINAL IMPLEMENTATION & SCIENTIFIC CLOSURE SPEC

Status: FROZEN TARGET CONTRACT
Repository: fyjk999-cyber/crypto-auto-trading-system
Spec branch: codex/low-risk-ml-m2-m10-closure-spec
Spec base / implementation baseline SHA: b49827635d33f683d21e0c8ed5484ac8d8692ae4
Parent scientific contract: docs/low-risk/ml/ML_FINAL_SCIENTIFIC_CLOSURE_SPEC.md
Scope: M2 through M10 only
Trading mode: PAPER ONLY
Authority: Model #21 and Model #25 remain LEARNING_ONLY / EVIDENCE_ONLY

---

# 0. PURPOSE

M0 and M1 are already complete at the frozen baseline.

M0:
- label-v1 excluded from final training/promotion;
- final readiness requires label-v2.

M1:
- exact factual label-v2 maturer;
- T0+horizon reconstruction;
- strict no-lookahead;
- historical pagination;
- versioned post-cost economics;
- only MATURE_VALID rows are trainable.

This document closes the remaining ML work:

M2:
freeze factual decision-time #01–#24 evidence.

M3:
final #21 immutable dataset + chronological training/validation.

M4:
true forward #21 shadow.

M5:
deterministic #21 promotion + ACTIVE runtime cutover.

M6:
literal XGBoost #25 training.

M7:
true forward #25 shadow.

M8:
deterministic #25 promotion + ACTIVE runtime cutover.

M9:
autonomous retrain/degrade/rollback/observability.

M10:
exact-SHA regression, deployment, autonomous accumulation, final scientific acceptance.

The final data/authority chain is:

REAL OKX decision-time facts
-> immutable scan snapshot
-> frozen #01–#24 decision-time ExpertEvidence
-> exact label-v2
-> immutable dataset
-> #21 chronological training
-> #21 true forward shadow
-> deterministic promotion
-> ACTIVE #21 artifact
-> #25 XGBoost meta dataset
-> #25 chronological training
-> #25 true forward shadow
-> deterministic promotion
-> ACTIVE #25 artifact
-> ExpertEvidenceEngine evidence
-> Core LLM context

At no point do #21 or #25 acquire order authority.

---

# 1. VERIFIED BASELINE GAPS AT b49827635d33

These are implementation gaps observed at the frozen baseline and are the reason for this contract.

## 1.1 M2 gap — #01–#24 evidence not frozen into real scanner snapshots

`src/crypto_trader/market_data/opportunity/snapshots.py` already accepts:

`decision_time_features(..., model_evidence=...)`

But:

`src/crypto_trader/market_data/opportunity/service.py::_collect_ml_snapshots()`

still calls:

`decision_time_features(facts)`

for both candidates and controls without actual model_evidence.

Therefore the capability exists at the schema/helper layer but the canonical scanner path does not yet persist factual #01–#24 decision-time evidence.

## 1.2 #21 orchestrator gap

At the baseline:

`src/crypto_trader/ml_orchestrator.py`

still contains legacy behavior including:
- `label_version="label-v1"`;
- historical `samples[-50:]` replay;
- replay rows written into shadow and used toward promotion.

This does NOT satisfy true forward shadow.

## 1.3 #25 algorithm gap

At the baseline:

`src/crypto_trader/ml_meta.py`

still calls:

`ml_trainer.fit_logistic(...)`

for Model #25.

There is no literal XGBoost implementation in the active meta trainer.

`pyproject.toml` also does not declare XGBoost.

Therefore Model #25 is not yet the specified XGBoost meta forecast.

## 1.4 ACTIVE runtime cutover gap

At the baseline:

`src/crypto_trader/factors/expert/models.py`

Model #21 still exposes:

`artifact_status = PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED`

and the expert layer does not expose a verified:

`ACTIVE_TRAINED_ARTIFACT`

cutover path for #21/#25.

Thus training/promotion would still not automatically replace the provisional runtime evidence implementation.

These four gaps MUST be eliminated by M2–M8.

---

# 2. NON-NEGOTIABLE AUTHORITY

Model #21 and Model #25 are:

- LEARNING_ONLY
- EVIDENCE_ONLY

They may NEVER:

- OPEN;
- ADD;
- HEDGE;
- REVERSE;
- REDUCE;
- CLOSE;
- place/cancel orders;
- choose leverage;
- choose capital allocation;
- alter Base Exit;
- bypass Core LLM;
- bypass Risk;
- bypass ExecutionAuthority.

Required invariants:

MODEL_21_ORDER_AUTHORITY = NO
MODEL_25_ORDER_AUTHORITY = NO
CORE_LLM_AUTHORITY_CHANGED = NO
RISK_AUTHORITY_CHANGED = NO
EXECUTION_AUTHORITY_CHANGED = NO
GROWTH_AUTHORITY_CHANGED = NO

If trained artifacts fail, the system degrades evidence quality. It does not gain execution authority.

---

# 3. M2 — FREEZE FACTUAL DECISION-TIME #01–#24 EVIDENCE

## 3.1 Canonical source

Use the existing ExpertEvidenceEngine / expert model path that produces the actual decision-time evidence consumed by Low-Risk.

Do not create a second implementation of the 24 experts only for ML.

The frozen evidence must be the same factual family used by the trading decision path at that time.

## 3.2 Scanner integration

The canonical scan flow must become equivalent to:

market facts
-> expert evidence #01–#24
-> candidate/control construction
-> decision_time_features(
       facts,
       model_evidence=factual_01_24,
       costs=decision_time_costs,
       growth_context=optional_decision_time_context
   )
-> ScanSnapshot persist

Candidate and control rows must use the same feature schema.

## 3.3 Required frozen fields per model

Persist enough information to reproduce the decision-time evidence, including where applicable:

- model_id
- model_version
- family
- available
- direction
- direction_score / score
- confidence
- data_quality
- freshness
- theory or bounded reason
- support evidence
- counter evidence
- neutral evidence
- key factual metrics
- regime compatibility
- strategy compatibility
- observed_at
- source refs if available

Do not require unsupported fields to be fabricated.

Unknown/missing stays explicit.

## 3.4 Models included

Freeze #01 through #24.

Do NOT include #25 in the #25 training input snapshot.

No self-feature leakage.

#21 may be:
- provisional/degraded before ACTIVE;
- ACTIVE-trained after promotion.

The exact artifact status/version used at snapshot time must be frozen.

## 3.5 Same-time semantics

Evidence must be generated from information available at the snapshot decision time.

Forbidden:
- later recomputation presented as original evidence;
- later artifact version substituted into an old snapshot;
- future Growth knowledge;
- future News;
- future labels.

## 3.6 Candidate/control parity

Candidate and control snapshots must:
- use the same schema;
- run the same #01–#24 evidence production contract where data is available;
- differ only in selection/admission context, not data semantics.

This is required to reduce selection-bias distortion.

## 3.7 M2 acceptance

Required:

MODEL_EVIDENCE_FROZEN = YES
MODEL_EVIDENCE_01_24_COUNT > 0
CANDIDATE_CONTROL_SCHEMA_MATCH = YES
MODEL_25_SELF_INPUT = NO
DECISION_TIME_ONLY = YES

---

# 4. M3 — MODEL #21 FINAL DATASET

## 4.1 Eligibility

Use only rows with:

label_version = label-v2
maturation_status = MATURE_VALID
usable_for_training = true

Label-v1 is archival only.

## 4.2 Dataset immutability

Freeze an immutable dataset artifact with:

- dataset_version
- dataset_hash
- row count
- symbol count
- time coverage
- regime coverage where available
- feature_version
- feature_schema_hash
- label_version
- code_sha
- horizon
- direction
- training cutoff
- cost policy/version
- exclusion counts/reasons

The same dataset version must never silently change contents.

## 4.3 #21 feature family

Use factual decision-time microstructure/order-flow fields where available:

- CVD
- taker buy volume
- taker sell volume
- taker imbalance
- trade count
- trade notional/activity
- L1 imbalance
- L5 imbalance
- microprice
- spread
- price velocity
- relative volume
- OI context
- funding context
- liquidity/data quality flags

Missing inputs remain explicit.

Do not future-impute.

## 4.4 Label target

The target must be defined from label-v2 post-cost economics.

The final binary/probability target must be versioned.

No target may use future information outside the requested horizon.

---

# 5. M3 — MODEL #21 TRAINING / VALIDATION

## 5.1 Chronological only

No random split.

Use chronological walk-forward.

At least two valid folds before promotion eligibility.

For each fold:

max(train timestamp) < min(validation timestamp)

## 5.2 Preprocessing leakage prevention

Any preprocessing/statistics must be fitted on the TRAIN fold only.

Forbidden:
- global scaling before split;
- future-derived normalization;
- label-derived feature preprocessing.

## 5.3 Metrics

Persist at minimum:

- AUC
- precision
- recall
- F1
- OOS count
- mean post-cost edge
- fold metrics
- train/validation windows
- class balance

Calibration/Brier may be added.

## 5.4 Algorithm

#21 does not have to be XGBoost.

A deterministic/calibrated logistic implementation is acceptable if:
- chronological;
- reproducible;
- post-cost validated;
- artifact versioned;
- true-forward promotion later.

---

# 6. #21 ARTIFACT CONTRACT

Persist immutable artifact metadata:

- model_id = 21_ORDER_FLOW_ML
- model_version
- artifact_hash
- artifact_path
- dataset_version
- dataset_hash
- feature_version
- feature_schema_hash
- label_version = label-v2
- code_sha
- training_cutoff_ts
- hyperparameters
- preprocessing
- metrics
- validation windows
- created_at
- algorithm

Registry truth must match artifact truth.

No registry ACTIVE state if artifact integrity fails.

---

# 7. M4 — TRUE FORWARD SHADOW #21

Historical replay is diagnostic only.

It is NOT forward shadow.

## 7.1 Eligibility

A true forward row requires:

snapshot.captured_at > artifact.training_cutoff_ts

AND

prediction_created_at < label outcome availability/maturity time

AND

the prediction is persisted before future outcome is known.

## 7.2 Required prediction fields

Persist:

- prediction_id
- model_id
- model_version
- artifact_hash
- snapshot_id
- symbol
- snapshot_ts
- prediction_created_at
- training_cutoff_ts
- probability
- direction/class
- expected_edge
- confidence
- feature_version
- label_version
- state = PENDING_OUTCOME / MATURED
- authority = LEARNING_ONLY
- is_order = false

## 7.3 Natural outcome attachment

After label-v2 naturally matures:

attach:
- outcome label
- net_bps
- outcome_ts
- maturity quality
- horizon

Never backdate prediction_created_at.

## 7.4 Legacy replay

The existing behavior equivalent to:

`for sample in samples[-50:]`

may remain only as:

HISTORICAL_REPLAY_DIAGNOSTIC

It must not count toward:

- forward sample minimum;
- promotion;
- ACTIVE state.

Required:

HISTORICAL_REPLAY_COUNTED_AS_FORWARD = NO

---

# 8. M5 — #21 PROMOTION

Promotion gate is deterministic.

Inputs must include:

- artifact integrity;
- chronological validation pass;
- post-cost validation pass;
- minimum TRUE forward sample count;
- forward performance threshold;
- no authority violation;
- schema compatibility.

Outputs:

PROMOTE
REJECT
CONTINUE_SHADOW

Do not force PROMOTE.

Do not lower minimums merely to finish the task.

If natural data is insufficient:

MODEL_21_PROMOTION = CONTINUE_SHADOW

and autonomous services keep accumulating.

---

# 9. M5 — ACTIVE #21 RUNTIME CUTOVER

This is mandatory engineering, even if natural promotion has not occurred yet.

Implement a canonical artifact resolver/loader.

Runtime path:

registry
-> find ACTIVE #21
-> verify artifact hash
-> verify model id/version
-> verify feature schema
-> verify label version
-> load artifact
-> evaluate factual current features
-> emit ModelEvidence

If a valid ACTIVE artifact exists:

artifact_status = ACTIVE_TRAINED_ARTIFACT

and runtime evidence includes:

- model_id
- model_version
- artifact_hash
- dataset_version
- feature_version
- label_version
- training_cutoff_ts
- probability/output
- artifact_status

The provisional #21 proxy may remain ONLY when no valid ACTIVE artifact exists.

Required:

ACTIVE_ARTIFACT_CUTOVER_21 = PASS
PROXY_USED_WHEN_ACTIVE_21_EXISTS = NO

## 9.1 Corrupt/missing artifact

If registry says ACTIVE but artifact is:
- missing;
- corrupt;
- hash mismatch;
- schema mismatch;

then:
- degrade evidence;
- report artifact failure;
- do not place any order;
- do not silently select an unverified model.

---

# 10. M6 — MODEL #25 MUST BE LITERAL XGBOOST

Model #25 is the XGBoost Meta Forecast.

The final implementation must import and use the real XGBoost library.

Forbidden:
- logistic model renamed XGBoost;
- weighted rule proxy promoted as XGBoost;
- custom linear classifier used under XGBoost metadata.

Add/pin a supported XGBoost dependency through the canonical Python dependency mechanism.

Record:
- xgboost version
- hyperparameters
- deterministic seed
- feature schema
- artifact hash

If XGBoost cannot be safely installed in the accepted runtime environment:

P0_BLOCKER

Do not silently substitute.

---

# 11. M6 — #25 TRAINING INPUTS

#25 may train only when its dependencies are scientifically valid.

Required inputs:

- factual frozen #01–#24 decision-time evidence;
- applicable #21 output known at decision time;
- market regime;
- cost context;
- liquidity/data-quality context;
- label-v2 target.

No later recomputation.

No hindsight Growth review.

No later News.

No #25 self-feature.

## 11.1 #21 dependency

The training contract must define which #21 state is acceptable.

At minimum:
- version/artifact must be explicit;
- training rows must state the #21 artifact status used;
- a later #21 model may not be substituted into earlier snapshots.

---

# 12. #25 META FEATURES

Version and freeze the feature schema.

Include where factual:

- #01–#24 direction/score/confidence/availability
- family consensus summaries
- raw LONG/SHORT/NEUTRAL counts
- disagreement/opposition
- effective independent evidence
- #21 probability/output
- market regime
- cost context
- liquidity context
- data quality
- scanner priority/rank where appropriate
- relevant decision-time factual context

Do not collapse all experts into one opaque unversioned score.

---

# 13. M6 — #25 CHRONOLOGICAL XGBOOST TRAINING

Use:
- chronological walk-forward;
- deterministic seed;
- versioned hyperparameters;
- label-v2 only;
- immutable dataset;
- post-cost validation.

No random split.

Persist metrics:

- AUC
- precision
- recall
- F1
- OOS count
- mean post-cost edge
- fold metrics
- train/validation windows
- class balance

---

# 14. #25 ARTIFACT CONTRACT

Persist:

- model_id = 25_XGBOOST_META_FORECAST
- model_version
- artifact_hash
- artifact_path
- dataset_version
- dataset_hash
- feature_schema_hash
- label_version
- xgboost_version
- training_cutoff_ts
- seed
- hyperparameters
- validation windows
- metrics
- code_sha

Registry must never claim ACTIVE unless artifact passes integrity checks.

---

# 15. M7 — TRUE FORWARD SHADOW #25

Same scientific rule as #21.

Only:

snapshot time > #25 training cutoff

and prediction persisted before outcome maturity

counts.

Historical replay does NOT count.

Persist exact prediction lineage.

Natural label-v2 attaches later.

Outputs:

PROMOTE
REJECT
CONTINUE_SHADOW

Do not force.

Required:

TRUE_FORWARD_SHADOW_25 = YES
HISTORICAL_REPLAY_COUNTED_AS_FORWARD_25 = NO

---

# 16. M8 — ACTIVE #25 RUNTIME CUTOVER

Implement canonical ACTIVE artifact loading for #25.

Runtime must evaluate the promoted XGBoost artifact when valid ACTIVE state exists.

Evidence metadata:

artifact_status = ACTIVE_TRAINED_ARTIFACT
model_id
model_version
artifact_hash
dataset_version
feature_version/schema
label_version
xgboost_version
training_cutoff_ts
probability
confidence

The existing provisional #25 proxy may remain only as degraded fallback when no valid ACTIVE artifact exists.

Required:

ACTIVE_ARTIFACT_CUTOVER_25 = PASS
PROXY_USED_WHEN_ACTIVE_25_EXISTS = NO

No order authority.

---

# 17. ARTIFACT RESOLVER / CACHE

The final runtime should not repeatedly parse disk artifacts unnecessarily.

Implement a bounded artifact cache keyed by:

model_id
model_version
artifact_hash

Cache invalidation:
- registry ACTIVE version changes;
- artifact hash mismatch;
- explicit reload;
- process restart.

Cache is performance only.

Registry + artifact hash remain source of truth.

---

# 18. M9 — AUTONOMOUS LIFECYCLE

Final ML lifecycle states must reflect reality.

At minimum:

WAITING_FOR_DATA
DATA_ACCUMULATING
DATA_READY

TRAINING_MODEL_21
VALIDATING_MODEL_21
SHADOW_MODEL_21
MODEL_21_PROMOTED
MODEL_21_ACTIVE

TRAINING_MODEL_25
VALIDATING_MODEL_25
SHADOW_MODEL_25
MODEL_25_PROMOTED
MODEL_25_ACTIVE

ML_CLOSURE_PASS

VALIDATION_FAILED
DEGRADED
ROLLED_BACK

Do not claim ACTIVE because a file merely exists.

---

# 19. AUTONOMOUS RETRAINING

Implement bounded deterministic retraining triggers such as:

- minimum number of new valid label-v2 rows;
- elapsed scheduled interval;
- feature/data drift;
- forward-performance degradation.

Prevent retraining loops.

Persist why retraining started.

LLM is not required to train ML.

Harness must not be required after deployment.

---

# 20. ROLLBACK

If a candidate model fails:

retain existing ACTIVE.

If ACTIVE artifact materially degrades under versioned policy:

rollback to prior accepted ACTIVE artifact where scientifically valid.

Persist:

- model_id
- old version
- candidate/new version
- result
- reason
- metrics
- timestamp

Never delete historical artifacts.

---

# 21. DATA / STORAGE SAFETY

Before schema or runtime DB changes:

backup the ML DB.

Record:
- ML_DB
- ML_DB_BACKUP
- row counts before
- row counts after

Never:
- reset the DB;
- delete label-v1;
- rewrite raw scan snapshots;
- delete historical artifacts;
- fabricate training rows;
- fabricate forward predictions.

Migrations must be additive/backward-compatible.

---

# 22. SERVICE SAFETY

Prefer existing:

com.lowrisk.mlcollector
com.lowrisk.mltrainer

Do not create extra daemons unless architecture proves necessary.

Requirements:

- user-level launchd;
- no sudo;
- no /tmp canonical state;
- durable absolute paths;
- graceful shutdown;
- heartbeat;
- restart-safe cursor/state;
- bounded loops.

Do NOT restart Growth.

Do NOT alter News.

Do NOT alter Core Runtime/Hedge/Flash branches during this mission.

---

# 23. OBSERVABILITY

Expose truthful ML status.

At minimum:

## dataset / labels
- label-v1 count
- label-v2 count
- MATURE_VALID count
- inconclusive counts
- by horizon
- training-eligible count
- time coverage
- symbol coverage
- regime coverage

## #21
- lifecycle state
- model version
- artifact hash
- artifact status
- dataset version
- training cutoff
- walk-forward metrics
- forward prediction count
- matured forward count
- promotion result
- runtime cutover status

## #25
- lifecycle state
- algorithm = XGBoost
- xgboost version
- model version
- artifact hash
- dataset version
- training cutoff
- walk-forward metrics
- forward prediction count
- matured forward count
- promotion result
- runtime cutover status

## authority
- LEARNING_ONLY
- is_order = false

---

# 24. REQUIRED TEST MATRIX

## M2 evidence
- candidate freezes #01–#24;
- control freezes #01–#24 with same schema;
- no #25 self-feature;
- later model recomputation does not rewrite old snapshot;
- model version/artifact status frozen;
- unavailable evidence remains explicit.

## #21 dataset/training
- label-v2 only;
- only MATURE_VALID trainable;
- immutable dataset hash;
- chronological folds;
- preprocessing train-fold only;
- no random split;
- artifact reproducibility;
- post-cost validation.

## #21 shadow
- post-cutoff only;
- prediction before outcome;
- historical replay rejected from forward count;
- restart-safe;
- duplicate-safe;
- natural outcome attachment;
- no forced promotion.

## #21 cutover
- ACTIVE artifact loaded;
- hash/version/schema checked;
- proxy not used when ACTIVE exists;
- corrupt ACTIVE degrades safely;
- no order authority.

## #25
- actual xgboost import/use;
- xgboost version persisted;
- no logistic substitution;
- #01–#24 decision-time evidence required;
- #21 dependency versioned;
- chronological folds;
- label-v2 only;
- post-cost validation;
- no #25 self-feature.

## #25 shadow
- post-cutoff only;
- prediction before outcome;
- historical replay excluded;
- restart-safe;
- natural outcome attachment.

## #25 cutover
- ACTIVE XGBoost artifact used;
- proxy not used when ACTIVE exists;
- corrupt ACTIVE degrades;
- no order authority.

## lifecycle
- retrain trigger bounded;
- candidate failure keeps current ACTIVE;
- rollback auditable;
- service restart preserves state.

## authority
- #21 cannot create order;
- #25 cannot create order;
- Growth authority unchanged;
- Core LLM sole new-risk authority.

---

# 25. M10 — FULL REGRESSION

Run fresh from the implementation candidate:

focused ML tests
pytest tests/low_risk -q
pytest tests -q
ruff check src scripts tests

Do not reuse historical counts.

After push:

create clean detached exact-SHA worktree

repeat:
- focused ML acceptance;
- low-risk suite;
- full suite;
- Ruff.

Final receipt must be tied to the exact remote SHA.

---

# 26. M10 — DEPLOYMENT

Only after engineering gates pass.

Before restart record:

- ML collector PID
- ML trainer PID
- runtime SHA
- DB path
- row counts
- Growth PID

Backup ML DB.

Deploy exact pushed ML SHA to ML runtime clone.

Restart only required ML services.

Do NOT restart Growth.

Verify:
- launchd owns services;
- runtime SHA exact;
- heartbeats advance;
- DB preserved;
- label-v2 accumulates;
- #01–#24 evidence accumulates;
- trainer consumes label-v2 only;
- true-forward predictions accumulate;
- no label-v1 promotion path.

---

# 27. SCIENTIFIC STATUS SEMANTICS

Engineering completion and natural scientific maturity are separate.

## ML_ENGINEERING = PASS

Allowed when:
- M2–M10 code is implemented;
- tests pass;
- autonomous services deployed safely;
- true-forward machinery is running;
- promotion/cutover/rollback logic is implemented;
- no authority violation exists.

## ML_FINAL_SCIENTIFIC_CLOSURE = AUTONOMOUSLY_ACCUMULATING

Expected when:
- engineering is complete;
- natural true-forward sample minimum has not yet matured for one or both models.

This is not an engineering failure.

Do not reduce thresholds to change this status.

## ML_FINAL_SCIENTIFIC_CLOSURE = PASS

Only when factual natural evidence proves:

### #21
- label-v2 training;
- chronological validation;
- post-cost validation;
- true forward minimum;
- promotion;
- ACTIVE registry artifact;
- runtime uses ACTIVE artifact.

### #25
- factual frozen #01–#24 evidence;
- literal XGBoost training;
- chronological validation;
- post-cost validation;
- true forward minimum;
- promotion;
- ACTIVE registry artifact;
- runtime uses ACTIVE artifact.

No fake samples.

---

# 28. EXACT-SHA CHECKPOINTS

For M2 through M10:

implement
-> focused tests
-> Ruff
-> commit
-> push
-> verify remote SHA
-> clean detached exact-SHA acceptance

Do not stop after ordinary checkpoints.

Only stop for genuine P0.

---

# 29. P0 BLOCKERS

Examples:

- final training still uses label-v1;
- future information leaks into features;
- historical replay counted as forward;
- #25 still logistic while called XGBoost;
- ACTIVE registry points to invalid/corrupt artifact without degradation;
- ACTIVE exists but runtime still silently uses provisional proxy;
- #21/#25 gains order authority;
- data migration risks destructive loss;
- XGBoost cannot be safely installed;
- fabricated predictions/outcomes used for acceptance;
- LIVE trading enabled.

Natural sample insufficiency is NOT P0.

---

# 30. P1 ISSUES

Examples when safely degraded:
- some models unavailable on some symbols;
- insufficient natural forward samples;
- sparse regime coverage;
- fallback cost estimate for some label-v2 rows;
- temporary OKX history outage;
- non-critical observability gap.

P1 must be documented with impact.

---

# 31. FINAL RECEIPT

Return:

STARTING_SHA
SPEC_SHA
FINAL_SHA
REMOTE_SHA_MATCH
WORKTREE_CLEAN
DETACHED_EXACT_SHA_ACCEPTANCE

M2_MODEL_EVIDENCE_FREEZE
M3_MODEL_21_TRAINING
M4_MODEL_21_TRUE_FORWARD
M5_MODEL_21_PROMOTION_CUTOVER
M6_MODEL_25_XGBOOST
M7_MODEL_25_TRUE_FORWARD
M8_MODEL_25_PROMOTION_CUTOVER
M9_AUTONOMOUS_LIFECYCLE
M10_ACCEPTANCE_DEPLOYMENT

ML_DB
ML_DB_BACKUP
MIGRATION_HEAD

LABEL_V1_ROWS
LABEL_V2_ROWS
LABEL_V2_VALID_ROWS
LABEL_V2_BY_HORIZON
LABEL_V1_EXCLUDED_FROM_FINAL_TRAINING

MODEL_EVIDENCE_FROZEN
MODEL_EVIDENCE_01_24_COUNT
CANDIDATE_CONTROL_SCHEMA_MATCH
MODEL_25_SELF_INPUT = NO

MODEL_21_DATASET_VERSION
MODEL_21_MODEL_VERSION
MODEL_21_ARTIFACT_HASH
MODEL_21_LABEL_VERSION
MODEL_21_TRAINING_CUTOFF
MODEL_21_WALK_FORWARD
MODEL_21_POST_COST_VALIDATION
MODEL_21_TRUE_FORWARD_COUNT
MODEL_21_MATURE_FORWARD_COUNT
MODEL_21_PROMOTION
MODEL_21_REGISTRY_STATE
MODEL_21_RUNTIME_ARTIFACT_STATUS
ACTIVE_ARTIFACT_CUTOVER_21
PROXY_USED_WHEN_ACTIVE_21_EXISTS = NO

MODEL_25_ALGORITHM = XGBoost
MODEL_25_XGBOOST_VERSION
MODEL_25_DATASET_VERSION
MODEL_25_MODEL_VERSION
MODEL_25_ARTIFACT_HASH
MODEL_25_LABEL_VERSION
MODEL_25_TRAINING_CUTOFF
MODEL_25_WALK_FORWARD
MODEL_25_POST_COST_VALIDATION
MODEL_25_TRUE_FORWARD_COUNT
MODEL_25_MATURE_FORWARD_COUNT
MODEL_25_PROMOTION
MODEL_25_REGISTRY_STATE
MODEL_25_RUNTIME_ARTIFACT_STATUS
ACTIVE_ARTIFACT_CUTOVER_25
PROXY_USED_WHEN_ACTIVE_25_EXISTS = NO

HISTORICAL_REPLAY_COUNTED_AS_FORWARD = NO

AUTONOMOUS_TRAINER
AUTONOMOUS_RETRAIN
AUTONOMOUS_PROMOTION
AUTONOMOUS_ROLLBACK
HARNESS_REQUIRED_FOR_ML = NO

MODEL_21_ORDER_AUTHORITY = NO
MODEL_25_ORDER_AUTHORITY = NO
CORE_LLM_AUTHORITY_CHANGED = NO
RISK_AUTHORITY_CHANGED = NO
EXECUTION_AUTHORITY_CHANGED = NO
GROWTH_RUNTIME_CHANGED = NO
NEWS_RUNTIME_CHANGED = NO

ML_COLLECTOR_SERVICE
ML_TRAINER_SERVICE
ML_COLLECTOR_PID
ML_TRAINER_PID
HEARTBEAT_ADVANCING

FOCUSED_ML_TESTS
LOW_RISK_TESTS
FULL_TEST_SUITE
RUFF

P0_BLOCKERS
P1_ISSUES

ML_ENGINEERING =
PASS | PARTIAL | BLOCKED

ML_FINAL_SCIENTIFIC_CLOSURE =
PASS | AUTONOMOUSLY_ACCUMULATING | PARTIAL | BLOCKED

---

# 32. DEFINITION OF DONE

M2–M10 engineering is DONE when:

1. the canonical scanner freezes factual #01–#24 decision-time evidence for candidates and controls;
2. label-v2 alone feeds final training;
3. #21 trains chronologically and writes immutable artifacts;
4. #21 true-forward predictions are written before natural outcomes mature;
5. #21 promotion is deterministic and ACTIVE cutover is real;
6. #25 is literal XGBoost;
7. #25 uses frozen #01–#24 + versioned #21 decision-time evidence;
8. #25 true-forward predictions are genuine;
9. #25 promotion and ACTIVE runtime cutover are real;
10. provisional proxies are used only when no valid ACTIVE artifact exists;
11. autonomous retrain/degrade/rollback works;
12. ML services survive restart with durable state;
13. exact-SHA tests/regression pass;
14. Growth/News/Core authority is unchanged;
15. LIVE trading remains disabled.

If true-forward natural minimum is still accumulating, engineering can still PASS and the scientific state remains AUTONOMOUSLY_ACCUMULATING.

No fabricated evidence may upgrade that status.
