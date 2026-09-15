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

## Remaining Phase 4 sub-phases

- 4A — Core LLM evidence package: Market + 25 models + News + Growth + account/economics.
- 4B — structured decision contract (SHOULD_TRADE/ACTION incl. ADD/HEDGE/REVERSE/MODIFY_EXIT, capital allocation, Base Exit, exit approach, adverse trigger, thesis invalidation, NEXT_REASSESSMENT, state version).
- 4C — plan versioning + atomic Base Exit replacement; no max holding time default.
- 4D — partial trading + independent hedge legs + lineage.
- 4E — event-driven invocation (dedup, material-information gate, position-aware priority, one active reassessment).
- 4F — NEXT_REASSESSMENT PRICE/TIME/INDICATOR/EVENT AND/OR + priority.
- 4H — Risk L1/L2 adaptation + execution contract validation (≤20x, ≤25% child reject-not-resize) + risk episodes.
- 4I — offline exits; 4J — Fast Profit Protection.

## P0 / P1

- P0: none (router cannot place orders; DeepSeek path unchanged).
- P1: router not yet wired; latency tracker in-process only (not persisted).
