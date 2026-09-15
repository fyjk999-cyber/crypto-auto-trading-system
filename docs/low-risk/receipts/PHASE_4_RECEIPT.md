# PHASE 4 RECEIPT — CORE LLM TRADEPLAN + POSITION MANAGEMENT

Status: **PARTIAL / IN PROGRESS** (4G complete; 4A–4F, 4H–4J pending)
Date: 2026-09-15T18:20Z (2026-09-16 02:20 +08:00)

## Identity

| Item | Value |
|---|---|
| BASE_SHA | `6651b3a` (phase 3) |
| FINAL_PHASE_SHA | updated as sub-chunks commit |
| BRANCH | `codex/low-risk-v2-inplace-evolution` |
| WORKTREE | `/Users/huhongjie/Documents/ChatGPT/crypto-low-risk-v2` |
| MIGRATIONS | none in 4G chunk (head `0023_opportunity_lineage`) |
| PAPER/LIVE | PAPER only; no runtime started |

## 4G — DeepSeek → GLM latest-state → OFFLINE (COMPLETE)

### Existing modules inspected / reused

- `llm_chief/provider.py::LLMProvider` Protocol, `DeepSeekProvider` (retry/JSON/diagnostics)
- `llm_chief/engine.py::ChiefTraderEngine.decide` (caller path; unchanged this chunk)
- `runtime/bootstrap.py` provider construction

### KEEP / EXTEND / ADD

| Action | Component | Detail |
|---|---|---|
| KEEP | `LLMProvider` Protocol + `DeepSeekProvider` behavior | unchanged; router wraps it |
| KEEP | fail-closed JSON semantics | both providers refuse malformed output |
| EXTEND | `LLMResponse` | additive `state_version`, `attempts`, `served_by` (fresh-state binding) |
| ADD | `llm_chief/failover.py` | `GLMProvider` (in `provider.py`), `LLMLatencyTracker`, `OfflineStatus`, `CoreLLMRouter` |
| ADD | `tests/low_risk/test_phase4_llm_failover.py` | 9 tests |

No new top-level package/table/dependency.

### Contract implemented

- DeepSeek call (its own bounded immediate retry) → success returns `served_by=deepseek`.
- On failure, `prompt_rebuilder()` must return **fresh** prompt + `state_version`; GLM then gets one immediate retry.
- If no rebuilder/fresh state: backup is **skipped** (`BACKUP_SKIPPED_NO_FRESH_CONTEXT`) and the router goes offline — stale prompts are never replayed.
- Both providers unavailable → `LLM_OFFLINE_MODE`, `offline_since`, `next_probe_at = now + 300s`, `windows += 1`.
- Inside the window: immediate `LLM_OFFLINE_MODE` without provider calls.
- At T+5m (and each subsequent window): probe again; on success **immediate** recovery (`LLM_RECOVERED`, `next_probe_at=None`) using the fresh state version.
- `LLMLatencyTracker`: mean/p50/p90/p95/p99/max, timeout rate, retry rate, provider success rate (nearest-rank percentiles).
- `GLMProvider`: OpenAI-compatible GLM endpoint (`GLM_API_KEY`/`GLM_BASE_URL`/`GLM_MODEL`), one bounded retry, no key → `NO_API_KEY` fail-closed, never logs secrets.
- Router contains no order authority (static test).

### Tests and evidence

```
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/low_risk -q
→ 35 passed (7 phase1 + 12 phase2 + 7 phase3 + 9 phase4G)
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests -q
→ 688 passed, 1 warning in 74.26s   (phase-3 baseline 679)
```

Ruff `src/` + `tests/` → **All checks passed**.

Deterministic assertions include: primary-success bypasses backup; failover passes `FRESH PROMPT v7` while primary saw `STALE PROMPT v1` and the answer is bound to `state_version=v7`; no-rebuilder → backup skipped and offline; window blocking at T+299s with zero calls; T+300s recovery returns immediately; retry rate/percentile math on 100 known samples; GLM without key fails closed.

### Honest gap

The router is **not yet wired into `runtime/bootstrap.py`**: after a DeepSeek failure the authoritative fresh-state rebuilder must come from the evolved runtime context path (4A/4E), otherwise GLM would be skipped by design. Wiring lands with the 4A/4E integration chunk.

## 4B/4C + 4H hard-contract gate (COMPLETE in this chunk)

