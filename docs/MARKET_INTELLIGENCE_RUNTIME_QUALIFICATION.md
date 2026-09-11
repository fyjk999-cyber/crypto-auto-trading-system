# Market Intelligence Runtime Qualification

How to reproduce and what the real PAPER runtime actually demonstrated.

```
.venv/bin/python tools/qualify_market_intelligence_v1.py --cycles 2
# report: data/market_intelligence_v1_qualification.json
```

The harness drives the REAL production components (`build_system(...)`) against REAL
public OKX market data and a REAL DeepSeek credential loaded from the macOS keychain via
`scripts/deepseek-keychain.swift`. No order is submitted, no risk/leverage limit is
changed, no gate is bypassed, and no trade is manufactured.

## 1. Real observation run (2 cycles, OKX public)

| Fact | Cycle 1 | Cycle 2 |
|---|---|---|
| `scan_id` | `scan_9b2cb29...` | `scan_de8b318...` |
| snapshot status | `COMPLETE` | `COMPLETE` |
| `discovered_count` (OKX live USDT perpetuals) | 463 | 463 |
| `observable_count` | 463 | 463 |
| `analysis_attempted_count` | 12 | 12 |
| `analysis_ready_count` | 12 | 12 |
| funding batch quality | `VALID` | `VALID` |
| OI broad collection | `{'requested': 463, 'collected': 463}` | `{'requested': 463, 'collected': 463}` |
| OI coverage ratio | 1.0 | 1.0 |
| fair-rotation symbols | 6 | 6 |

Additional observed facts:

* `universe_type = "OKX Live USDT Perpetual Discovery Universe"` (not "all OKX markets").
* **One broad OI request covers the whole universe**: `instType=SWAP` returned
  463/463 USDT perpetual rows
  (ratio 1.0) — the previous 120-symbol rotation is gone.
* `status = COMPLETE` while `analysis_attempted_count`
  (12) is far below the universe:
  intentional bounded coverage is reported as coverage, never as scan failure.
* funding quality histogram over 463 instruments:
  `{'VALID': 463}` — real rates including factual zeros; a provider
  failure would appear as `REQUEST_FAILED`, never `0`.
* snapshot ids are unique per cycle and snapshots are never mutated in place.

## 2. Real ChiefTrader market selection

| Fact | Value |
|---|---|
| `selection_id` | `mkt_sel_7a3f2e19...` |
| `scan_id` | `scan_de8b3189a85...` (matches the snapshot) |
| status | `SUCCESS` |
| selection_state | `SELECT` |
| provider / model | `deepseek` / `deepseek-flash` |
| latency_ms | 1617 |
| input / output tokens | 6336 / 191 |
| pool size | 30 (bounded) |
| directory pages in phase 1 | NONE (duplicate/bounded pages are fetched only on REQUEST_DIRECTORY) |
| selected symbols | `CNPYUSDT`, `BZUSDT`, `EGLDUSDT` |
| persisted to `market_selections` | YES |
| duplicate guard (`scan_id` re-request) | YES — same `selection_id`, no second model call |

Phase 1 no longer preloads directory pages, which cut live input tokens from
~15.2k to 6364 with no evidence removed. Directory data is fetched
only when the ChiefTrader asks: the controlled exploration round's real phase 2
measured 16056 input tokens with the directory result attached.

The model could also have returned `NO_RESEARCH`; that path is exercised deterministically
in `tests/opportunity/test_active_selection_gate3.py::test_chief_can_return_no_research`,
and the schema rejects any directional/order fields with
`error_code = AUTHORITY_LEAK:<path>`.

## 2b. Real ChiefTrader directory exploration (controlled induction)

The phase-1 answer was scripted to `REQUEST_DIRECTORY` (a controlled harness
decision, so the path is safely inducible); **the directory layer and phase 2 are
real**:

| Fact | Value |
|---|---|
| directory query | `{'sort': 'abs_move', 'page': 1}` |
| exploration rounds | 1 (hard cap 1) |
| bounded pages returned | 2 (cap 2, <=25 rows each) |
| final status | `SUCCESS` / `SELECT` |
| symbols discovered via directory | ['RAYUSDT', 'IOSTUSDT', 'ICXUSDT'] |
| provenance | `discovered_via_directory=true` + `directory_page_ref` persisted per symbol |

So the system can answer, from persisted lineage, whether a symbol came from the
initial pool or from the ChiefTrader's own bounded exploration.

## 2c. Research-attention authority (deterministic, production path)

`LiveLLMDecisionStrategy.desired_symbol()` is the canonical production path that
decides which symbol receives autonomous NEW research. The OpportunityBoard in
this run always had a programmatic candidate/rotation symbol available
(`AMDUSDT`), so any returned symbol would prove a
fallback.

