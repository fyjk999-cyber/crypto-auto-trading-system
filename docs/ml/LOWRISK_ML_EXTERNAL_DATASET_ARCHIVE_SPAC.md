# LOWRISK ML EXTERNAL DATASET ARCHIVE SPAC

Status: AUTHORITATIVE TASK SPEC
Version: 1.0
Scope: LowRisk derived ML dataset migration to external disk
Trading authority: NONE
Model-promotion authority: NONE

## 1. Purpose

Migrate the large LowRisk derived ML dataset store from the Mac internal SSD to a dedicated external-disk archive, then reclaim the verified redundant local copy.

Source:

`/Users/huhongjie/lowrisk-ml/data/ml/datasets`

Target:

`/Volumes/My PSSD/MLArchive/lowrisk/datasets`

Known inventory size is approximately 298 GB, but all acceptance receipts must use measured values, not projections.

This task is storage relocation only.

It must not change:
- feature semantics;
- label semantics;
- prediction horizon;
- model family;
- promotion thresholds;
- ML authority;
- LowRisk strategy;
- Risk;
- leverage;
- execution.

## 2. Strict separation from Shared History

The target is NOT Shared Market History.

Required final layout:

```text
/Volumes/My PSSD/
├── SharedMarketHistory/
│   └── factual canonical historical market data
└── MLArchive/
    └── lowrisk/
        └── datasets/
            └── derived ML datasets
```

Never write derived ML datasets into:

`/Volumes/My PSSD/SharedMarketHistory`

Shared History remains the canonical factual market truth.
MLArchive stores derived ML training/OOS/replay datasets.

## 3. In-scope data

Primary in-scope source:

`/Users/huhongjie/lowrisk-ml/data/ml/datasets`

Classify its contents as applicable:
- DERIVED_FEATURE_DATASET
- TRAINING_SNAPSHOT
- OOS_DATASET
- REPLAY_DATASET
- TEMPORARY_DATASET
- UNKNOWN

Only the dataset tree is eligible for this migration.

## 4. Explicitly out of scope

Do NOT move, archive, modify or delete:

- `scan_dataset.db`;
- ML model registry;
- active model artifact;
- model checkpoints needed by runtime;
- LowRisk trading DB;
- orders/fills/positions;
- Risk state;
- execution state;
- PAPER account state;
- Growth memory;
- LLM decision DB;
- Shared History Parquet;
- Shared History checkpoints;
- credentials/API keys;
- Turbo runtime state.

## 5. Phase 0 — runtime truth

Before any copy, record:

```text
ML_STARTING_SHA =
ML_BRANCH =
ML_DATASET_SOURCE =
ML_DATASET_TARGET =
ML_COLLECTOR_PID =
ML_TRAINER_PID =
ML_RUNTIME_PID =
CURRENT_DATASET_ROOT_CONFIG =
ACTIVE_DATASET_READERS =
ACTIVE_DATASET_WRITERS =
WORKTREE_CLEAN =
```

Active readers alone are not a blocker.

Any active writer to the source dataset tree is a blocker to taking a consistent migration snapshot.

Pause/stop only canonical ML dataset-producing jobs if needed.

Do NOT stop:
- LowRisk PAPER runtime;
- Shared History service;
- Turbo.

Before initial copy:

`ACTIVE_DATASET_WRITERS = 0`

## 6. Inventory

Record measured:
- source file count;
- source directory count;
- source logical bytes;
- dataset IDs/versions;
- feature schema versions;
- label schema versions;
- oldest/newest relevant timestamps.

Do not classify derived datasets as canonical market truth.

## 7. Target capacity and health

Before copy verify:
- `/Volumes/My PSSD` is mounted;
- target is writable;
- enough free space exists for the measured source plus safety margin;
- target filesystem is healthy enough for the operation.

If capacity is unsafe, stop before destructive operations.

## 8. Migration method

Mandatory order:

```text
inventory
→ quiesce dataset writers
→ resumable copy
→ structural/integrity verification
→ path switch
→ real read validation
→ prove future writes use external root
→ local deletion gate
→ delete only verified redundant local dataset copy
→ post-delete validation
```

Never perform move-first or delete-before-verify.

Use a resumable copy mechanism such as rsync or equivalent.

Do not follow unsafe symlinks.

AppleDouble `._*` files are not factual ML dataset content.

## 9. Copy acceptance

Record:

```text
FILES_COPIED =
FILES_SKIPPED =
FILES_FAILED =
BYTES_COPIED =
SOURCE_FILE_COUNT =
TARGET_FILE_COUNT =
SOURCE_LOGICAL_BYTES =
TARGET_LOGICAL_BYTES =
```

Required before path switch:

