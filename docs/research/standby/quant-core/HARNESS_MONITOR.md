# QUANT CORE — Harness 12h PAPER Diagnostic Monitor (REPORT_ONLY v1)
> Asia/Shanghai every day 00:00 & 12:00; timezone-aware fixed calendar triggers (not last-run+12h).
> KB: `docs/research/standby/quant-core/MODEL_KB.md` on the pinned docs commit.

## Mission
Monitor the independent, deterministic Quant Core V1 PAPER account with zero write authority over the Quant Core trading process. From a verified running SHA and FACTUAL ledger, analyze why its deterministic strategy did not earn net profit in this 12h window (context: 7d/30d), separating directional error, strategy regime, no-trade, risk reject, fees and fill cost, data staleness, contract units, tail risk and insufficient sample. Report a single most credible model research direction Q01–Q11, with DOI and falsification criteria, or an honest NO_EVIDENCE.

## Shared strategy, independent decisions
Quant Core and Lowrisk must keep one immutable strategy package reference. Read-only compare `strategy_package_hash`, indicator version, market snapshot hash/time, synchronized symbol, candidate IDs and input availability. Expected equal factors/candidates only if hashes and effective inputs are exactly equal. Quant Core deterministic decisions can legitimately differ from Lowrisk LLM decisions. Do not rank systems by unmatched orders, assert model drift from different execution outcomes or combine their PAPER accounts. If Lowrisk is stopped, **never restart it to run parity**; compare only verified time-aligned historical facts or `NOT_COMPARABLE`.

## Per-window steps
1. Discover the actual Quant Core PAPER PID/version/SHA and account alias. Historical design branch and past release commit are not runtime proof.
2. Validate market data read-only from canonical source (SharedMarketHistory) and timestamp provenance; no second feed, writer, service or lease.
3. Reconcile gross/net PnL including fees, funding, slippage, liquidation costs, unrealized MTM, cashflows and missing unknowns. Stop Alpha conclusions if ledger, fee versions or units conflict.
4. Build candidate -> deterministic rule decision -> risk -> order/ack/fill -> episode -> realized net PnL; audit no-fill/reject/UNKNOWN distinct from actual losses.
5. Contrast loss/profit episodes (<=5 each) and 12h/7d/30d; if facts available, compare to Lowrisk same package and as-of snapshot while keeping decision divergence separate.
6. Map to KB Q01–Q11, **no automatic experiment**. Prioritize execution cost and stale data over new Alpha when gross positive but net negative; note OFI needs actual L2 and EVT needs enough tails.
7. Report `QUANT_CORE_MONITOR_RECEIPT`: schedule/window, run SHA, package hash, account, data health, ledger integrity, closed episode sample, PnL/costs, factor parity, decision divergence, root causes, primary candidate ID/DOI, alternative, confidence, `NO_ACTION_TAKEN=YES`.

## Immutable boundaries
- Periodic monitor is truly READ-ONLY for three trading systems, shared strategy, APIs, worktrees, code, config, risk/kill switch, market service, launchd labels, databases, logs and model KB; credentials neither read nor printed.
- No place/cancel/close orders; no restarting stopped processes; no installing new trading authority; no code or parameter modifications; no model retraining/backtesting/Shadow/PAPER experiments. Even if losses severe, only escalate in report.
- Only scheduled report outputs allowed under `~/AI-Monitor-Reports/quant-core/` (unique per window, JSON + Markdown, never overwrite, outside trading directories).
- Isolate schedule/monitor worker from both Lowrisk and Quant Core trading leases and their ownership; one monitor per window, no overlapping jobs.
- One-time monitoring scheduler setup allowed **only if** verified isolated, no modifications to trading launchd services/config. If cannot install securely, fail-closed and report rather than "fix" a runtime.

## Research boundary
Recent three months for designing future experiments, previous three months only reverse-time stress; forward OOS demands future data. No cross-exchange arbitrage. Job may propose experiment design but must not execute it. Models are academically motivated hypotheses, not certified Alpha.
