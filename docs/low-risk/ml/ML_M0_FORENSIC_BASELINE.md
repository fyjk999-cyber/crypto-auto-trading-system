# M0 - FORENSIC BASELINE + LABEL-V1 SAFETY GATE

- Repository: fyjk999-cyber/crypto-auto-trading-system
- SPEC_SHA / STARTING_SHA: a4bf252fdde093eb322974c4aba1dd4e1c0a5e1c
- Implementation branch: codex/low-risk-ml-final-scientific-closure
- Worktree: /Users/huhongjie/Documents/ChatGPT/crypto-ml-final-closure
- Mode: PAPER only; models are LEARNING_ONLY / EVIDENCE_ONLY.

## Runtime / service baseline (2026-09-16T12:55Z)

| Item | Fact |
|---|---|
| Runtime clone | /Users/huhongjie/lowrisk-ml, HEAD 6b64aa723b90dd4b63556781181e4098ec02e855 (detached) |
| launchd plist RUNNING_SHA | 31c13f4da4bf (stale vs clone HEAD - P1 config drift) |
| Collector service | com.lowrisk.mlcollector, PID 46360, KeepAlive, WorkingDirectory /Users/huhongjie/lowrisk-ml |
| Trainer service | com.lowrisk.mltrainer, PID 46485, KeepAlive, WorkingDirectory /Users/huhongjie/lowrisk-ml |
| Collector command | scripts/run_ml_collector_macos.sh -> $ML_PYTHON scripts/ml_collector.py data/ml/scan_dataset.db data/ml/collector_heartbeat.json |
| Trainer command | scripts/run_ml_trainer_macos.sh -> $ML_PYTHON scripts/ml_trainer.py data/ml/scan_dataset.db data/ml |
| ML DB | /Users/huhongjie/lowrisk-ml/data/ml/scan_dataset.db |
| ML DB backup | /Users/huhongjie/lowrisk-ml/data/ml/backups/scan_dataset.m0-20260916T125505Z.db (labels=8450, snapshots=1750 at backup time) |
| Migration head (implementation repo) | 0031_scan_snapshot_labels; ML DB has no alembic_version table (runtime schema created via metadata) |
| state.json | state=WAITING_FOR_DATA, reasons=["insufficient_time_coverage:0<3"] |
| collector heartbeat | cycles=169, snapshots=1640, candidates=1132, controls=508, labels=8260, errors=7, last_error=OKXDiagnosticError: Unable to connect to OKX |
| trainer heartbeat | WAITING_FOR_DATA, no dataset/model versions |

## Factual row counts at M0 (DB advancing while collector runs)

- scan_snapshots: 1750 (candidates 1186, controls 564)
- labels total: 8450; label-v1: 8450; label-v2: 0
- label-v1 by horizon: 1m=1740, 5m=1720, 15m=1660, 30m=1570, 1h=1410, 4h=350
- models/datasets/shadow artifact files: 0 / 0 / 0
- shadow_campaigns/prediction_results: 0
- registry model states: none (state.json has no model versions)

## Existing ML module map (baseline)

| Module | Responsibility | Baseline gap |
|---|---|---|
| scripts/ml_collector.py | OKX scanner snapshots + label-v1 maturer | uses wake-time ticker price, 22 bps constant, future_high==future_low==price |
| src/crypto_trader/ml_dataset.py | quality/readiness/immutable dataset freeze | hardcoded label-v1, no version/maturity gate |
| src/crypto_trader/ml_trainer.py | features, folds, logistic fit, walk-forward | default label_version label-v1 |
| src/crypto_trader/ml_meta.py | provisional weighted #25 proxy | logistic fit, label-v1 |
| src/crypto_trader/ml_orchestrator.py | autonomous trainer loop + historical "shadow" tail predictions | replay shadow, label-v1 |
| src/crypto_trader/ml_registry.py | model registry states/artifacts | usable, no ACTIVE cutover proof |
| src/crypto_trader/ml_shadow.py | prediction storage | needs true-forward contract |
| src/crypto_trader/ml_lifecycle.py | retrain/degrade/rollback helpers | needs versioned policy/events |
| src/crypto_trader/factors/expert/models.py | #21/#25 evidence models | PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED |

## M0 safety gate implemented

- `ml_dataset.FINAL_LABEL_VERSION = "label-v2"`; readiness now requires non-zero
  label-v2 rows and adds `label_v1_excluded_from_final_training` when label-v1 exists.
  Label-v1 can never satisfy final readiness.
- `freeze_dataset` selects label-v2 rows only and returns
  `{ready: false, reason: "NO_LABEL_V2"}` (no file written) when only label-v1 exists.
- Data quality exposes `label_counts_by_version` and `final_label_count` for audit.
- Tests superseded by the constitution: old label-v1 readiness/freeze/orchestrator
  expectations were updated to label-v2 with OLD/NEW comments; added
  `test_label_v1_only_is_excluded_from_final_training` and
  `test_label_v1_only_cannot_train_or_promote`.
- No runtime clone, service, Growth line, artifact, snapshot or label-v1 row was
  modified or deleted. ML DB was backed up before any future migration.

## Evidence

- Focused ML tests: 29 passed including updated dataset/orchestrator gates.
- Ruff: clean (src, scripts, tests).
- Next: M1 label-v2 exact factual maturer (T0+horizon reconstruction, pagination,
  no-lookahead, cost versioning, maturity statuses).
