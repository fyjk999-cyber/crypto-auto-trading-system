# Market Intelligence & Active Research Architecture V1

Status: implemented (PAPER-only). Authority doctrine is unchanged and non-negotiable.

```
FACTOR_REQUIRED_FOR_TRADE = FALSE
FACTOR_DIRECTION_AUTHORITY = NONE
NEW_DIRECTION_DECISION_AUTHORITY = CHIEF_TRADER_ONLY
```

## 1. Authority map (who may do what)

| Component | Authority | May NOT do |
|---|---|---|
| Market Observer (`OpportunityScannerService`) | observation only | choose LONG/SHORT, create SignalIntent/TradePlan, size, approve risk, submit orders |
| Factor Scanner (`FactorScanner`, `factors.py`) | nomination / attention evidence only | emit direction, gate admissibility, rank who may trade |
| ChiefTrader `select_markets()` | research-attention only | emit direction, quantity, leverage, stops, orders |
| ChiefTrader `select_tools()` | evidence selection only | emit direction |
| ChiefTrader `decide()` | the ONLY new-direction authority | bypass RiskEngine or ExecutionAuthority |
| RiskEngine | risk approval authority | — |
| ExecutionAuthority | final execution safety authority | — |

There is no Scout Brain, no second LLM trader, no secondary directional authority and
no strategy vote system. `MarketSelection` for the next research round is produced by
the SAME canonical `ChiefTraderEngine` that later selects tools and makes the final
LONG / SHORT / WAIT / NO_TRADE decision.

## 2. Four independent loops

```
Market Observation Loop    (opportunity-scanner task)
       -> immutable MarketObservationSnapshot (scan_id)
Market Research Selection  (market-selection task)
       -> MarketSelection (0..3 symbols | NO_RESEARCH)
Selected research targets  (entry review, funded by LLM budget P3)
       -> ChiefTrader tool selection -> read-only tools -> DynamicEvidencePackage
Trading Decision Loop      -> ChiefTrader decide() -> Sizing -> TradePlan
       -> RiskEngine -> ExecutionAuthority -> PAPER execution
Position Management Loop   (llm-position-reviews + engine-ticks)
```

Runtime priority is fixed and enforced by scheduling (separate asyncio tasks +
the global LLM budget):

```
POSITION SAFETY / EXIT
  > POSITION LIFECYCLE MANAGEMENT
  > FINAL ENTRY DECISION
  > MARKET RESEARCH
  > MARKET SELECTION
  > BACKGROUND OBSERVATION
```

A slow scan, slow market-selection LLM, slow research tool, or a failed selection
never blocks position review; this is proven by `tests/opportunity/test_lineage_isolation_gate4.py`.

## 3. Market sets (never conflated)

| Set | Meaning |
|---|---|
| `DiscoveryUniverse` | **OKX Live USDT Perpetual Discovery Universe** (live USDT-margined SWAP instruments). Never call this "all OKX markets". |
| `ObservableSet` | identity + basic factual observation usable |
| `AnalysisAttemptedSet` | deep candle/factor analysis was attempted |
| `AnalysisSuccessSet` | candles were returned and parsed |
| `AnalysisReadySet` | enough real, closed, deduplicated, contiguous history exists |
| `ResearchExposedSet` | symbol appeared in a ChiefTrader selection candidate set |
| `ResearchSelectedSet` | ChiefTrader explicitly selected the symbol |
| `ExecutionSupportedSet` | PAPER infrastructure supports the instrument contract |
| `RiskApprovedSet` | RiskEngine approved a specific planned action |
| `ExecutedSet` | a fill was settled |

`ExecutedSet ⊆ RiskApprovedSet ⊆ ExecutionSupportedSet ⊆ ObservableSet ⊆ DiscoveryUniverse`.

Counters are exposed separately by `/opportunity/stats` and
`/market-intelligence/snapshot` (see `docs/MARKET_INTELLIGENCE_RUNTIME_QUALIFICATION.md`).
Attempted analysis is never reported as successful coverage.

## 4. Snapshot lifecycle

1. Each scan cycle allocates a new `scan_id` (`scan_...`).
2. The completed snapshot is frozen: `MarketObservationSnapshot` is a frozen dataclass
   and `OpportunityBoard.publish_snapshot` replaces the *reference*, never mutating the
   previous object.
3. Snapshots carry `status ∈ {COMPLETE, PARTIAL, FAILED}` and factual coverage counts.
4. Snapshot validity window defaults to 180 s (`opportunity_candidate_ttl_seconds`).
5. Candidates bind to their snapshot via `scan_id` / `created_at` / `expires_at`;
   expired candidates stay historically queryable (`board.historical_candidate_for`) but
   are never presented as current opportunities.
6. A FAILED scan publishes its own `scan_id`, zero candidates and an error code. It can
   never make a stale board look current.

## 4b. Execution status vs feature coverage

`status` describes whether the scan executed its designed plan:

| Status | Meaning |
|---|---|
| `COMPLETE` | the designed bounded plan executed successfully (even when a bounded/rotating feature covers < 100% of the universe) |
| `PARTIAL` | an UNEXPECTED provider failure, timeout, missing required component or incomplete execution occurred |
| `FAILED` | the core snapshot could not be truthfully produced |

