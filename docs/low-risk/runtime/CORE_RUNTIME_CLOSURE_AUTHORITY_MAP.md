# CORE RUNTIME CLOSURE - R0 FORENSIC AUTHORITY MAP

Baseline: 8dc0ca43451372b877f95bf7bc054170492a04ec
Spec: 779f7e17d0e948ba54bacb817d14d37078c811b4
Branch: codex/low-risk-core-runtime-constitution-closure
Scope: runtime authority semantics only (PAPER).

## Authority table (exact paths at baseline)

| Action | Originator | Authority gate | Decision object | TradePlan | Execution path | State/version protection |
|---|---|---|---|---|---|---|
| OPEN (LONG/SHORT) | Core LLM: runtime_strategy RuntimeStrategy -> llm_chief/engine.py decide -> decision ChiefTraderDecision | execution/authority.py ExecutionAuthority.authorize (V2 NewRiskOrderContract: Base Exit, <=25% child, <=20x) | FlatAction.LONG/SHORT | llm_chief/trade_planner.py create_entry_signal -> trade_plan/service.py | runtime/engine.py process_signal -> ExecutionAuthority -> PAPER adapter | plan_contract_version>=2, based_on_state_version, lease/fencing, duplicate client-order id |
| ADD | Core LLM OpenAction.ADD | same V2 contract as OPEN | ChiefTraderDecision.action=ADD | no dedicated path at baseline (drift 2) | was falling into position_manager reduce path; R1 quarantine | ADD_REQUIRES_CORE_NEW_RISK_PATH, no order |
| HEDGE | Core LLM OpenAction.HEDGE | execution/hedge_legs.py validate_hedge_leg + independent strategy/thesis/Base Exit; engine net-model gate | action=HEDGE | trade_planner.create_hedge_signal | engine.process_signal (net model fails closed: HEDGE_EXECUTION_BLOCKED_NET_MODEL) | leg registry, HedgeLegContract, lineage metadata |
| REVERSE | Core LLM OpenAction.REVERSE | as HEDGE + REVERSE_MISSING_SOURCE_LEG | action=REVERSE | create_hedge_signal(reverse_of=...) | as HEDGE | source leg required |
| REDUCE | Core LLM OpenAction.REDUCE | reduce-only path, no new-risk contract | position_size_request | current active plan | position_manager.review -> SignalIntent(reduce_only) -> process_signal | state_version freshness guard; factual qty bound |
| CLOSE / EXIT | Core LLM OpenAction.CLOSE/EXIT | reduce-only full remaining | action | current plan | as REDUCE | bounded by abs(position.quantity); R1 groups CLOSE with EXIT |
| MODIFY_EXIT | Core LLM OpenAction.MODIFY_EXIT | versioned Base Exit replacement (spec section 8) | base_exit on decision | plan/base-exit version | none at baseline (drift 3); R1 quarantine | MODIFY_EXIT_REQUIRES_VERSIONED_BASE_EXIT, no order |
| Base Exit | deterministic runtime, preauthorized by entry contract | runtime/exit_controller.py + execution/base_exit.py BaseExitRegistry | persisted TradePlan.base_exit | plan + active Base Exit version | engine._deterministic_exit_signals -> reduce-only SignalIntent | BaseExitVersion.based_on_state_version, atomic activate, STALE_DECISION rejection |
| Fast Profit | deterministic risk-reducing protection | risk/fast_profit.py + runtime/exit_controller.py priority FAST_PROFIT | exit-controller intent | current plan | deterministic reduce-only SignalIntent | intent state_version mismatch -> DETERMINISTIC_EXIT_STALE |
| Risk hard exit (L1/L2) | deterministic protection risk/risk_levels.py | PositionRiskMonitor.evaluate; L1->LLM reassessment, L2->forced close | RiskDecision | current plan | engine._deterministic_exit_signals priority RISK_HARD_EXIT | episode latch not reset by ADD; reduce-only |
| Offline reduce/protection | runtime/offline.py + engine offline rule | offline blocks new risk; protections continue | n/a | current plan | engine.enter_offline_mode cancels pending new-risk; deterministic exits still run | OFFLINE_NEW_RISK_BLOCKED for entries |
| NEXT_REASSESSMENT | Core LLM decision field | llm_chief/reassessment.py evaluation -> wake Core LLM only | NextReassessment | persisted on plan by trade_planner | wake path only, never an order | one-active-reassessment + novelty/dedup (R2) |

## Verified drift found in R0

1. HARD MAX-HOLD EXIT (spec section 2): llm_chief/position_manager.py computed
   max_hold_reached and time_stop = max_hold_reached and decision.action != EXIT,
   forcing a full TIME_STOP_SAFETY_FALLBACK reduce-only order even when the Core
   LLM returned HOLD/FAIL_CLOSED. Fixed in R1.
2. ADD fell through the reduce path: no OpenAction.ADD branch existed; the code
   emitted a reduce-only SignalIntent with lifecycle_action=ADD. Fixed in R1 by
   quarantine; ADD remains NEW RISK on the Core-LLM -> TradePlan ->
   ExecutionAuthority path.
3. MODIFY_EXIT fell through the reduce path: no handler existed, so a
   discretionary reduce order could be emitted without versioning the Base Exit.
   Fixed in R1 by quarantine; full atomic replacement remains for R2/R3.
4. CLOSE used position_size_request instead of factual full remaining; R1
   groups CLOSE with EXIT for full-remaining reduce.
5. max_holding_time_seconds remains a persisted field and API/context value
   (backward compatible) but is informational/reassessment-only.

## R1 required semantics (implemented)

- time threshold -> high-priority fresh Core-LLM reassessment (engine forces the
  review past the ordinary cooldown);
- no deterministic order originates from the time threshold;
- Base Exit / Fast Profit / Risk hard exit remain active during reassessment;
- expected holding period is not an order;
- ADD / MODIFY_EXIT can never become reduce-only orders on the original leg.
