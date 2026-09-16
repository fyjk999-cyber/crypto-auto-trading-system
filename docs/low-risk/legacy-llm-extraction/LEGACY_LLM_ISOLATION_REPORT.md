# Legacy LLM isolation experiment

## Scope and safety

- **Starting SHA:** `115571c`
- **Worktree:** `crypto-legacy-llm-isolation`
- **Execution mode:** test-only PAPER_SYNTHETIC compatibility boot
- **Low-Risk V2 soak:** not started, stopped, configured, or modified
- **Live trading:** disabled

This experiment switches off only the two source-level legacy LLM network
boundaries found in the call graph.  It deliberately does not change
`llm_chief`, its DeepSeek/GLM router, its health probe, its provider settings,
or any Low-Risk V2 position/order/Growth runtime.

## Implemented control

`LEGACY_LLM_ENABLED=false` is read by:

1. `crypto_trader.deepseek.client.DeepSeekClient`
2. `crypto_trader.llm_runtime.executor.LLMExecutor`

At that point both return/record `LLM_DISABLED_BY_CONFIG` before an HTTP client
or injected provider can be reached.  Disabled executor calls always produce:

```json
{"action":"NO_DECISION","reason_codes":["LLM_DISABLED_BY_CONFIG"]}
```

The executor intentionally ignores a caller-provided fallback decision while
disabled, preventing a stale/default BUY or SELL from becoming a new-risk
decision.

## Factual zero-network proof

`LegacyLLMInvocationTracker` has no prompt, response, header, URL, or key
storage.  Its counters are:

```text
LLM_PROVIDER_CALLS
DEEPSEEK_REQUESTS
GLM_REQUESTS
OTHER_LLM_REQUESTS
DISABLED_CALLS
```

Disabled-path tests replace the legacy HTTP client and injected provider with
objects that fail immediately if touched.  The passing tests prove all four
provider/network counters remain zero on the disabled path.

## Compatibility boot result

The official bootstrap was started with:

```text
LEGACY_LLM_ENABLED = false
AUTO_START_RUNTIME = false
PAPER_MODE = PAPER_SYNTHETIC
LIVE_TRADING_ENABLED = false
```

This selects the non-LLM `DummyStrategy` compatibility profile.  It completed
adapter connection, recovery, execution lease acquisition, `/ready`, and
`/health`, then stopped and released its lease cleanly.

| Component | Result without legacy LLM | Evidence |
| --- | --- | --- |
| system boot / persistence | WORKS_WITHOUT_LLM | integration boot test |
| market adapter infrastructure | WORKS_WITHOUT_LLM | adapter health true |
| deterministic risk infrastructure | WORKS_WITHOUT_LLM | bootstrap completed without provider call |
| execution infrastructure / lease | WORKS_WITHOUT_LLM | lease health true |
| recovery | WORKS_WITHOUT_LLM | recovery health true |
| API / health | WORKS_WITHOUT_LLM | `/ready` and `/health` 200 |
| scanner / factual OKX feed | NOT_EXERCISED | this compatibility test deliberately used synthetic PAPER; no soak was touched |
| legacy strategic decision | FAIL_CLOSED | `NO_DECISION`, no provider call |
| Low-Risk V2 core decision | OUT_OF_SCOPE | intentionally unchanged |

## Findings

- There is no source-level production construction of `DeepSeekClient` or
  `LLMExecutor` in `runtime.bootstrap.build_system()`.
- `deepseek.decision_engine.fuse_quant_deepseek()` is a dormant but unsafe
  historical utility: a missing legacy opinion yields `QUANT_ONLY`.  It has no
  source production caller today.  It must be fail-closed before reuse.
- `deepseek.risk_committee.apply_capital_review()` is another dormant utility
  that changes size/leverage when no review exists.  It must not be introduced
  into canonical risk authority.
- No provider-specific imports were found in canonical market, risk,
  execution, portfolio, reconciliation, or persistence domain paths.  The
  existing `llm_chief` boundary is the correct starting point for the proposed
  in-process `CoreDecisionPort` extraction.

## Classification

```text
LEGACY_LLM_DISABLED = YES
LLM_NETWORK_CALLS = 0 (guarded legacy paths)
MARKET_INDEPENDENT = YES (infrastructure boot); factual feed not exercised
SCANNER_INDEPENDENT = NOT_EXERCISED
RISK_INDEPENDENT = YES
EXECUTION_INDEPENDENT = YES
RECOVERY_INDEPENDENT = YES
GROWTH_INDEPENDENT = NOT_EXERCISED
LLM_EXTRACTION_FEASIBILITY = PARTIALLY_EXTRACTABLE
```

The classification is **PARTIALLY_EXTRACTABLE**, rather than fully complete,
because this repository revision has no separately bootable legacy runtime to
exercise against factual market/scanner/Growth services.  The known network
boundaries are isolated; dormant legacy helpers still require a future
fail-closed migration before they can be reintroduced.

See `LLM_CALL_GRAPH.md` for the complete caller classification, target
architecture, hard-coupling findings, and migration sequence.

## Verification

```text
Focused legacy/bootstrap regression: 21 passed
Full backend regression:              863 passed (one pre-existing FastAPI deprecation warning)
Changed-file Ruff:                    PASS
Secret-pattern scan of this change:   PASS
```
