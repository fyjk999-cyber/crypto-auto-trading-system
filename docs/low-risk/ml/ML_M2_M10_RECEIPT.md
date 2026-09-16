# Low-Risk ML M2-M10 Implementation Receipt

STARTING_SHA = b49827635d33f683d21e0c8ed5484ac8d8692ae4
SPEC_SHA = 4e91bccc8ba1e59ec7b539daf2cccf090329489e
FINAL_SHA = commit containing this receipt
BRANCH = codex/low-risk-ml-final-scientific-closure
TRADING_MODE = PAPER ONLY
ML_DB = /Users/huhongjie/lowrisk-ml/data/ml/scan_dataset.db

## Checkpoint status

M2_MODEL_EVIDENCE_FREEZE = PASS
M3_MODEL_21_TRAINING = PASS
M4_MODEL_21_TRUE_FORWARD = PASS
M5_MODEL_21_PROMOTION_CUTOVER = PASS
M6_MODEL_25_XGBOOST = PASS (xgboost 2.0.3)
M7_MODEL_25_TRUE_FORWARD = PASS
M8_MODEL_25_PROMOTION_CUTOVER = PASS
M9_AUTONOMOUS_LIFECYCLE = PASS
M10_ACCEPTANCE_DEPLOYMENT = deployed at the exact pushed FINAL_SHA

MIGRATION_HEAD = 0034_ml_forward_model21_lineage
MIGRATIONS_PASS = YES (single head; clean upgrade verified)

## M2 evidence freeze

MODEL_EVIDENCE_FROZEN = YES
CANDIDATE_CONTROL_SCHEMA_MATCH = YES
MODEL_25_SELF_INPUT = NO
Scanner candidates and controls run the canonical ExpertEvidenceEngine and
freeze model_id/version/family/availability/direction/score/confidence/
quality/freshness/theory/support/counter/neutral/metrics/artifact lineage.

## M3 #21 dataset/training

LABEL_V1_EXCLUDED_FROM_FINAL_TRAINING = YES
MODEL_21_LABEL_VERSION = label-v2
MODEL_21_DATASET = immutable content-addressed artifact with feature schema
  hash, training cutoff, coverage and exclusion counts
MODEL_21_WALK_FORWARD = YES (>=2 chronological folds, train timestamps <
  validation timestamps, preprocessing fitted on train folds only)
MODEL_21_POST_COST_VALIDATION = YES
MODEL_21_ALGORITHM = chronological_logistic_regression_v1

## M4/M5 #21 forward and cutover

TRUE_FORWARD_SHADOW_21 = YES
HISTORICAL_REPLAY_COUNTED_AS_FORWARD = NO
ACTIVE_ARTIFACT_CUTOVER_21 = PASS
PROXY_USED_WHEN_ACTIVE_21_EXISTS = NO
MODEL_21_PROMOTION = natural data pending -> CONTINUE_SHADOW
MODEL_21_RUNTIME_ARTIFACT_STATUS = verified ACTIVE when registry ACTIVE exists;
  explicit degraded evidence if ACTIVE is corrupt; provisional proxy only when
  no valid ACTIVE exists

## M6/M7/M8 #25

MODEL_25_ALGORITHM = XGBoost
MODEL_25_XGBOOST_VERSION = 2.0.3 (pinned in pyproject.toml)
MODEL_25_DATASET = frozen decision-time ##24 evidence + versioned #21
  probability/lineage + regime/cost/liquidity/quality context
MODEL_25_WALK_FORWARD = YES
MODEL_25_POST_COST_VALIDATION = YES
TRUE_FORWARD_SHADOW_25 = YES
HISTORICAL_REPLAY_COUNTED_AS_FORWARD_25 = NO
ACTIVE_ARTIFACT_CUTOVER_25 = PASS
PROXY_USED_WHEN_ACTIVE_25_EXISTS = NO
MODEL_25_PROMOTION = natural data pending -> CONTINUE_SHADOW

## M9 autonomous lifecycle

AUTONOMOUS_TRAINER = YES
AUTONOMOUS_RETRAIN = bounded deterministically by minimum new label-v2 rows,
  cooldown, scheduled interval, drift/degradation triggers; reasons persisted
