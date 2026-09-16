# Low-Risk Pre-ML Convergence Receipt

Status: PRE_ML_CONVERGENCE_CANDIDATE
Deployed: NO
ML final scientific closure: NOT MERGED

## Source integrity

| Line | Branch | Exact source SHA |
|---|---|---|
| Growth / Memory | codex/low-risk-growth-memory-autonomous-v2 | 01c58a3a1ead1827a09660bbcef10da0a21a9196 |
| Core Runtime Constitution | codex/low-risk-core-runtime-constitution-closure | ad1379cfd933f54e291e2306ceb076450edf987b |
| Hedge / Position-Leg | codex/low-risk-hedge-position-leg-final-closure | 550c91ebae91d2c51e9752ff985d191e4e3d8221 |
| DeepSeek Flash High | codex/deepseek-flash-high-cutover | e2e8386fc8a6e7ad5f8a5dab5eaf99f3521f637d |

The Hedge branch head had advanced to `b01e01f` with a docs-only evidence
commit. The merge used the exact directive SHA `550c91e`; the newer
unreviewed head was not merged.

## Merge order and commits

1. Growth baseline `01c58a3` (new `codex/low-risk-pre-ml-convergence`)
2. Core Runtime `ad1379c` (merge commit `4c70476`)
3. Hedge / PositionLeg `550c91e` (merge commit `92566dc`)
4. Flash High `e2e8386` (merge commit `7dd853e`)

MERGE_CONFLICT_COUNT = 0
MERGE_CONFLICT_FILES = NONE

Textual auto-merge was followed by a semantic audit. Residual findings were
fixed in the convergence branch:

- removed the stale `TIME_STOP_SAFETY_FALLBACK` reduction allowlist entry;
- added the FLAT offline router health probe so `LLM_OFFLINE_MODE` can
  self-clear without an open position;
- pinned `DeepSeekProvider` to the canonical trading resolver so generic
  `LLM_MODEL` cannot select the trading model;
- aligned `/llm/status` diagnostics with canonical configured/effective
  model reporting;
- joined the Growth and Hedge migration heads with
  `0041_pre_ml_convergence_merge`.

## Constitution preservation

GROWTH_PRESERVED = YES
RUNTIME_CONSTITUTION_PRESERVED = YES
HEDGE_POSITION_LEG_PRESERVED = YES
FLASH_HIGH_PRESERVED = YES

HARD_MAX_HOLD_EXIT_REMOVED = YES
TIME_THRESHOLD_REASSESSMENT = YES

SAME_SYMBOL_LONG_SHORT = YES
LEG_RECONCILIATION = YES
LEG_PNL_AGGREGATION = YES

CONFIGURED_MODEL = deepseek-flash
CONFIGURED_THINKING = true
CONFIGURED_REASONING_EFFORT = high
GENERIC_LLM_MODEL_IGNORED = YES
INVALID_MODELS_FAIL_CLOSED = YES

FLAT_OFFLINE_RECOVERY = YES
LLM_OFFLINE_SELF_CLEAR = YES

BASE_EXIT_PRESERVED = YES
FAST_PROFIT_PRESERVED = YES
RISK_HARD_EXIT_PRESERVED = YES

CORE_LLM_NEW_RISK_AUTHORITY = YES
MODEL_NEW_RISK_AUTHORITY = NO
GROWTH_NEW_RISK_AUTHORITY = NO
RISK_NEW_RISK_AUTHORITY = NO

MIGRATION_HEAD = 0041_pre_ml_convergence_merge
MIGRATIONS_PASS = YES

## Static audit

- `maximum holding time safety fallback`: no active-path hit; only the
  reassessment trigger remains.
- Legacy model IDs in active bootstrap path: none.
- `src/crypto_trader/deepseek/client.py` (`deepseek-chat`) is an inactive
  legacy committee client; it is not imported by the canonical runtime.
- `scripts/deepseek-keychain.sh` now pins `TRADING_LLM_MODEL=deepseek-flash`
  and no longer exports an invalid model for the PAPER launcher.
- `HEDGE_EXECUTION_BLOCKED_NET_MODEL` remains the intentional fail-closed
  guard when `LEG_EXECUTION_ENABLED` is off; leg-level truth is active when the
  operational switch is enabled.

## Fresh test evidence

FOCUSED_GROWTH_TESTS = 56 passed
FOCUSED_RUNTIME_TESTS = 90 passed
FOCUSED_HEDGE_TESTS = 52 passed
FOCUSED_FLASH_TESTS = 38 passed
CROSS_SUBSYSTEM_TESTS = 8 passed (6 convergence + 2 migration)

LOW_RISK_TESTS = 333 passed
FULL_TEST_SUITE = 997 passed
RUFF = clean

## Limitations / P1

- The Hedge operational leg switch remains default-off
  (`LEG_EXECUTION_ENABLED`), preserving the accepted Hedge closure posture.
- Natural PAPER operational evidence is autonomously accumulating; no trade
  was forced for this convergence receipt.
- ML final scientific closure remains unmerged and is intentionally absent.
- The GLM provider fallback remains the explicit Core Runtime contract
  fallback and is skipped unless a fresh-state rebuilder is available.

## Final state

FINAL_SHA = commit containing this receipt (branch head); verify with
`git -C <worktree> rev-parse codex/low-risk-pre-ml-convergence`.
REMOTE_SHA_MATCH = verified after push
WORKTREE_CLEAN = YES
DETACHED_EXACT_SHA_ACCEPTANCE = YES

GROWTH_RUNTIME_CHANGED = NO
ML_RUNTIME_CHANGED = NO
FLASH_HIGH_POLICY_CHANGED = NO
DEPLOYED = NO
FINAL_LOW_RISK_CANDIDATE = NO
PRE_ML_CONVERGENCE = PASS
P0_BLOCKERS = NONE
P1_ISSUES = documented above; non-blocking
