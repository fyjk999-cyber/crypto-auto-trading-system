# LLM Budget Call Graph & Capacity Audit

Scope: PAPER runtime, single global budget authority (`GlobalLLMBudget`).

Base SHA audited: `a8a61ad5cf3103ea69654a17d57ccc415f411b9c`
(deployed runtime `460553f2d42b8fd650fb1e69b92943c62f31af3f` is an ancestor of it,
and is the build actually running; this document describes that observed reality).

> Audit note: the repository's `fullmarket` worktree HEAD (`1b896fb`) is OLDER
> than the deployed build and does **not** contain the reserve implementation
> (0 hits for `position_management_reserve`). Auditing `fullmarket` would have
> produced a false "the reserve does not exist" conclusion. The authoritative
> tree is the one the runtime process actually runs from.

## 1. Quota authority

One authority only — no per-subsystem budgets exist or were added:

```
GlobalLLMBudget.try_acquire(priority, operation)
      │
      ├── _prune(now)                    expire calls older than window
      ├── ceiling = config.ceiling_for(priority)      (fractional head-room)
      ├── reserve guard: non-position work is capped at min(ceiling, general_pool)
      └── _granted.append(now)           ← the ONLY thing that consumes quota
```

Defaults (unchanged by this work):

```
window_seconds                      = 3600
max_calls_per_window                = 120
position_management_reserve          = 60
general_pool                        = 60
position_review_min_interval_seconds = 60.0
```

Key accounting property: quota counts **granted attempts**. A refused attempt is
*not* appended to `_granted`, and `complete()` / `fail()` do **not** return
capacity. One grant = one provider call's worth of the window.

## 2. Call paths that acquire budget

Exactly four `try_acquire` call sites exist:

| # | Site | Priority | Operation |
|---|---|---|---|
| 1 | `llm_chief/engine.py:97` | per-call | (gate/tool path) |
| 2 | `llm_chief/engine.py:219` | `P1_POSITION_LIFECYCLE` when `position_state != FLAT`, else `P2_FINAL_ENTRY_DECISION` | `trading_decision` |
| 3 | `market_data/opportunity/selection.py:498` | `P4_MARKET_SELECTION` | `market_selection` |
| 4 | `market_data/opportunity/selection.py:718` | research tier | `research` |

Priority tiers:

```
P0_POSITION_SAFETY_EXIT          position safety / exit
P1_POSITION_LIFECYCLE_REVIEW     position lifecycle review
P2_FINAL_ENTRY_DECISION          new-entry directional decision
P3_SELECTED_SYMBOL_RESEARCH      selected-symbol research
P4_MARKET_SELECTION              market selection
P5_BACKGROUND_RESEARCH           background research
```

Runtime event → priority → operation:

```
close/reduce/exit intent     → P0 (when used) / P1 → trading_decision
FLAT symbol evaluation       → P2            → trading_decision
market scanning              → P4            → market_selection
optional research            → P3/P5         → research
```

## 3. Measured consumption (2026-09-12, live PAPER)

```
llm_decisions total            = 470   (02:26 → 09:04 UTC, continuous)
provider/model attribution     = 100% deepseek / deepseek-flash
hourly attempts                = 16, 82, 103, 98, 51, 57, 58
```

Action mix:

```
FAIL_CLOSED 216 · REDUCE 69 · HOLD 55 · EXIT 51 · NO_TRADE 47 · SHORT 14 · LONG 9 · WAIT 9
```

`FAIL_CLOSED` reason breakdown — the key finding:

```
["SKIPPED_BUDGET"]                          212   ← capacity
["TOOL_SELECTION_TIMEOUT"]                    2   ← tool
["INVALID_LLM_OUTPUT"]                        1   ← model
["SKIPPED_BUDGET","ENTRY_BUDGET_EXHAUSTED"]   1   ← capacity (entry pool)
```

`SKIPPED_BUDGET` alone could not answer *"was position management starved, or
merely redundant?"* That ambiguity is exactly what this work removes.

## 4. Waste identified

| Waste class | Cause | Status |
|---|---|---|
| Redundant position reviews | scheduled cadence re-asking an unchanged position | **coalesced** (`position_review_min_interval_seconds`), now *reported* as `REVIEW_COALESCED` |
| Material-change re-arm | every fill/order transition could re-authorise a review | coalesced into the next eligible review (no extra call), now observable |
| Duplicate entry context | same symbol/evidence re-evaluated on tick | fingerprint dedup: **deferred — not implemented in this change** |
| Timeout retries | `provider retries=1` inside a single ticket | does not consume extra quota (single grant) |
| Recovery amplification | recovery scans do not acquire budget | no amplification |

## 5. Protection guarantee

```
general (P2..P5)  ──► capped at min(ceiling, general_pool) = 60
position (P0/P1)  ──► may use its own 60, and cannot be denied by general use
```

Because the reserve is held out of the general pool, exhausting general traffic
**cannot** deny a position review. Verified by deterministic replay (§19).

## 6. Capacity verdict (§20)

Deterministic replay of the observed schedule pressure (470 attempts / 6.6 h,
peaks 80–103/h, one open position under management):

```
position_required_calls_per_hour = 60.0     (scheduled cadence, after coalescing)
observed_total_attempts_per_hour = 170.0
capacity                         = 120/h

position_budget_exhausted = 0        ← position management never starved
entry_budget_exhausted    = 558      ← general work degrades first (by design)
position_review_coverage  = 1.0000
coalesced_calls           = 132      ← calls avoided, not budget spent
```

`BUDGET_120_SUFFICIENT` **for position-management safety**.

Honest caveat: 170 attempts/hour exceeds 120, so general/entry traffic is
throttled under peak load. That is the intended degradation order
(`P5 → P4 → P3 → P2 → P1 → P0`), not a defect. Raising the ceiling is
**not** proposed or applied here; the data above is provided so the decision can
be made on evidence rather than on the 212 opaque skips.