### Decision contract (`llm_chief/decision.py`)

Additive fields (defaults keep legacy v1 valid): `plan_contract_version` (1 legacy / 2 V2), `should_trade`
TRADE/WAIT/REJECT, `strategy`, `capital_allocation_pct`, `base_exit` (`BaseExitPlan`), `exit_approach`,
`adverse_trigger`, `thesis_invalidation`, `reassessment_rules`, `next_reassessment` (`NextReassessment`:
PRICE/TIME/INDICATOR/EVENT, AND/OR, NORMAL/HIGH/URGENT), `partial_entry`, `reentry_policy`,
`position_plan_version`, `based_on_state_version`, `expected_edge_bps`, `expected_cost_bps`, `order_contract`.
New `OpenAction` values: ADD/CLOSE/MODIFY_EXIT/HEDGE/REVERSE (existing HOLD/REDUCE/EXIT/FAIL_CLOSED preserved).
V2 validation rejects allocation outside (0,25], leverage outside (0,20], missing Base Exit/thesis,
edge <= cost, malformed NEXT_REASSESSMENT.

### TradePlan versioning

- `trade_plan/service.py` + `persistence/models.py` + migration `0024_trade_plan_v2_contract` (11 additive
  nullable/defaulted columns; head verified on a fresh DB, temp DB removed).
- `create(plan_version>=2)` requires Base Exit + strategy + edge>cost; idempotent conflict detection extended.
- `LiveLLMTradePlanner` passes contract into plan + signal metadata; v1 decisions fabricate nothing.

### ExecutionAuthority hard contract (reject, never resize)

`NewRiskOrderContract` + `AuthorizationContext.order_contract`; rejections: >25% allocation
(`NEW_RISK_CHILD_OVER_25PCT_EQUITY`), >20x (`LEVERAGE_OVER_20X`), missing Base Exit (`BASEEXIT_MISSING`),
missing/invalid allocation or leverage. Legacy callers without contract keep the exact previous verdict.
Removal of the `risk_decision` APPROVE/SCALE_DOWN coupling and Risk L1/L2 adaptation remain pending (4H).

### Tests in this chunk

```
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/low_risk -q
→ 51 passed (7 phase1 + 12 phase2 + 7 phase3 + 9 phase4G + 16 phase4 contract)
```

New tests: V2 boundary accept (25%/20x); rejections (30%, 25x, no Base Exit, empty thesis, edge<=cost);
legacy v1 compatibility; ADD + NEXT_REASSESSMENT AND/OR validation; TradePlan round-trip + idempotency;
planner propagation and no-fabrication for v1; authority reject-not-resize; legacy authority path.

## 4J — Fast Profit Protection (COMPLETE in this chunk)

`risk/fast_profit.py` (deterministic, online or offline):

- Trigger requires ALL THREE: estimated NET profit after unified all-in costs; rapid expansion
  `net_profit_pct >= max(min_net_profit_pct, expansion_atr_multiple * ATR%)`; reversal score >= threshold
  from material evidence.
- Evidence weights: CVD reversal against the leg (1.0), order-book deterioration (0.7), volume climax with
  RVOL (0.5), price rejection (0.8), large opposite trade only when CVD is also against (0.5). A lone large
  trade (0.5) or lone volume climax (0.5) cannot reach the default 0.8 threshold — a single random large
  trade is structurally insufficient.
- Exit fractions: base 25% / strong 50% / severe 100%, configurable; 1..100% bound; severe also on
  expansion_ratio >= 3. Fragment protection: an uneconomic partial is upgraded to a full factual exit when
  the whole leg is meaningful, otherwise no exit (`EXIT_FRAGMENT_UNECONOMIC`).
- LONG/SHORT mirrored; `authority="FAST_PROFIT_PROTECTION"`, `is_new_risk=False`, and
  `requires_llm_reassessment=True` (caller must trigger a fresh Core LLM reassessment afterwards).
- No execution/order imports; this module returns a decision; the canonical exit path remains responsible
  for any order.

Tests: `tests/low_risk/test_phase4_fast_profit.py` — 10 tests (long trigger, short mirror,
not-net-profitable, lone large trade, fast move without reversal, price rejection, fragment economics,
configurable fractions, determinism, no new-risk/execution path).

## 4E/4F/4I — dynamic invocation, NEXT_REASSESSMENT, exit coordination (COMPLETE core)