```text
FILES_FAILED = 0
FILE_COUNT_MATCH = YES
BYTE_COUNT_MATCH = YES
```

Use full checksums where practical; otherwise use deterministic structural validation plus broad cryptographic checksum sampling.

## 10. Dataset integrity

Validate external copies through actual dataset readers, not filename existence alone.

Verify:
- dataset metadata;
- feature schema;
- label schema;
- symbols/universe metadata;
- timestamp ranges;
- representative row readability;
- training datasets;
- OOS datasets;
- replay datasets.

Required:

```text
CORRUPT_TARGET_FILES = 0
UNREADABLE_TARGET_FILES = 0
SCHEMA_MISMATCHES = 0
```

## 11. Canonical path configuration

Search all ML code/config/scripts/launch configuration for references to:

- `/Users/huhongjie/lowrisk-ml/data/ml/datasets`
- `data/ml/datasets`
- `ML_DATA_ROOT`
- `ML_DATASET_ROOT`
- `DATASET_ROOT`

Reuse the existing centralized configurable root if one exists.

Do not scatter hardcoded external paths through many modules.

Preferred final configuration:

`LOWRISK_ML_DATASET_ROOT=/Volumes/My PSSD/MLArchive/lowrisk/datasets`

or the equivalent existing canonical variable.

There must be one canonical ML dataset root after migration.

## 12. Path switch acceptance

After the verified copy, switch all dataset readers/writers to the target.

Required functional checks:

```text
TRAINING_DATA_LOAD = PASS
OOS_DATA_LOAD = PASS
REPLAY_DATA_LOAD = PASS
SCHEMA_VALIDATION = PASS
DATASET_DISCOVERY = PASS
DATASET_METADATA_LOOKUP = PASS
```

A bounded training/data-loader smoke test is allowed if it does not change model activation state.

Do NOT activate/promote any model.

## 13. Prove new writes use the external root

Run the canonical ML dataset producer/collector sufficiently to produce or update one factual dataset artifact.

Verify both roots.

Required:

```text
NEW_WRITE_EXTERNAL = YES
NEW_WRITE_LOCAL_OLD_ROOT = NO
LOCAL_OLD_ROOT_GROWTH_BYTES = 0
```

Do not delete the source until this has been proven.

## 14. External-disk absence behavior

The external target must fail closed if unavailable.

Required behavior:

```text
ML_DATASET_STORAGE = DATA_ROOT_UNAVAILABLE / FAIL_CLOSED
LOCAL_FALLBACK_CREATED = NO
```

Forbidden:
- silently recreating the old 298GB local dataset lake;
- silently switching to another local canonical root;
- inventing missing datasets.

## 15. Shared-disk coordination

This migration shares the physical external disk with Shared Market History.

Therefore:
- perform the heavy copy only after Shared History Phase A pre-migration freshness acceptance;
- Shared History freshness measurements during bulk copy are observational only;
- do not change Shared History thresholds because of migration I/O;
- do not start the final Shared History 24h soak until this migration and final concurrent-load acceptance are complete.

Reference coordinating SPAC:

`docs/shared-market-history/SHARED_HISTORY_STORAGE_CONVERGENCE_FINAL_SPAC.md`

## 16. Deletion gate

Local dataset deletion is authorized only if ALL are true:

```text
COPY_COMPLETE = YES
FILES_FAILED = 0
FILE_COUNT_MATCH = YES
BYTE_COUNT_MATCH = YES
TARGET_READABILITY = PASS
SCHEMA_VALIDATION = PASS
TRAINING_DATA_LOAD = PASS
OOS_DATA_LOAD = PASS
REPLAY_DATA_LOAD = PASS
NEW_WRITE_EXTERNAL = YES
NEW_WRITE_LOCAL_OLD_ROOT = NO
ALL_CONFIG_REFERENCES_SWITCHED = YES
NO_ACTIVE_FD_ON_LOCAL_DATASET_FILES = YES
EXTERNAL_VOLUME_HEALTH = PASS
```

If any condition fails:

`LOCAL_SOURCE_DELETED = false`

and stop.

## 17. Local cleanup

Only after the deletion gate passes, remove the redundant dataset contents under:

`/Users/huhongjie/lowrisk-ml/data/ml/datasets`

Do not delete the ML project or parent runtime structure.

Avoid symlink-based compatibility unless there is no safe centralized configurable-root mechanism.

Preferred final state:
- canonical dataset root = external target;
- old large local derived dataset copy = removed.

Measure actual Mac space reclaimed after deletion.

## 18. Post-delete validation

Repeat:
- dataset discovery;
- training data load;
- OOS data load;
- replay data load;
- schema validation;
- new-write-path verification.

Required:

```text
POST_DELETE_ML_DATA_LOAD = PASS
POST_DELETE_NEW_WRITE_EXTERNAL = YES
POST_DELETE_LOCAL_RECREATION = NO
```

