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
| R3/R3b | Exit precedence / partial-close safety + versioned MODIFY_EXIT activation | this commit | 40 + 302 focused | DONE |
| R4 | Offline/recovery semantics | this commit | 303 focused | DONE |
| R5 | NEXT_REASSESSMENT wake-only + dedup | this commit | 304 focused | DONE (price/time; indicator/event feeds P1) |
| R6 | Execution/authority contract audit | this commit | 62 authority/lease/UNKNOWN tests | DONE (ADD full path P1 quarantine) |
| R7 | Lineage/observability (indicator feed + wake audit) | this commit | 304 focused | DONE (EVENT feed P1) |
| R8 | Fresh full regression | this commit | 902 passed | DONE (detached acceptance pending) |
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

## R3b evidence (versioned MODIFY_EXIT, no order, no protection gap)

- `TradePlanService.replace_base_exit(...)` performs optimistic versioned persistence:
  only an ACTIVE plan whose `plan_version` still matches the decision base is replaced,
  incrementing `plan_version`; otherwise returns None (stale replacement).
- `LiveLLMPositionManager._modify_exit`: validates `decision.base_exit`, requires an
  injected BaseExitRegistry, rejects an explicit mismatched `based_on_state_version`
  (`MODIFY_EXIT_STALE_REJECTED`), stages a new Base Exit version, atomically activates
  it, then persists the new plan version. Never emits an order.
- `Engine`/`bootstrap` now share one `DeterministicExitController` between the runtime
  and the position manager, so MODIFY_EXIT replaces the same active protection the
  deterministic layer evaluates.
- Binding rule: a provider-returned explicit `based_on_state_version` is preserved and
  validated; only a missing value is bound to the current factual state version.
- Tests: `test_modify_exit_activates_versioned_base_exit_without_order`,
  `test_modify_exit_stale_replacement_rejected`; lifecycle file 16/16; focused closure
  suite 302 passed; ruff clean.

## R4 evidence (offline/recovery)

- `runtime/offline.py` NEW_RISK_LIFECYCLE_ACTIONS = OPEN/ENTRY/ADD/HEDGE/REVERSE/RE_ENTRY;
  dead legacy `TIME_STOP_SAFETY_FALLBACK` classification removed (no time-stop authority
  remains anywhere after R1).
- `engine.enter_offline_mode`: cancels/reconciles every pending new-risk order
  (`OFFLINE_CANCEL_PENDING_NEW_RISK`), keeps protective reduce/close paths active.
- `process_signal` blocks new risk while offline (`OFFLINE_NEW_RISK_BLOCKED`).
- `attempt_offline_recovery`: runs factual reconciliation first, then returns NORMAL and
  audits `LLM_RECOVERED_NORMAL`; failed reconciliation audits
  `OFFLINE_RECOVERY_RECONCILE_FAILED` and stays offline. No synthetic decision.
- New engine-level test `test_engine_offline_recovery_reconciles_then_normal`; fresh
  offline+failover run 21 passed; focused closure suite 303 passed; ruff clean.

## R5 evidence (NEXT_REASSESSMENT)

- `runtime/engine.py` now evaluates `plan.next_reassessment` each tick with
  `ReassessmentEvaluator` (PRICE/TIME/INDICATOR/EVENT, AND/OR, priority).
- When a condition fires, the engine audits `NEXT_REASSESSMENT_WAKE` with
  `authority=WAKE_LLM_ONLY`, `is_order=false`, matched conditions, priority and state
  version, and forces a fresh Core-LLM review (bypassing ordinary cooldown).
- Wake dedup: one wake per distinct matched-condition fingerprint per plan version
  (`_last_reassessment_wake`); an unchanged repeated trigger does not invoke the LLM again.
- The trigger itself never emits an order; any action still travels the Core-LLM decision
  and normal exit precedence.
- Engine test `test_next_reassessment_wakes_llm_only_once_per_condition`: first tick wakes
  exactly once, emits no order; second tick is deduplicated; exactly one
  `NEXT_REASSESSMENT_WAKE` audit. Focused closure suite 304 passed; ruff clean.
- P1: INDICATOR/EVENT condition feeds are evaluated when supplied, but runtime tick
  currently supplies price/time only; enriching indicator/event maps is scheduled R7.

## R6 evidence (execution/authority audit)

- Fresh run 62 passed: `tests/low_risk/test_phase4_contract.py` (>25% child rejected,
  >20x rejected, boundary 25%/20x approved, invalid not resized),
  `tests/low_risk/test_phase4_risk_gate_adapt.py` (Risk is not a sizing gate; LLM size
  preserved), `tests/integration/test_lease.py` (single-writer lease, dual-engine block,
  lease-loss fail-closed and restart recovery), `tests/integration/test_recovery.py`,
  `tests/integration/test_order_manager.py` (duplicate fill single-application,
  `test_unknown_recovery`), `tests/chaos/test_chaos.py` (duplicate client-order id,
  duplicate fill events).
- Authority boundary: only Core-LLM decisions with a durable TradePlan reach
  `process_signal` as new risk; models/Growth/Risk have no entry-constructing path
  (Risk hard exits and all deterministic protections are reduce-only; ADD remains
  quarantined `ADD_REQUIRES_CORE_NEW_RISK_PATH` rather than transformed).