### 4E `llm_chief/invocation.py`

- `MaterialEvent` with kinds LARGE_TRADE/VOLUME_SURGE/PRICE_VELOCITY/ACTIVITY_SURGE/CVD_REVERSAL/
  ORDERBOOK_DISLOCATION/OI_CHANGE/FUNDING_BASIS_ANOMALY/MAJOR_NEWS/RISK_L1/LLM_REQUESTED_REASSESSMENT.
- Position-aware sensitivity = f(cumulative exposure/equity, leverage, |PnL|, event severity/novelty/urgency);
  priority NORMAL/HIGH/URGENT. Material events with sufficient severity+novelty bypass ordinary dedup.
- Same-zone oscillation (e.g. 104.01/103.99/104.02/103.98) is deduped by a bps zone anchor.
- One active reassessment per leg: a newer material event is queued as the latest pending state and started
  immediately on completion.
- No order authority (static test); it only gates Core-LLM wakeups.

### 4F `llm_chief/reassessment.py`

- Evaluates the V2 `NextReassessment` contract: PRICE (operator-first/bare touch), TIME (absolute ISO or
  `+Ns` relative to anchor), INDICATOR (e.g. `rsi14>=70`), EVENT (kind within lookback).
- AND/OR logic, priority escalation (URGENT > HIGH > NORMAL), malformed conditions reported not crashed.
- `authority="WAKE_LLM_ONLY"`, `is_order=False` — never an order/stop.

### 4I `execution/exit_coordinator.py`

- Priorities 1 Risk hard exit, 2 Offline hard exit, 3 Fast Profit, 4 Active Base Exit, 5 LLM reduce/close,
  6 LLM new risk (recorded only; never reserves reduce capacity).
- Hard invariant `reserved_reduce_qty <= factual_qty` enforced on every submit/fill/cancel path.
- Higher priority preempts only pending/submitted/partial *unfilled reservations*; confirmed fills are never
  clawed back. Full close releases all other reservations. Reduce-side mismatch/invalid quantity rejected.
- `cancel_all(priorities=...)` supports offline cancellation of LLM reduce/new-risk requests.

### Tests in this chunk

```
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/low_risk -q
→ 71 passed (+10 exit coordinator, +10 event invocation)
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests -q
→ 734 passed, 1 warning in 78.48s
```

## 4H — Risk levels + pre-trade coupling adaptation (COMPLETE core)

### `risk/risk_levels.py`

- `RiskLevelConfig` (L1/L2 position-loss and account-drawdown thresholds) explicitly labelled
  `ENGINEERING_CANDIDATE_NOT_FROZEN_STRATEGY_LAW`.
- `PositionRiskEpisode` per leg: `l1_hits`, `l2_hits`, `add_count`, sticky `latched_level`, `forced_close`,
  full history. `record_add()` increments adds without resetting L1/L2 history.
- `PositionRiskMonitor.evaluate()` → L1 warning + LLM reassessment, or L2 forced hard exit (deterministic).
  L2 latches: a favourable recovery never clears a hit episode.
- `escalate_l1_to_force_close()` implements the SPEC rule: L1 + DeepSeek/GLM chain failure → immediate
  forced close, no five-minute wait.
- No sizing/execution authority (static test).

### Pre-trade coupling ADAPT

- `execution/contract.py::derive_execution_terms()`: for V2 entries (plan_version >= 2) the LLM's quantity
  and leverage pass through unchanged; Risk observations are recorded (`scaled_by_risk=False`) but never
  resize. Legacy entries and reduce/close actions keep historical APPROVE/SCALE_DOWN behavior.
- `TradingEngine.process_signal` now uses the derived terms, passes `order_contract` into
  `AuthorizationContext`, and audits `RISK_OBSERVATION_V2_NO_RESIZE` whenever Risk returned SCALE_DOWN on a
  V2 entry without an actual resize.
- `ExecutionAuthority` gate 11: new-risk orders carrying a V2 contract no longer require a pre-trade
  `RiskDecision`; the constitutional contract gate (>25% / >20x / Base Exit) validates them instead. Legacy
  orders without a contract keep the exact previous `RISK_NOT_VALID` behavior.

### Tests and factual evidence

```
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/low_risk -q
→ 79 passed (+8 risk levels, +6 risk-gate adaptation incl. engine integration)
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests -q
→ 748 passed, 1 warning in 76.33s
```

