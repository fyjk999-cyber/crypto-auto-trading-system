# Autonomous Low-Risk ML Pipeline

Status: engineering complete, waiting for factual samples. PAPER/research only.

## Architecture

REAL OKX market -> OpportunityScannerService.scan_once() -> candidate + stratified control
snapshots (`scripts/ml_collector.py`) -> maturity-gated factual labels
(`ScanSnapshotLabelORM`, migration 0031) -> data quality + readiness + immutable freeze
(`crypto_trader.ml_dataset`) -> #21 walk-forward training (`crypto_trader.ml_trainer`) ->
post-cost + shadow + promotion (`crypto_trader.ml_shadow`) -> registry/lifecycle
(`crypto_trader.ml_registry`, `crypto_trader.ml_lifecycle`) -> #25 meta pipeline
(`crypto_trader.ml_meta`) -> autonomous orchestrator (`crypto_trader.ml_orchestrator`,
`scripts/ml_trainer.py`).

## Components

| Component | File | Authority |
|---|---|---|
| Collector | `scripts/ml_collector.py` | learning only, no LLM/keys |
| Labels | `persistence.models.ScanSnapshotLabelORM`, migration `0031` | factual outcomes |
| Quality/readiness/freeze | `crypto_trader/ml_dataset.py` | deterministic gates |
| #21 trainer + walk-forward | `crypto_trader/ml_trainer.py` | EVIDENCE_ONLY |
| Post-cost/shadow/promotion | `crypto_trader/ml_shadow.py` | deterministic, no LLM vote |
| Registry | `crypto_trader/ml_registry.py` | immutable versions |
| Retraining/degradation/rollback | `crypto_trader/ml_lifecycle.py` | evidence only |
| #25 meta | `crypto_trader/ml_meta.py` | gated behind valid #21 |
| Orchestrator | `crypto_trader/ml_orchestrator.py`, `scripts/ml_trainer.py` | restart-safe |

## Safety invariants

- `MODEL_21_ORDER_AUTHORITY = NO`; `MODEL_25_ORDER_AUTHORITY = NO`.
- No order, position, TradePlan, Base Exit, leverage or risk-limit changes.
- `LLM_REQUIRED_FOR_TRAINING = NO`; no LLM in labels, splits, metrics or promotion.
- Core LLM new-risk authority and ExecutionAuthority unchanged.
- L10/basis remain NULL when the feed does not provide them; no unsupported imputation.

## Runbook (macOS, no LLM credentials required)

1. Create the durable layout under `data/ml/` (wrappers do this automatically).
2. Substitute `__PYTHON__`, `__REPO__`, `__SHA__` in the LaunchAgent templates:
   `deploy/launchagents/com.lowrisk.mlcollector.plist` and `com.lowrisk.mltrainer.plist`.
3. Install user-level services with `launchctl bootstrap gui/$(id -u) <plist>` and
   `launchctl kickstart -k gui/$(id -u)/<label>`.
4. Collector writes `scan_dataset.db` and `collector_heartbeat.json`; trainer writes
   `registry.json`, `state.json`, `trainer_heartbeat.json`, datasets, models and shadow rows.
5. When readiness becomes YES the trainer trains #21 automatically; #25 stays gated until a
   valid #21 shadow/active artifact exists. Promotion is deterministic; LLM review is optional
   and read-only.

## Verification status

- Focused ML tests: `tests/low_risk` 235 passed (collector, labels, dataset, registry,
  trainer, shadow, lifecycle, meta, orchestrator, deployment artifacts).
- Scanner/factor/runtime regression: 87 passed.
- Ruff clean on all new modules, scripts and templates.
- Factual samples: 0 until services are deployed; `ML_DATA_READY = NO`.
- `MODEL_21_TRAINING_STATUS = WAITING_FOR_FACTUAL_SAMPLES`;
  `MODEL_25_TRAINING_STATUS = WAITING_FOR_FACTUAL_SAMPLES`.
- Full repository suite on this SHA: `pytest tests -q` -> **892 passed**, 1 warning, 101.9s
- Factual deployment status: services not yet installed; `COLLECTOR_RUNNING = NO`; samples 0.