Feature coverage is tracked separately and never conflated with health:

```
ticker_coverage_count / ticker_coverage_ratio
funding_coverage_count / funding_coverage_ratio
oi_coverage_count / oi_coverage_ratio
analysis_attempted_count / analysis_success_count / analysis_ready_count
```

`status = COMPLETE` with `oi_coverage_ratio < 1` is a valid, truthful state;
`PARTIAL` is never used to describe intentional bounded coverage.

## 5. Selection lifecycle

```
valid fresh snapshot (COMPLETE | PARTIAL, not expired)
  -> bounded research pool (<= 30: <=10 factor, <=10 fair rotation, <=10 active/anomaly,
     then oldest-unresearched fill)
  -> cooldown check (default 300 s)
  -> duplicate guard (one autonomous selection per scan_id, restart-durable)
  -> global LLM budget (P4 — higher priorities are reserved first)
  -> SAME ChiefTrader select_markets()  [phase 1: SELECT | NO_RESEARCH | REQUEST_DIRECTORY]
       if REQUEST_DIRECTORY:
            bounded read-only directory lookup (<=2 pages, <=25 rows/page, P4 budget)
            -> SAME ChiefTrader select_markets()  [phase 2, terminal: SELECT | NO_RESEARCH]
  -> strict schema validation (authority-leak rejection)
  -> MarketSelection persisted (incl. exploration provenance); research queue exposed
```

Empty pools are reported as errors (`EMPTY_RESEARCH_POOL`), never silently as
`NO_RESEARCH`. Statuses: `SUCCESS`, `NO_RESEARCH`, `LLM_UNAVAILABLE`, `INVALID_OUTPUT`,
`STALE_SCAN`, `SKIPPED_BUDGET`, `TIMEOUT`, `FAILED`, `DEFERRED`.

## 5b. Restart durability of scheduling state

Fairness clocks (`last_observed_at`, `last_analysis_at`, `last_llm_research_at`),
the rotation cursor/order, timestamped OI samples and the cycle/overrun counters are
exported to the non-secret `runtime_settings` key `market_intelligence.scanner_state`
(`ScannerStateStore`) and restored at scanner startup. A missing or corrupt value is
ignored (fresh start) and never fails the runtime. No market fact and no authority is
stored there.

## 6. Lineage

```
MarketObservationSnapshot (scan_id)
   -> MarketSelection (selection_id, scan_id)
   -> ResearchTarget (selected symbol, selection_source)
   -> ToolSelection (ChiefTrader-chosen tool names)
   -> DynamicEvidencePackage (symbol-bound)
   -> LLMDecision (llm_decisions.scan_id / selection_id)
   -> TradePlan -> RiskDecision -> Order -> Fill
```

Decisions taken from routine program rotation are recorded with
`selection_id = NULL` and `candidate_source = MARKET_OBSERVER`
("routine program-rotation review; no factor trigger"). No DeepSeek selection record is
ever invented when none exists.

## 7. PAPER-only restrictions

* `PAPER ONLY` — no live trading is enabled by this work.
* Execution scope remains **USDT linear perpetual swaps only**; spot, inverse swaps,
  futures and options are explicitly `NOT_EXECUTABLE` and were not broadened.
* Observation coverage is broader than execution coverage; that is the only asymmetry.
* No risk limit was changed, no leverage limit was raised, no RiskEngine gate lowered,
  no ExecutionAuthority check weakened, no strategy economics changed.
* No fabricated fills, exits, episodes, factor triggers, snapshots or selections exist
  anywhere in this architecture; provider failures are reported as failures.

## 8. Failure semantics

| Failure | Behaviour |
|---|---|
| funding provider fails | `funding_quality = REQUEST_FAILED`, `funding_rate = None` (never 0) |
| valuation of a fact impossible | `quality = MISSING`/`UNSUPPORTED`/`MALFORMED` |
| selection LLM unavailable | `status = LLM_UNAVAILABLE`; observation and position management continue |
| snapshot stale/expired | autonomous selection and research continuation refused |
| research tool timeout | evidence `UNAVAILABLE`; no synthetic substitution |
| scanner partial failure | snapshot `PARTIAL` with factual counts |
| whole scanner failure | snapshot `FAILED` with an error code |
| LLM budget exhausted | `SKIPPED_BUDGET` / `DEFERRED`; never an engine failure |

### Global LLM budget (single authority)

Every model call in the canonical ChiefTrader asks the same `GlobalLLMBudget`:

| Phase | Priority |
|---|---|
| position safety / exit | P0 |
| position lifecycle review | P1 |
| final entry decision (flat) | P2 |
| selected-symbol research / tool selection | P3 |
| market selection | P4 |
| background research | P5 |

Each lower priority keeps a reserved *share* of the rolling window for the levels
above it (P3 15%, P4 30%, P5 45%), so market selection can never starve position
management. Refusal is an explicit `SKIPPED_BUDGET` state (a fail-closed decision
with `SKIPPED_BUDGET` reason code for `decide()`, a skip for `select_markets()` /
`select_tools()`), never an exception. Each granted call records operation,
provider, model, started_at, latency and input/output tokens when  no
secrets are recorded.