Engine integration proof (`test_engine_v2_entry_is_not_resized_by_risk_and_is_audited`): `RiskEngine`
configured with `max_order_notional=50` returns `SCALE_DOWN` with `approved_quantity=0.4`; the V2 order is
persisted through `OrderManager` with the LLM's factual quantity `1`, `RiskDecisionORM` records the
SCALE_DOWN observation, and `audit_events` contains `RISK_OBSERVATION_V2_NO_RESIZE`.

### OLD BEHAVIOR / NEW BEHAVIOR / WHY SUPERSEDED

- OLD: Risk must APPROVE/SCALE_DOWN before any order; SCALE_DOWN silently shrank quantity and clamped
  leverage. NEW: for V2 contract orders, Risk observation only; execution contract validation rejects
  invalid >25%/>20x orders instead of resizing. WHY: SPEC §4H/ExecutionAuthority migration — Risk is a
  protection layer, not a pre-trade strategy sizing gate; the Core LLM owns size/leverage.
- Legacy tests asserting `RISK_NOT_VALID` without a contract still pass unchanged.

## 4C — atomic Base Exit activation + stale-plan race safety (COMPLETE core)

`execution/base_exit.py`:

- `stage()` adds a versioned exit proposal without touching the active exit; `activate()` atomically replaces it
  and marks the previous version superseded.
- Activation bound to a stale `based_on_state_version` raises `StaleBaseExitError` (`STALE_DECISION`) and the
  old exit stays active. A leg already closed by a factual exit fill cannot be re-activated
  (`already closed`), and `reopen_leg()` starts a new episode for re-entry.
- `evaluate()` returns a due/not-due `BaseExitDecision` (`authority="ACTIVE_BASE_EXIT"`, `is_new_risk=False`,
  size 1..100%). PRICE (`>=`, `<=`, `==`, `>`, `<`, bare touch), TIME (absolute ISO or `+Ns`), and injected
  INDICATOR/EVENT evaluation are supported; without an evaluator those conditions explicitly do not fire.
- `mark_filled()` records the factual fill and latches the leg closed.

Tests (`tests/low_risk/test_phase4_base_exit.py`, 9): staging does not replace; atomic replacement; stale plan
rejected with old exit still active; **Exit V1→V2 race** (V1 fills while V2 is staged → V2 activation rejected
as stale/closed, fresh episode reopens); trigger due/not-due; partial size; time trigger; evaluator injection;
no order authority.

## 4I/4C/4H runtime wiring — deterministic exits execute in the canonical engine

`runtime/exit_controller.py` hosts the already-tested deterministic protections and returns ordered
reduce-only intents: Risk Hard Exit (incl. escalated L1) > Fast Profit > Active Base Exit. Every reduce is
reserved through the canonical `ExitCoordinator` before submission, so
`TotalReduceQty <= CurrentFactualPositionQty` holds across mechanisms.

`TradingEngine` changes:
- new `self.exit_controller = DeterministicExitController()` (single source of truth for deterministic exits);
- `tick()` now scans open positions for deterministic exits BEFORE any LLM position review, converts due
  intents into canonical reduce-only `SignalIntent`s (`strategy_id="live_llm_position"`,
  `deterministic_exit=True`, `exit_authority`, `exit_request_id`, `state_version`), submits them through the
  existing `process_signal` path, and releases the reservation when submission is denied;
- `process_signal` accepts the four deterministic exit authorities for reduce/close while keeping all
  reduce-only/side/quantity/plan-ACTIVE checks; the LLM `latest_position_decision_id` binding is required for
  LLM exits and replaced by the reservation lineage for deterministic exits;
- a `DETERMINISTIC_EXIT_STALE` guard cancels any intent whose `state_version` changed before submission
  (stale decision cannot execute);
- `_settle_fill` consumes the reservation with the factual fill quantity.

### Factual engine evidence (`test_engine_executes_active_base_exit_without_llm`)

Real canonical path, no LLM position manager wired: V2 entry decision -> `LiveLLMTradePlanner` -> TradePlan
-> `process_signal` -> PAPER fill -> ACTIVE plan -> `tick()` -> deterministic Base Exit reduce order
(`exit_authority=ACTIVE_BASE_EXIT`, `reduce_only=True`) -> PAPER fill -> factual position 0; coordinator
snapshot `invariant_holds=True`, `reserved_reduce_qty=0`; orders persisted with the plan lineage.