```
PROGRAMMATIC_FALLBACK_WHEN_SELECTION_ENABLED = NO
```

| Selection state | `desired_symbol()` | board candidate consumed |
|---|---|---|
| `NO_RESEARCH` | `None` | False |
| `SELECTION_LLM_UNAVAILABLE` | `None` | False |
| `SELECTION_TIMEOUT` | `None` | False |
| `SELECTION_FAILED` | `None` | False |
| `SELECTION_SKIPPED_BUDGET` | `None` | False |
| `SELECTION_DEFERRED` | `None` | False |
| `SELECTION_QUEUE_EXHAUSTED` | `None` | False |

```
NO_RESEARCH_WITH_EXISTING_BOARD_CANDIDATE:
desired_symbol = None

SELECTION_LLM_UNAVAILABLE_WITH_EXISTING_BOARD_CANDIDATE:
desired_symbol = None

SELECTION_QUEUE_EXHAUSTED_WITH_EXISTING_BOARD_CANDIDATE:
desired_symbol = None
```

The board agenda is used only when MarketSelection is disabled
(`selection_service is None`), which is covered separately by the production-path
unit tests in `tests/opportunity/test_research_attention_authority.py`.

## 3. Real research round + lineage

For the first selected symbol the SAME ChiefTrader selected tools and made the final
decision:

```
symbol              = CNPYUSDT (matches the selected research target)
tools selected      = multi_timeframe_history, orderbook, momentum, volatility,
                      liquidity, funding, open_interest, market_regime
evidence items      = 8 (all symbol == CNPYUSDT)
decision action     = WAIT
stored.scan_id      = scan_de8b3189a85...      (== selection.scan_id)
stored.selection_id = mkt_sel_d2e05d52...   (== selection.selection_id)
```

So the factual chain

```
MarketObservationSnapshot -> MarketSelection -> ResearchTarget -> ToolSelection
-> DynamicEvidencePackage -> LLMDecision
```

was reconstructed from real runtime records. No `TradePlan`, `RiskDecision`, order or
fill exists for this decision, because the ChiefTrader chose `WAIT`.

## 4. PAPER trade observation

```
NO_NATURAL_TRADE_OBSERVED
```

The qualification never forces an entry. If a natural PAPER entry occurs it flows through
the unchanged chain `Sizing -> TradePlan -> RiskEngine -> ExecutionAuthority -> PAPER
execution` and its lineage is recorded in `llm_decisions`, `trade_plans` and
`risk_decisions`.

## 5. Position-management isolation evidence

Slow opportunity scan / slow market-selection LLM / slow research tool are simulated in
`tests/opportunity/test_lineage_isolation_gate4.py`, which starts the real `TradingEngine`
and proves `llm-position-reviews` still executes while the other tasks are blocked.

## 6. Real OKX public integration tests

`tests/opportunity/test_real_okx_public_gate5.py` (skipped — never passed — when the
public endpoint is unreachable):

| Test | Fact proven |
|---|---|
| `test_real_okx_batch_funding_contract_returns_rows_not_empty` | `instId=ANY&instType=SWAP` returns hundreds of real funding rows |
| `test_real_okx_insttype_only_funding_request_is_rejected` | the OLD request shape returns a non-zero OKX error code (so it could never yield data) |
| `test_real_okx_discovery_universe_is_usdt_perpetuals` | discovery universe is live USDT-margined SWAP only |
| `test_real_okx_scan_publishes_truthful_immutable_snapshot` | real scan → truthful set counts + `VALID` funding + ESTIMATED turnover labelling |
| `test_real_okx_candles_are_closed_and_contiguous_enough` | OKX returns an in-progress candle; only closed candles feed history |
| `test_real_okx_funding_failure_semantics_are_truthful` | a rejected instrument raises instead of becoming zero funding |

## 7. Observability endpoints to inspect a live runtime

| Endpoint | Purpose |
|---|---|
| `GET /market-intelligence/snapshot` | current snapshot, age, status, market-set counts, data-quality summary, candidates, rotation |
| `GET /market-intelligence/selection` | latest `MarketSelection`, cooldown, pool size |
| `GET /market-intelligence/lineage` | selections + recent ChiefTrader decisions |
| `GET /market-intelligence/directory?page=N` | read-only bounded market directory |
| `GET /market-intelligence/budget` | global LLM budget state + recent operation facts |
| `GET /market-intelligence/symbol/{symbol}` | per-symbol `last_successful_observation_at`, `last_successful_analysis_at`, `last_llm_research_at` |
| `GET /opportunity/board` / `/opportunity/stats` / `/opportunity/candidates` | legacy-compatible evidence views (attempted ≠ success) |

Never exposed: API secrets, raw provider credentials, hidden chain-of-thought.
