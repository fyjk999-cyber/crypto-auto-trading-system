# LOWRISK — Harness 12h PAPER Diagnostic Monitor (REPORT_ONLY v1)
> SCHEDULE Asia/Shanghai 00:00 and 12:00 every day; `0 0,12 * * *` only with a timezone-aware scheduler. No interval drift.
> KB: `docs/research/standby/lowrisk/MODEL_KB.md` at this exact docs branch/commit. Runtime data and strategy code always read-only.

## Primary mission
At each local clock window [previous boundary, current boundary), identify the currently active Lowrisk PAPER runtime (or record STOPPED, never start it); read-only reconstruct orders, fills, positions, closed episodes, PnL, fees, funding, data quality, factor provenance. Compare 12h/7d/30d and winning/losing/no-fill examples. Decide whether losses are data/accounting, cost, wrong regime, signal quality, correlation/tail, or LLM choice. Recommend **one** primary model hypothesis (+ <=2 alternatives) from `MODEL_KB.md`, or INSUFFICIENT_EVIDENCE.

## Shared Quant Core strategy parity
Read authorized Quant Core observations only as comparative evidence. Match on `strategy_package_hash` / feature version / as-of market snapshot / symbol / exact observation time. Validate same factor and strategy-candidate outcomes if both sides have equivalent inputs. Keep differences in final deterministic-vs-LLM decision separate. Never mix accounts or combine equity/fees/episodes. Inconsistent package versions => PARITY_NOT_COMPARABLE, not Alpha failure. Cross-system read unavailable => NOT_VERIFIED.

## Strict permissions
- Periodic job: READ-ONLY against **all** trading services, code trees, market/history storage and knowledge bases. No changing runtime, strategy, LLM prompts, factors, thresholds, leverage, order state, risk controls, services, Git refs, credentials, databases, or other job schedules.
- FORBID: deploy, push, pull, git checkout/reset/clean, migration, restart, service enable/disable, launchctl mutating commands, placing/cancelling orders, auto-training, backtest or shadow experiments.
- No hard stop/restart even if an alarm indicates losses. Existing risk authority remains unchanged. Do not write remediation tickets that execute actions.
- Only allowed recurring writes: append-new Markdown + JSON report in `~/AI-Monitor-Reports/lowrisk/` (isolated from runtime and histories). If no safe report directory, output message-only with BLOCKED_OUTPUT.
- Do not read or echo API keys; queries via true read-only DB connection; never attach write authorization to scheduler.
- One run per window; no overlap, no catch-up replay if would risk concurrency; durable idempotent report names.

## Evidence procedure
1. State window, source timestamps, Git/run SHA, PAPER flag, account alias, strategy hash, factor hash, decision source, health; distinguish historical facts and present instance.
2. If STOPPED/UNKNOWN, do **not** start anything; report status, allowed historical fact coverage and limitation.
3. Integrity-first: contract units, timestamp point-in-time, rate/fee/funding, database reconciliation and money accounting. If failure => `BLOCKED_DATA`/`BLOCKED_ACCOUNTING`, stop Alpha assertions.
4. Assemble lifecycle signal -> strategy candidate -> LLM proposal -> RiskDecision -> order -> fill -> closed episode. Distinguish unfilled from realized losses, MTM and cashflows.
5. Report 12h and rolling 7/30d; compare up to five loss episodes with up to five profitable episodes; avoid post-hoc selection and duplicated market events.
6. Map only supported explanations to KB L01–L11; every candidate: paper DOI, baseline overlap, exact observables, missing data, future isolated comparison, falsification condition. **Do not run future experiment**.
7. Issue `LOWRISK_MONITOR_RECEIPT` with source SHA, 12h window, integrity status, net accounting, top loss buckets, strategy parity, selected hypothesis, confidence and `NO_ACTION_TAKEN=YES`.

## Scheduling installation / isolation
One-time installation MAY create a monitoring-only schedule and dedicated report folder outside all trading worktrees, never modifying existing runtime/launchd trading labels. On macOS launchd StartCalendarInterval follows system timezone: if Mac timezone is not Beijing, use verified timezone-aware scheduler rather than `TZ` guess; validate next 00:00/12:00 Beijing triggers. If isolated scheduling cannot be proven, do NOT install; report MONITOR_SECURITY_FAIL.

## Acceptance
No trading code/config/runtime/database/strategy or KB modifications; no agent auto-repair; report only. Never infer production readiness or live permission. Research data lookback: recent 3 months fitting; prior 3 months backward stress only; never call it true forward OOS.