Additional controller tests: Risk L2 outranks an already-due Base Exit and returns 100%; L1 returns a
wake-LLM intent with quantity 0; duplicate evaluate with no capacity returns nothing (reservation cap
enforced); SHORT exits use BUY.

Full regression for this chunk: pytest tests -q -> **762 passed**, 1 warning in 75.18s.

## Offline mode runtime guard (SPEC OFFLINE RULE)

`runtime/offline.py` (`OfflineMode`): five-minute windows (T+5m, T+10m, ...), probe
due/`probe_failed`, new-risk classification (OPEN/ENTRY/ADD/HEDGE/REVERSE/RE_ENTRY and any
`strategy_id=live_llm` entry) vs protective (reduce_only / REDUCE / EXIT / CLOSE / BASE_EXIT /
FAST_PROFIT_PROTECTION / RISK_HARD_EXIT / OFFLINE_HARD_EXIT), pending-new-risk order filtering, and
recovery that only completes when factual reconciliation is coherent (`reconciled=True`); otherwise it
stays offline and schedules the next window.

`TradingEngine` wiring:
- `offline_mode` guard in `process_signal`: an entry while offline is rejected + audited
  (`OFFLINE_NEW_RISK_BLOCKED`), so no OPEN/ADD/HEDGE/REVERSE/RE-ENTRY can execute;
- `enter_offline_mode(reason)`: audits `LLM_OFFLINE_MODE`, cancels pending new-risk orders through the
  canonical `OrderManager`/adapter, then reconciles via `RecoveryService`;
- `attempt_offline_recovery()`: runs factual reconciliation first and only then returns to NORMAL
  (`LLM_RECOVERED_NORMAL`);
- `tick()` syncs engine state from `llm_router.offline` (when wired), skips entry strategies while offline,
  and still runs deterministic protective exits in the position scan.

Bootstrap now constructs `CoreLLMRouter(primary=DeepSeekProvider(), backup=GLMProvider if GLM_API_KEY)`
and passes it as the Chief provider and engine `llm_router`; until a fresh-state prompt rebuilder is wired
(Phase 4A), GLM is deliberately skipped instead of replaying a stale prompt and the router fails safe into
OFFLINE.

Test evidence (`tests/low_risk/test_phase4_offline_mode.py`, 6):
- offline blocks new risk, allows every protective authority, idempotent enter;
- pending-new-risk filter excludes protective orders;
- 299s not due / 300s due / failed probe extends to T+600s and windows=2;
- recovery requires reconciliation: mismatch keeps OFFLINE and schedules next window; coherent recovery
  returns NORMAL;
- engine: with a factual PAPER position, entering offline blocks a new entry (audited) yet the Active Base
  Exit still closes the position through the canonical path;
- engine syncs OFFLINE/NORMAL from the router and updates `llm_offline_mode` health.

## Remaining Phase 4 sub-phases

- 4A — Core LLM evidence package: Market + 25 models + News + Growth + account/economics.
- 4B — structured decision contract (SHOULD_TRADE/ACTION incl. ADD/HEDGE/REVERSE/MODIFY_EXIT, capital allocation, Base Exit, exit approach, adverse trigger, thesis invalidation, NEXT_REASSESSMENT, state version).
- 4C — plan versioning + atomic Base Exit replacement; no max holding time default.
- 4D — partial trading + independent hedge legs + lineage.
- 4E — event-driven invocation (dedup, material-information gate, position-aware priority, one active reassessment).
- 4F — NEXT_REASSESSMENT PRICE/TIME/INDICATOR/EVENT AND/OR + priority.
- 4H — Risk L1/L2 adaptation + execution contract validation (≤20x, ≤25% child reject-not-resize) + risk episodes.

## P0 / P1

- P0: none (router cannot place orders; DeepSeek path unchanged).
- P1: router not yet wired; latency tracker in-process only (not persisted).

## L1 wake bypass (COMPLETE, commit 26d480c)

Risk L1 is a material event:  bypasses the ordinary review
cooldown, and  passes  from the deterministic exit scan (wake intents
marked ). Test  proves the immediate
reassessment and the unchanged ordinary cadence. Chunk regression: 89 passed (spac/lifecycle/bootstrap/
llm_chief/chaos/e2e); low_risk focused 13 passed.