## 19. Non-target invariants

Throughout:

```text
LOWRISK_TRADING_RUNTIME_RESTARTED = NO
TURBO_RESTARTED = NO
SHARED_HISTORY_RESTARTED = NO
STRATEGY_CHANGE = 0
RISK_CHANGE = 0
LEVERAGE_CHANGE = 0
AUTHORITY_CHANGE = 0
DEEPSEEK_STATE_CHANGED = NO
ML_MODEL_ACTIVATED = NO
ML_FILES_WRITTEN_TO_SHARED_HISTORY = 0
SHARED_HISTORY_FILES_MOVED_TO_MLARCHIVE = 0
```

If an ML dataset producer must be restarted to pick up the new root, restart only that canonical ML dataset job.

## 20. Rollback

Before local deletion, rollback is simple:
- restore the original dataset root configuration;
- resume using the untouched local source.

After local deletion, rollback must use the verified external dataset copy.

Never respond to a path/config failure by recreating an uncontrolled second full dataset lake.

## 21. Stop conditions

Stop and report if:
- active dataset writers cannot be safely quiesced;
- source/target counts or bytes cannot be reconciled;
- corruption or unreadable target files are found;
- target capacity becomes unsafe;
- required runtime/model-state files are discovered inside the proposed deletion scope;
- application requires semantic ML changes to support the storage relocation;
- external target cannot be made the single canonical dataset root.

## 22. Required final receipt

Return:

```text
LOWRISK_ML_EXTERNAL_ARCHIVE_MIGRATION_RECEIPT

SPAC_SHA =
ML_STARTING_SHA =
ML_FINAL_SHA =

SOURCE =
/Users/huhongjie/lowrisk-ml/data/ml/datasets

TARGET =
/Volumes/My PSSD/MLArchive/lowrisk/datasets

SOURCE_BYTES_BEFORE =
SOURCE_FILES_BEFORE =
TARGET_BYTES_AFTER =
TARGET_FILES_AFTER =

PRE_MIGRATION_ACTIVE_READERS =
PRE_MIGRATION_ACTIVE_WRITERS =
ML_JOBS_PAUSED =
POST_MIGRATION_ML_WRITERS =

FILES_COPIED =
FILES_SKIPPED =
FILES_FAILED =
BYTES_COPIED =

FILE_COUNT_MATCH =
BYTE_COUNT_MATCH =
CHECKSUM_VALIDATION =
CORRUPT_TARGET_FILES =
UNREADABLE_TARGET_FILES =

FEATURE_SCHEMA =
LABEL_SCHEMA =
DATASET_VERSIONS =
TRAINING_DATA_LOAD =
OOS_DATA_LOAD =
REPLAY_DATA_LOAD =
SCHEMA_VALIDATION =

OLD_DATASET_ROOT =
NEW_DATASET_ROOT =
CONFIG_FILES_CHANGED =
ALL_REFERENCES_SWITCHED =

NEW_WRITE_EXTERNAL =
NEW_WRITE_LOCAL_OLD_ROOT =
LOCAL_OLD_ROOT_GROWTH_BYTES =

EXTERNAL_ABSENCE_BEHAVIOR =
LOCAL_FALLBACK_CREATED =

DELETION_GATE =
LOCAL_SOURCE_DELETED =
LOCAL_BYTES_REMOVED =

POST_DELETE_ML_DATA_LOAD =
POST_DELETE_NEW_WRITE_EXTERNAL =
POST_DELETE_LOCAL_RECREATION =

MAC_FREE_BEFORE =
MAC_FREE_AFTER =
MAC_SPACE_RECLAIMED =
EXTERNAL_FREE_BEFORE =
EXTERNAL_FREE_AFTER =

ML_FILES_WRITTEN_TO_SHARED_HISTORY = 0
SHARED_HISTORY_FILES_MOVED_TO_MLARCHIVE = 0

LOWRISK_TRADING_RUNTIME_RESTARTED =
TURBO_RESTARTED =
SHARED_HISTORY_RESTARTED =

STRATEGY_CHANGE = 0
RISK_CHANGE = 0
AUTHORITY_CHANGE = 0
ML_MODEL_ACTIVATED = NO

ML_ARCHIVE_MIGRATION = PASS | BLOCKED
LOCAL_ML_SPACE_RECLAIM = PASS | BLOCKED
CANONICAL_ML_DATASET_ROOT =
BLOCKERS =
NEXT_REQUIRED_ACTION =
```

## 23. Governing principle

Separate factual market truth from derived ML datasets, keep one canonical root for each, validate before deleting, and prove the final external-disk topology under real concurrent load before Shared History begins its final soak.
