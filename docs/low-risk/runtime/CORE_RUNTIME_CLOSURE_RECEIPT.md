# CORE RUNTIME CONSTITUTION CLOSURE - CHECKPOINT RECEIPT

STARTING_SHA: 8dc0ca43451372b877f95bf7bc054170492a04ec
SPEC_SHA: 779f7e17d0e948ba54bacb817d14d37078c811b4
BRANCH: codex/low-risk-core-runtime-constitution-closure
WORKTREE: /Users/huhongjie/Documents/ChatGPT/crypto-low-risk-core-closure

## Checkpoints

| # | Scope | Commit | Tests | Status |
|---|-------|--------|-------|--------|
| R0 | Forensic runtime authority map | a42905d | docs | DONE |
| R1 | Remove hard max-hold exit; reassessment-only horizon; ADD/MODIFY_EXIT reduce fallthrough quarantined | 0b7c464 | 296 focused | DONE |
| R2 | Fresh-state stale-response rejection; horizon wake dedup (one per factual state version) | pending | 297 focused | DONE |
| R3 | Exit precedence / partial-close safety | this commit | 40 focused | VERIFIED (versioned MODIFY_EXIT activation pending R3b) |
| R4 | Offline/recovery semantics | - | - | TODO |
| R5 | NEXT_REASSESSMENT closure | - | - | TODO |
| R6 | Execution/authority contract audit | - | - | TODO |
| R7 | Lineage/observability | - | - | TODO |
| R8 | Fresh full regression | - | - | TODO |
| R9 | Factual PAPER acceptance | - | - | TODO |

## R2 evidence

- `llm_chief/state_version.py::position_state_version(position, plan)` is now the single
  factual version source; `TradingEngine._position_state_version` delegates to it.
- `LiveLLMPositionManager.review`:
  - binds `state_version_before` into `ChiefTraderContext.state_version` and the persisted
    decision (`based_on_state_version`);
  - if factual state changed while the LLM was thinking (Base Exit fill, partial reduction,
    position close, leg change, UNKNOWN), audits `STALE_LLM_RESPONSE_REJECTED` and returns
    None: no new risk, no exit replacement, no order.
- Expected-holding-horizon wake is deduplicated: `horizon_wake_due()` allows one reassessment
  per factual state version (`_last_horizon_wake_state`), so unchanged facts are not
  repeatedly invoked; a new fill/plan version re-arms it.
- Provider retry/failover continues to require a fresh-state rebuilder
  (`build_rebuild_kwargs` + fresh context provider); stale prompt replay stays blocked
  (`BACKUP_SKIPPED_NO_FRESH_CONTEXT`).
- Tests added/updated in `tests/integration/test_live_llm_position_lifecycle.py`:
  horizon reassessment not forced exit + no-novelty suppression; stale response rejected
  after a factual state change; ADD and MODIFY_EXIT never become reduce orders.
- Fresh focused run: 297 passed (tests/low_risk + tests/llm_chief + lifecycle file);
  ruff check src/ scripts/ tests/ clean.
- Known intermittent: simulator fill-timing test flakes under load
  (`test_position_action_waits_until_partially_filled_entry_order_is_terminal`), passes
  isolated 3/3 and on fresh rerun; not an order/authority defect.

## Final receipt fields (to fill at R8/R9)

HARD_MAX_HOLD_EXIT_REMOVED = YES
TIME_THRESHOLD_REASSESSMENT = IMPLEMENTED
EXPECTED_HOLDING_NOT_ORDER = YES
STALE_RESPONSE_PROTECTION = IMPLEMENTED
REASSESSMENT_DEDUP = IMPLEMENTED
INFORMATION_NOVELTY_GATE = PARTIAL (material-event coordinator exists and is unit-tested;
runtime event-feed wiring scheduled R5/R7)
MODIFY_EXIT ATOMIC REPLACEMENT = QUARANTINED (no order); versioned activation scheduled R3
ADD NEW-RISK PATH = QUARANTINED (no order/reduce); full path scheduled R6
GROWTH_RUNTIME_CHANGED = NO
ML_RUNTIME_CHANGED = NO
FLASH_HIGH_POLICY_CHANGED = NO

## R3 evidence (fresh)

- Fresh run: `pytest tests/low_risk/test_phase4_exit_coordinator.py
  tests/low_risk/test_phase4_base_exit.py tests/low_risk/test_phase4_fast_profit.py
  tests/low_risk/test_phase7_exit_races.py -q` -> 40 passed.
- Covered: Risk Hard Exit > Fast Profit > active Base Exit > LLM discretionary
  precedence; stale Base Exit version rejected (`STALE_DECISION`); atomic Base Exit
  activation; partial preemption without oversell; cancel/fill and duplicate-fill races
  (no double close); fill larger than reservation never goes below zero; grown position
  reservation revalidation.
- `MODIFY_EXIT` can never become a discretionary reduce order (R1 quarantine test
  `test_modify_exit_action_never_becomes_reduce_order`). Full versioned
  validate -> persist -> atomic activate replacement on TradePlanService/BaseExitRegistry
  remains the next R3b slice (currently safe quarantine, no protection gap created
  because the existing Base Exit stays active).
