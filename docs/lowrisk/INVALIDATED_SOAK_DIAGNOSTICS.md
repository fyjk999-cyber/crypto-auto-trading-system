# Invalidated soak diagnostic engineering (not deployed)

Base: `0697a6da512fb20c570ace40c655705fc4c6cc4d`.
The original 72-hour window remains invalid with zero credit. This branch is
not a new activation candidate and does not implement an RC-A repair.

## RC-A controlled causal reproduction

`tests/integration/test_settlement_generation_repro.py` uses temporary SQLite,
the actual PAPER adapter matching/accounting, OrderManager, TradingEngine fill
settlement callback, ledger, portfolio and ReconciliationService. It seeds a
synthetic fixture LONG 0.6, then fills a synthetic reduce-only SELL 0.3. These
are engineering fixtures, never production trades or lifecycle evidence.

An asyncio.Event barrier holds fill-event delivery after the adapter has
updated its position/account but before the order/ledger callback receives it.
A concurrent real reconciliation observes local 0.6 versus adapter 0.3 and
halts. Before the fill, and after releasing settlement, reconciliation passes.
Twenty iterations reproduce this exact interleaving without timing sleeps.

Red command: set `LOWRISK_REPRO_ASSERT_COHERENT=1` and run iteration `[0]`.
This additional assertion fails on the real in-flight halt after convergence
controls run. Without that flag, the characterization suite asserts that all
20 controlled interleavings exhibit the defect; its PASS does not mean the
production defect has been repaired.

The comparison detector correctly reports unequal snapshots. The coordination
contract permits cross-generation comparisons: adapter matching changes account
state before awaited event delivery, while the independent reconciliation loop
replays the local ledger and then separately reads adapter account/positions.
No shared settlement generation/fence is checked by that path. This reproduces
the historical pattern, not every unrecorded microsecond of that incident.

### Recommended repair design, not implementation

Prefer an explicit account settlement generation/fence. Both submission-driven
fills and later asynchronous fills must mark a generation in flight before
external account state may change. Reconciliation must obtain a coherent
generation or report a bounded pending/unknown observation; it must never
publish healthy evidence from a skipped/mixed snapshot. Completed settlement
must include durable fill/ledger commit and projection refresh before clearing
the generation. Exceptions must retain fail-closed state, not clear it in an
unconditional finally. A real same-generation mismatch must still halt.

Before implementing, enumerate all adapter fill and recovery writers. A lock
covering only `_settle_fill` is insufficient: external mutation precedes that
callback. Holding a lock while waiting for the callback can deadlock a submit
that awaits delivery. A narrowly scoped coordinator is an alternative only if
every reachable writer participates and tests cover late/duplicate/failed fills,
UNKNOWN recovery, no deadlock and no false healthy evidence. Do not use sleeps,
blind retries, higher tolerances or symbol-specific exceptions.

The preserved reconciliation execution gate is intentional conservative safety
(master spec requires keeping it). It unconditionally holds all newly submitted
orders, including reduce/exit. Explicit policy intent for blocking risk-reducing
orders is not independently documented; sustained mismatch may delay necessary
exits. This concern is disclosed, not changed or bypassed here.

## RC-B content-free diagnostic metadata

Historical failed response content/finish reason/parser offsets were not
retained; this branch cannot retroactively identify that incident's syntax or
prove token truncation. Provider/token/prompt/thinking/retry/offline/acceptance
settings are unchanged.

The provider captures only whitelisted response identifiers/status, attempt and
budget, usage, factual finish reason, content hash/length, structural classes
and JSON parser location/message. `length` may support the diagnostic taxonomy
PROVIDER_REPORTED_TRUNCATION; token usage alone never does. Structured validation
captures library error codes and known field paths, excluding inputs, context,
messages and untrusted extra-key names. No prefix, suffix, raw body, prompt or
credential is added to persisted telemetry.

Persistence uses the existing application logging handlers, tagged
`LLM_FAILURE_METADATA` JSON envelopes. This requires no DB migration or new
file writer. Operation diagnostics also expose the per-call failed-attempt
metadata, while the existing response object still has its original transient
text semantics. Schema failures bind a factual generated decision ID. Provider
failures retain their wire request/response IDs if supplied; no fabricated ID.
Collection timestamps are actual collection time, not old fact re-stamping.
Logging failures are isolated from trading/retry decisions. Existing runtime
log routing remains unchanged; actual host persistence must be checked only
in a later separately reviewed deployment phase.

Synthetic offline transport fixtures verify classification, leakage prevention,
retry and router offline behavior. They are not historical RC-B evidence.
No real provider calls, deployment, restart, new qualification or soak occur.
