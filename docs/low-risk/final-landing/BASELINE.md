# FINAL LANDING BASELINE (PHASE 0)

- AUDIT_UTC: 2026-09-17T10:02:00Z
- SPEC_BRANCH: `codex/low-risk-final-landing-spec`
- SPEC_SHA: `d8ca1fd071288558dca237e57db83fa947be4896`
- SPEC_PARENT: `19b97849f0f0aad151e70bcfc9911010ceff34a8`
- LANDING_BRANCH: `codex/low-risk-final-landing`
- LANDING_WORKTREE: `/Users/huhongjie/Documents/ChatGPT/crypto-low-risk-final-landing`
- STARTING_SHA: `d8ca1fd071288558dca237e57db83fa947be4896`
- WORKTREE_CLEAN: YES
- `origin/main`: `784216a926ac2af1431e517efc95ddb1c8e6ace4`
- Remote divergence vs audited integration `19b97849...`: `main-only=192`, `integration-only=345`, `merge_base=889ccc74c45f439830b4c1287032a9191a5e3500`

## Relevant subsystem refs verified

| Ref | SHA |
|---|---|
| `origin/codex/low-risk-final-convergence` | `19b97849f0f0aad151e70bcfc9911010ceff34a8` |
| `origin/codex/low-risk-pre-ml-convergence` | `619cb9b86c3ab508a97aeaaffe7158acd1aff9fb` |
| `origin/codex/low-risk-ml-final-scientific-closure` | `f345cee4250bf60fcc5830b1c58b3c580dab51db` |
| `origin/codex/low-risk-news-external-evidence-final-closure` | `3fe837bbecfb9d718c2fdb3a3c73389096aa5b02` |
| `origin/codex/low-risk-growth-memory-autonomous-v2` | `01c58a3a1ead1827a09660bbcef10da0a21a9196` |
| `origin/codex/low-risk-core-runtime-constitution-closure` | `ad1379cfd933f54e291e2306ceb076450edf987b` |
| `origin/codex/low-risk-hedge-position-leg-final-closure` | `b01e01f714d571a3a7da9b19d88e8f032b69c484` |
| `origin/codex/deepseek-flash-high-cutover` | `e2e8386fc8a6e7ad5f8a5dab5eaf99f3521f637d` |
| `origin/codex/low-risk-provider-durability` | `60e80dd9e3722818559c5a74af6a26455fde9d62` |
| PR #2 | `72e10e63d9860ce87c634d3fbd348040f36eed98` |
| PR #3 | `b3873d015b40916066dc19243e7d005be5ae3f5b` |
| PR #4 | `46c91fc44e63dd72615f4e52b73c2a31336efc77` |
| PR #5 | `9144c9887157c6ef6f1ccd14f538bec1b2ea6e4d` |

## Canonical PAPER runtime

| Item | Fact |
|---|---|
| launchd | `com.lowrisk.paper` |
| PID | `75392` |
| source worktree | `/Users/huhongjie/lowrisk-provider-durability` |
| source HEAD | `d4e4a7f79b00f673328d3ad8ad45a5968ab7c7c1` (local-only pause commit) |
| plist `RUNNING_SHA` | `60e80dd9e3722818559c5a74af6a26455fde9d62` |
| process env `RUNNING_SHA` | `60e80dd9e3722818559c5a74af6a26455fde9d62` |
| actual source-vs-reported SHA | **DRIFT** (source `d4e4a7f`, reported `60e80dd`) |
| mode | `PAPER` |
| `LIVE_TRADING_ENABLED` | `false` |
| DB | `/private/tmp/lr2-soak2/data/crypto_trader.db` |
| DB revision | `0028_opportunity_outcomes` |
| lease | held, owner `engine_run_b7d837b7c4114dffa64c88cc6bef3888`, fence `15` |
| single writer | `true` |
| kill switch | `enabled=false` (expected state) |
| health | overall `OK` |
| scanner / market / risk / reconciliation components | all `ok` in health snapshot |
| latest run | `run_b7d837b7c4114dffa64c88cc6bef3888` |

## LLM pause state

- Current local provider worktree has unmerged commit `d4e4a7f` (`ops: pause low-risk llm calls fail closed`).
- Running process env contains `LLM_CALLS_PAUSED=true`.
- `d4e4a7f` short-circuits `CoreLLMRouter.complete_json` with `_offline_response("LLM_CALLS_PAUSED_BY_CONFIG")`.
- This is **not** part of the landing branch and does not yet satisfy the full zero-call pause contract (direct provider calls, probe suppression, diagnostics, tests).
- `LLM_PAUSE_STATE = UNVERIFIED/PARTIAL` until the canonical Phase 7 pause gate is implemented and secondary-accepted.
- Do not make provider calls while unverified.

## Runtime diagnostics snapshot (no outbound call)

```text
provider = deepseek
model = deepseek-flash
configured = true
reachable = false
provider_state = PROVIDER_UNREACHABLE
effective_provider = core_llm
effective_model = core_llm
last_error = LLM_OFFLINE_MODE
```

## Other services

| Service | PID | SHA | Heartbeat / state |
|---|---:|---|---|
| `com.lowrisk.news` | 14423 | `3fe837b...` | running, `cycles=504`, last progress `2026-09-17T10:01:51Z` |
| `com.lowrisk.growth` | 58247 | `01c58a3...` | `ACCUMULATING`, cycles completed 268, last progress `2026-09-17T10:02:21Z` |
| `com.lowrisk.mlcollector` | 97898 | `f345cee...` | cycles 145, label-v2 total 22920, mature 4950, 1 batch timeout, 25 transient source errors |
| `com.lowrisk.mltrainer` | 98095 | `f345cee...` | `DATA_ACCUMULATING`, coverage `1<3`, no trained models |
| `com.crypto-trader.okx-market-data` | 7717 | n/a | `crypto_trader.market_history.server` on `127.0.0.1:8002` |
| legacy detached PAPER runtime | 93512 | `f14744f...`? (canonical repo) | port `8020`, not canonical owner |

## DB / backup baseline

| DB | Revision | Size |
|---|---|---|
| PAPER `lr2-soak2` | `0028_opportunity_outcomes` | 26,611,712 bytes |
| ML `scan_dataset.db` | `0035_ml_label_v2_alignment` | 116,273,152 bytes |
| Growth `growth.db` | `0040_growth_memory_versions` | 86,368,256 bytes |
| News `news.db` | no `alembic_version` table | 2,199,552 bytes |

Existing backups include ML hotfix / M2-M10 backups under `/Users/huhongjie/lowrisk-ml/data/ml/backups/`, plus News pre-hotfix DB copies.

## Known immediate risks / gaps

1. `RUNTIME_SHA_DRIFT`: running source `d4e4a7f` reports `60e80dd`.
2. `LLM_PAUSE_GATE`: local pause commit is short-circuit only; full canonical gate, diagnostics and zero-call tests absent from landing branch.
3. `MAIN_DIVERGENCE`: 192 main-only commits not yet classified.
4. `OPEN_PR_DISPOSITION`: PR #2-#5 not yet audited/closed.
5. `CHAMPION_PROMOTION`: champion/fingerprint source of truth not yet found.
6. `POSITION_LEG_FRONTEND`: still missing.
7. `FINAL_ACCEPTANCE_HARNESS`: still missing.
8. `CI`: no final landing CI run observed for exact candidate branch.
9. `MIGRATION`: landing base has `0042_final_convergence_merge`; main/PR migration overlays not yet audited.