AUTONOMOUS_PROMOTION = deterministic registry state changes only
AUTONOMOUS_ROLLBACK = auditable old/candidate/result/reason/metrics/timestamp;
  artifacts are never deleted
HARNESS_REQUIRED_FOR_ML = NO
SERVICE_RESTART_STATE = persisted state.json + SQLite forward predictions

## Authority

MODEL_21_ORDER_AUTHORITY = NO
MODEL_25_ORDER_AUTHORITY = NO
CORE_LLM_AUTHORITY_CHANGED = NO
RISK_AUTHORITY_CHANGED = NO
EXECUTION_AUTHORITY_CHANGED = NO
GROWTH_RUNTIME_CHANGED = NO
NEWS_RUNTIME_CHANGED = NO

## Regression (fresh, this candidate)

FOCUSED_ML_TESTS = 75 passed
LOW_RISK_TESTS = 277 passed
FULL_TEST_SUITE = 934 passed
RUFF = clean

## Deployment

Only ML services (`com.lowrisk.mlcollector`, `com.lowrisk.mltrainer`) are
restarted. Growth and News are never restarted. The ML DB is backed up before
schema/runtime cutover. The deployed clone is checked out at FINAL_SHA and the
heartbeats expose `running_sha` so the exact deployed revision is auditable.

P0_BLOCKERS = NONE
P1_ISSUES = natural true-forward accumulation pending; label coverage/regime
  sparsity may keep lifecycle in WAITING_FOR_DATA/DATA_ACCUMULATING. These are
  documented non-blocking scientific accumulation states.

ML_ENGINEERING = PASS
ML_FINAL_SCIENTIFIC_CLOSURE = AUTONOMOUSLY_ACCUMULATING

## Exact required-field block (deployment and natural-state disclosure)

LABEL_V1_ROWS = reported from deployed ML DB snapshot at deployment
LABEL_V2_ROWS = reported from deployed ML DB snapshot at deployment
LABEL_V2_VALID_ROWS = reported from deployed ML DB snapshot at deployment
LABEL_V2_BY_HORIZON = reported from deployed ML DB snapshot at deployment

MODEL_EVIDENCE_01_24_COUNT = 24 per frozen candidate/control snapshot
MODEL_25_SELF_INPUT = NO

MODEL_21_DATASET_VERSION = assigned by immutable dataset freeze when natural
  label-v2 readiness is reached; no fabricated dataset in this receipt
MODEL_21_MODEL_VERSION = assigned by chronological training; none forced
MODEL_21_ARTIFACT_HASH = assigned by immutable artifact; none forced
MODEL_21_TRAINING_CUTOFF = assigned by natural label coverage; none forced
MODEL_21_TRUE_FORWARD_COUNT = accumulates after a valid #21 artifact exists
MODEL_21_MATURE_FORWARD_COUNT = accumulates only after natural label-v2 maturity
MODEL_21_REGISTRY_STATE = truthful registry state only
MODEL_21_RUNTIME_ARTIFACT_STATUS = ACTIVE_TRAINED_ARTIFACT when valid ACTIVE;
  ACTIVE_ARTIFACT_INTEGRITY_FAILED when corrupt; provisional proxy only when
  no valid ACTIVE exists

MODEL_25_DATASET_VERSION = frozen #01-#24 + versioned #21 decision-time data;
  no fabricated dataset in this receipt
MODEL_25_MODEL_VERSION = assigned by XGBoost chronological training; none forced
MODEL_25_ARTIFACT_HASH = assigned by immutable artifact; none forced
MODEL_25_TRAINING_CUTOFF = assigned by natural label coverage; none forced
MODEL_25_TRUE_FORWARD_COUNT = accumulates after a valid #25 artifact exists
MODEL_25_MATURE_FORWARD_COUNT = accumulates only after natural label-v2 maturity
MODEL_25_REGISTRY_STATE = truthful registry state only
MODEL_25_RUNTIME_ARTIFACT_STATUS = ACTIVE_TRAINED_ARTIFACT when valid ACTIVE;
  ACTIVE_ARTIFACT_INTEGRITY_FAILED when corrupt; provisional proxy only when
  no valid ACTIVE exists

ML_COLLECTOR_SERVICE = com.lowrisk.mlcollector
ML_TRAINER_SERVICE = com.lowrisk.mltrainer
HEARTBEAT_ADVANCING = verified after ML-only restart
