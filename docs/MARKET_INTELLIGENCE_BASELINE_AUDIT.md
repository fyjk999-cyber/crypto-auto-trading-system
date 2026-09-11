# Baseline Audit — Market Intelligence & Active Research V1

Stage A deliverable (no behavioural change).

## 1. Workspace

| Item | Value |
|---|---|
| `WORKSPACE_PATH` | `/Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-fullmarket` |
| `STARTING_SHA` | `57c3ee3` |
| `CURRENT_BRANCH` | `codex/full-market-factor-layer` |
| `WORKTREE_DIRTY` | YES (pre-existing user work — preserved untouched) |
| Expected reviewed SHA | `df55b11` |
| `BASELINE_DRIFT` | YES — HEAD is one review commit ahead |

## 2. Baseline drift audit (`df55b11..57c3ee3`)

Single commit `57c3ee3 fix(review): complete recovery execution path and memory scope
inheritance`, touching 5 files (+218/-15):

```
src/crypto_trader/llm_chief/context_loader.py
src/crypto_trader/runtime/engine.py
src/crypto_trader/trade_plan/service.py
tests/integration/test_applicability_filtering.py
tests/integration/test_orphan_position_recovery.py
```

It is a valid, independently reviewed recovery/memory-scope fix. It was preserved as-is;
this work was implemented against the actual workspace (`57c3ee3` + user worktree).

## 3. Pre-existing uncommitted work (owned by other tasks — not rewritten)

```
 M .env.example
 M data/paper-runtime.log
 M docs/ai-native-remediation/RUNTIME_ACCEPTANCE_PLAN.md
 M frontend/src/App.test.tsx
 M frontend/src/App.tsx
 M scripts/deepseek-keychain.sh
 M src/crypto_trader/api/app.py          (model-control wiring; my changes are additive)
 M src/crypto_trader/api/deps.py         (model-control wiring; additive)
 M src/crypto_trader/runtime/bootstrap.py(model-control wiring; additive)
?? .ops/
?? data/crypto_trader.db.bak-0911-1547
?? data/crypto_trader.db.pre-0040
?? data/crypto_trader.db.presep8-history
?? migrations/versions/0040_runtime_settings.py   (alembic head — respected)
?? src/crypto_trader/llm_chief/model_control.py
?? tests/llm_chief/test_model_control.py
```

Destructive git operations (`reset --hard`, `clean -fd`, blanket restore, stash/pop) were
never used. New migrations use `down_revision = "0040_runtime_settings"` so the user's
untracked migration stays the parent.

## 4. Dependency / path map for this work

| Concern | Module |
|---|---|
| data-quality contract | `market_data/quality.py` |
| OI time series | `market_data/opportunity/oi.py` |
| snapshots + expiry | `market_data/opportunity/snapshot.py` |
| market sets / fairness clocks / counters | `market_data/opportunity/coverage.py` |
| factor scanner + rotation | `market_data/opportunity/scanner.py` |
| observation loop | `market_data/opportunity/service.py` |
| board / observability | `market_data/opportunity/board.py` |
| research pool | `market_data/opportunity/pool.py` |
| market directory | `market_data/opportunity/directory.py` |
| ChiefTrader selection | `market_data/opportunity/selection.py` |
| selection persistence | `market_data/opportunity/selection_store.py`, `persistence/models.py`, `migrations/versions/0041_market_selection.py` |
| LLM budget | `llm_chief/budget.py` |
| selection phase in the canonical chief | `llm_chief/engine.py` |
| runtime wiring / isolation | `runtime/bootstrap.py`, `runtime/engine.py`, `llm_chief/runtime_strategy.py` |
| observability API | `api/app.py`, `api/deps.py` |

## 5. Defects confirmed at baseline

1. `OKXAdapter.get_funding_rate` batch used `instType` only → live OKX returns HTTP 400 /
   code `50014`; the scanner swallowed it into `[]`, rendering every funding fact missing.
2. `OKXAdapter.get_open_interests` called `/api/v5/public/open-interests` (plural) → live
   OKX returns HTTP 404. No batch OI endpoint exists at all.
3. `_safe_batch` collapsed provider failure into an empty list (failure ≈ missing ≈ 0).
4. Ticker age used `max(0, now - ts)`, so a future timestamp produced age 0 (falsely fresh).
5. `_f()` accepted `NaN`/`Infinity` into ranking, factor strength and liquidity math.
6. `FactorScanner.scan` sorted by `c.triggered[0].strength` (detector declaration order)
   instead of the strongest triggered factor.
7. `_record_oi` compared the "last 8" observations as if inter-call time were constant.
8. Candle `candle_limit` was treated as history coverage; coverage was never measured.
9. Candidate pool had no `scan_id`/expiry binding, and the board was a mutable singleton.
10. `run_forever` was `scan + sleep(interval)`, i.e. cadence = duration + interval, with
    unbounded serial per-symbol candle fetches and no timeout/deadline.
11. There was no ChiefTrader market-selection phase, no market directory, no LLM budget,
    no selection persistence, and `DEEPSEEK_SELECTION` existed only as schema vocabulary.
12. `LLMToolRegistry` treated locally generated fail-closed evidence as "future evidence",
    overwriting the real timeout/error reason.
