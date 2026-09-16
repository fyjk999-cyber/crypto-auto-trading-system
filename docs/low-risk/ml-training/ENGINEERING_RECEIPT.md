# ML Engineering Closure Receipt

Branch: `codex/low-risk-v2-ml-closure`
Starting SHA: `893dbe0100d5c034192ec12381c7b96a833f1eb5`

## Checkpoints

| SHA | Scope | Tests |
|---|---|---|
| `3c0ec7b` | factual label ORM + migration 0031 | ruff + ORM check |
| `9a7e3ed` | factual collector + maturity labels | 3 focused + 14 adjacent |
| `59e77c5` | data quality/readiness/immutable freeze | 3 focused + 17 adjacent |
| `53fb04b` | registry + #21 walk-forward trainer | 6 focused |
| `32c8911` | post-cost/shadow/promotion gate | 3 focused |
| `86769b8` | retraining/degradation/rollback | 2 focused |
| `25252d3` | #25 meta pipeline gated behind #21 | 3 focused |
| `66df301` | autonomous orchestrator + trainer loop | 2 focused |
| `a25bc23` | macOS wrappers + LaunchAgent templates | 2 artifact tests |
| `05cd7f3` | pipeline docs + runtime artifact ignores | docs only |

## Engineering acceptance

| Item | Status |
|---|---|
| COLLECTOR_IMPLEMENTED | YES |
| LABEL_STORAGE_IMPLEMENTED | YES |
| MIGRATION_0031_IMPLEMENTED | YES |
| READINESS_ENGINE_IMPLEMENTED | YES |
| DATASET_FREEZER_IMPLEMENTED | YES |
| MODEL_REGISTRY_IMPLEMENTED | YES |
| MODEL_21_TRAINER_IMPLEMENTED | YES |
| WALK_FORWARD_IMPLEMENTED | YES |
| POST_COST_IMPLEMENTED | YES |
| SHADOW_IMPLEMENTED | YES |
| PROMOTION_GATE_IMPLEMENTED | YES |
| RETRAINING_IMPLEMENTED | YES |
| ROLLBACK_IMPLEMENTED | YES |
| MODEL_25_PIPELINE_IMPLEMENTED | YES (gated) |
| AUTONOMOUS_TRAINER_IMPLEMENTED | YES |
| MACOS_WRAPPERS_IMPLEMENTED | YES |
| LAUNCHAGENT_TEMPLATES_IMPLEMENTED | YES |

## Tests

- Focused ML/low-risk suite: **235 passed** (`pytest tests/low_risk -q`).
- Scanner/factors/runtime regression: **87 passed**.
- Full repository suite: **892 passed**, 1 warning, 101.9s (`pytest tests -q`).
- Ruff: clean on every new module, script and template.

## Runtime / deployment status

- Services not installed in this engineering phase.
- `COLLECTOR_RUNNING = NO`; `TOTAL_SCAN_SNAPSHOTS = 0`; candidate/control samples 0.
- `ML_DATA_READY = NO`; `MODEL_21_TRAINING_STATUS = WAITING_FOR_FACTUAL_SAMPLES`;
  `MODEL_25_TRAINING_STATUS = WAITING_FOR_FACTUAL_SAMPLES`.

## Authority

- `MODEL_21_ORDER_AUTHORITY = NO`; `MODEL_25_ORDER_AUTHORITY = NO`.
- `LLM_REQUIRED_FOR_TRAINING = NO`; LLM not used for labels, splits, metrics or promotion.
- `CORE_LLM_AUTHORITY_UNCHANGED = YES`; `EXECUTION_AUTHORITY_UNCHANGED = YES`.

## Blockers

- P0: none.
- P1: deployment not yet run; factual samples and labels must accumulate before readiness passes.

## Status

`AUTONOMOUS_ML_ENGINEERING = PASS` (engineering complete, ready for deployment).

## Deployment evidence (2026-09-16)

- Runtime dir: `/Users/huhongjie/lowrisk-ml` (self-contained clone, outside TCC-protected folders).
- Services: `com.lowrisk.mlcollector` running (pid 46360), `com.lowrisk.mltrainer` running
  (pid 46485), both owned by user launchd with `RunAtLoad` and `KeepAlive`.
- DB: `data/ml/scan_dataset.db`; heartbeat: `data/ml/collector_heartbeat.json`.
- Collector heartbeat: cycles 3, snapshots 30, candidates 16, controls 14, labels 70, errors 0.
- DB totals: 140 snapshots (70 candidate / 70 control), 25+ symbols, labels: 1m=130, 5m=100, 15m=30.
- Post-fix factual coverage (30 rows captured after deployment): l1_imbalance, l5_imbalance,
  microprice, cvd and trade_count all 0.0 null rate; all rows `available_at_decision_time = true`.
- Trainer heartbeat: state `WAITING_FOR_DATA`, no LLM, no orders, no training forced.
- Readiness: `NO` with reasons `insufficient_snapshots:140<200`,
  `feature_incomplete:l1_imbalance:0.7857>0.5` (legacy pre-fix rows),
  `insufficient_time_coverage:0<3`. Collection continues automatically.
- Final status: `AUTONOMOUSLY_ACCUMULATING`; `ML_DATA_READY = NO`; #21/#25 remain
  `WAITING_FOR_FACTUAL_SAMPLES`. No synthetic data or labels were created.
  Model order/risk/sizing authority remains NO.
- Final full repository suite on branch HEAD (runtime code 6b64aa7): **895 passed**, 1 warning, 94.5s.