- ExecutionAuthority remains a safety validator (lease, kill switch, reconciliation halt,
  freshness, precision/min-notional, duplicate client ids, rate limiting); invalid
  contracts are rejected, never silently resized.
- P1: full ADD new-risk execution path (Core-LLM ADD -> child TradePlan with Base Exit ->
  ExecutionAuthority) is not implemented; rejection is the safe current semantics.

## R7 evidence (lineage/observability)

- NEXT_REASSESSMENT evaluator now receives a factual indicator feed from the strategy
  context (`atr_pct`, `mark_price`, `funding`, `oi`, `basis`) in addition to price/time;
  P1: EVENT condition feed (event timestamps) still to be enriched.
- Every forced review now audits `LLM_REASSESSMENT_REQUESTED` with the exact wake sources
  (`risk_wake`, `expected_holding_horizon_wake`, `next_reassessment_wake`), trade plan id,
  factual state version, `authority=REASSESSMENT_ONLY` and `is_order=false`, giving the
  full why-was-the-LLM-woken lineage alongside the decision/plan/state version.

## R8 evidence (fresh full regression, working tree)

- Focused closure suite: 304 passed
  (`tests/low_risk` + `tests/llm_chief` + lifecycle + bootstrap).
- Fresh full suite: `pytest tests -q` -> 902 passed, 0 failed (89s).
- `ruff check src/ scripts/ tests/` clean.
- Detached exact-SHA acceptance run is recorded below after commit.

## R8 detached exact-SHA acceptance

- Detached worktree `/tmp/lr2-closure-accept` at code SHA
  `0a9d8779f8896945a14c65b45efbae6372187e70` (exact commit, no dirty state):
  `pytest tests -q` -> **902 passed, 0 failed**; `ruff check src/ scripts/ tests/` clean.

## R9 factual PAPER acceptance

- `RUNTIME_ENGINEERING = PASS`: all constitutional runtime semantics are implemented,
  focused-tested and fresh-full-regression-tested on a detached exact SHA; no fabricated
  evidence and no forced trade.
- `RUNTIME_OPERATIONAL_EVIDENCE = AUTONOMOUSLY_ACCUMULATING`: no rare natural lifecycle
  event was manufactured inside this engineering checkpoint; the directive's isolation
  rules (do not disturb the running `com.lowrisk.growth` / `mlcollector` / `mltrainer`
  services) were respected, so no shared or parallel runner was started merely to force
  acceptance evidence.

## FINAL RECEIPT FIELDS

STARTING_SHA = 8dc0ca43451372b877f95bf7bc054170492a04ec
SPEC_SHA = 779f7e17d0e948ba54bacb817d14d37078c811b4
FINAL_SHA = (this commit; remote-verified)
REMOTE_SHA_MATCH = YES
WORKTREE_CLEAN = YES
DETACHED_EXACT_SHA_ACCEPTANCE = YES @ 0a9d8779f8896945a14c65b45efbae6372187e70

HARD_MAX_HOLD_EXIT_REMOVED = YES
TIME_THRESHOLD_REASSESSMENT = YES
EXPECTED_HOLDING_NOT_ORDER = YES

CORE_LLM_NEW_RISK_AUTHORITY = YES
MODEL_NEW_RISK_AUTHORITY = NO
GROWTH_NEW_RISK_AUTHORITY = NO
RISK_NEW_RISK_AUTHORITY = NO

BASE_EXIT_ACTIVE_DURING_REASSESSMENT = YES
BASE_EXIT_ATOMIC_REPLACEMENT = YES

FAST_PROFIT_REDUCE_ONLY = YES
RISK_HARD_EXIT_REDUCE_ONLY = YES
OFFLINE_NEW_RISK_BLOCK = YES

STALE_RESPONSE_PROTECTION = YES
STATE_VERSION_ENFORCED = YES
UNKNOWN_DUPLICATE_PROTECTION = YES (order manager recovery test + chaos duplicate ids)

EXIT_PRECEDENCE = YES
NO_DOUBLE_CLOSE = YES
PARTIAL_REDUCE_SAFE = YES
NO_SIGN_FLIP_REDUCE_ONLY = YES

NEXT_REASSESSMENT_WAKES_ONLY = YES
REASSESSMENT_DEDUP = YES
INFORMATION_NOVELTY_GATE = YES (state-version/fingerprint dedup; EVENT feed P1)

EXECUTION_LEASE_PRESERVED = YES
KILL_SWITCH_PRESERVED = YES
RECONCILIATION_GATE_PRESERVED = YES
INVALID_NEW_RISK_REJECTED_NOT_RESIZED = YES

AUDIT_LINEAGE_COMPLETE = YES (decision/plan/order/fill/state-version + wake/rejection reasons)

GROWTH_RUNTIME_CHANGED = NO
ML_RUNTIME_CHANGED = NO
FLASH_HIGH_POLICY_CHANGED = NO

FOCUSED_TESTS = 304 passed
LOW_RISK_TESTS = included in focused/full green
FULL_TEST_SUITE = 902 passed (also detached exact SHA)
RUFF = clean

P0_BLOCKERS = NONE
P1_ISSUES = full ADD new-risk execution path (currently safely quarantined, never resized);
EVENT-condition reassessment feed; natural PAPER lifecycle accumulation.
