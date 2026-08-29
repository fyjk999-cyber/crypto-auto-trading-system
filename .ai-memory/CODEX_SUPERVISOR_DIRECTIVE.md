# CODEX SUPERVISOR DIRECTIVE

Directive ID: `CS-20260829-064844-P2-EXIT`

Timestamp: 2026-08-29T07:22:30+00:00

Last Supervisor Recheck: 2026-08-29T07:56:00+00:00

Status: ACTIVE — PARTIALLY VERIFIED (Harness resolution claim not accepted; only Codex Supervisor may close after all PASS CONDITIONS are independently verified)

Severity: P2 - runtime correctness and derived evidence integrity

## Detected Regression

The primary position-lifecycle and FactorSnapshot defects are operationally repaired, but the commit does not satisfy all Directive pass conditions. EXIT retry state remains unaware of Risk/Execution outcomes, snapshot persistence failure remains silent, and the quarantined ETH entry has produced derived realized PnL that must also be excluded from clean learning/performance evidence.

## Evidence

- Commit `8d6f505` deployed at 07:18Z; Runtime is PAPER, healthy, and uses real OKX data.
- Eleven due positions closed through 11 reduce-only orders/fills; Risk approved each, no duplicate IDs appeared, reconciliation remains `OK`, and eight not-yet-due positions remain.
- Exit prices are plausible real levels, including ETH `2435.04` and BTC perpetual `77492.15`; no new 100/100.05 fill was created.
- FactorSnapshot persistence is active after restart: 19 new durable rows.
- Independent focused validation passed: Ruff clean, `24 passed, 1 warning`, and commit diff check clean.
- Full-suite evidence reported by Harness: `734 passed` with 2 documented pre-existing live-OKX failures; TEST_STATUS/CHANGELOG/CURRENT_STATE have not yet recorded this run.
- `_exit_in_flight` is still set before `process_signal()` and cleared only after the position disappears. No test proves retry after Risk REJECT or Execution HOLD/REJECT.
- The legacy ETH entry remains immutable and quarantined, but closing it generated `2.33499` USDT realized PnL derived from the fake 100.05 basis.
- Latest independent 30-minute audit: 114 decisions, 114 durable FactorSnapshots with 0 unresolved references, 36/36 successful `live_analysis` calls, 7 PAPER orders/fills at plausible real-market prices, 60 clean reconciliations, zero duplicate IDs and zero ledger imbalance.
- No new code addresses the remaining PASS CONDITIONS. The only current source diff adds `RUNTIME_LOOP_CRASHED` logging in `runtime/supervisor.py`; focused validation is `24 passed, 4 skipped`, Ruff clean.
- The apparent 07:26-07:37 decision stall was a UTC/time-base diagnosis error. Runtime evidence remained healthy; this does not close the result-aware EXIT retry or evidence-integrity requirements.
- `OVERNIGHT_PAPER_STATE.md` still contains stale 05:00 checkpoint, position and realized-PnL fields that conflict with current database truth.

## Affected Runtime Stage

Position lifecycle retry semantics; FactorSnapshot durability diagnostics; trade episode / realized-PnL learning and performance attribution.

## Why It Violates Architecture

No AI-FIRST authority violation is present. The remaining issues can suppress a later safety exit after a temporary reject/hold or allow tainted derived outcomes into learning/performance, violating Runtime correctness and evidence integrity.

## Required Correction

1. Make EXIT in-flight state result-aware. Clear/retry after Risk REJECT, Execution HOLD/REJECT, exception, or a completed call that leaves the position open with no live order. Retain duplicate suppression only for a genuinely outstanding or filled exit.
2. Add focused tests for Risk REJECT then retry and Execution HOLD/REJECT then retry; preserve the no-duplicate filled/outstanding case.
3. Make FactorSnapshot persistence failure visible through durable audit/health/decision evidence. An unresolved snapshot ID must not qualify a fill as a valid AI PAPER lineage.
4. Quarantine the whole historical ETH episode for analytics and learning: entry fill, derived exit fill, realized PnL, trade episode, memory and lesson inputs. Preserve all raw order/fill/ledger/audit facts; do not rewrite or delete them.
5. Ensure quarantine JSON decoding works for SQLite string JSON and PostgreSQL native JSON objects.
6. Update CURRENT_STATE, TEST_STATUS, CHANGELOG, OVERNIGHT_PAPER_STATE/REVIEW and this Directive with exact commit, test and Runtime evidence.

## Do Not Change

- PAPER-only and OKX real public market data
- Chief Trader AI decision authority and legal NO_TRADE/WAIT
- RiskEngine / ExecutionAuthority checks
- Append-only raw order/fill/ledger/audit evidence
- Single canonical engine and ledger
- Remaining positions before their own valid exit conditions

## Files Likely Affected

- `src/crypto_trader/runtime/ai_position_bridge.py`
- `src/crypto_trader/runtime/engine.py`
- `src/crypto_trader/runtime/live_decision_context.py`
- learning/performance episode filters
- `tests/integration/test_exit_lifecycle.py`

## Regression Tests Required

- EXIT Risk REJECT then later retry
- EXIT Execution HOLD/REJECT then later retry
- outstanding/filled EXIT duplicate suppression
- snapshot persistence failure produces durable diagnostics
- unresolved snapshot cannot qualify valid-fill lineage
- tainted entry and all derived episode outcomes excluded from learning/performance
- SQLite and PostgreSQL quarantine payload decoding

## Runtime Validation Required

Continue safe PAPER observation. Verify no post-deployment retry storm, no duplicate orders, remaining positions exit only when due, Live LLM continues on flat symbols, new snapshots resolve, reconciliation stays `OK`, and clean PnL/learning reports exclude the tainted ETH episode.

## Harness May Continue After

Harness may continue PAPER Runtime observation and the corrective work. Do not disable safety gates, force trades, or stop the healthy canonical Runtime solely for documentation.

## PASS CONDITIONS

- Result-aware EXIT retry tests pass
- Snapshot durability failure is observable
- Entire tainted ETH episode is excluded from clean analytics/learning without mutating raw facts
- Runtime remains PAPER/OKX real, reconciliation clean, and duplicate IDs zero
- Project state files record the new commit and validation evidence
- Supervisor independently closes this Directive
