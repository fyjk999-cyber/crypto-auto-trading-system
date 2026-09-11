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
| `scan_id` | `scan_ba825d3...` | `scan_32072a0...` |
| snapshot status | `PARTIAL` | `PARTIAL` |
| `discovered_count` (OKX live USDT perpetuals) | 463 | 463 |
| `observable_count` | 463 | 463 |
| `analysis_attempted_count` | 12 | 12 |
| `analysis_ready_count` | 12 | 12 |
| `execution_supported_count` | 245 | 245 |
| funding batch quality | `VALID` | `VALID` |
| OI sampling quality (per instrument) | `VALID` | `VALID` |
| OI symbols sampled this cycle | 120 | 120 (rotated: new symbols first) |
| factor candidates | 8 | 11 |
| fair-rotation symbols | 6 | 6 |

Additional observed facts:

* `universe_type = "OKX Live USDT Perpetual Discovery Universe"` (not "all OKX markets").
* funding quality histogram over 463 instruments: `{"VALID": 463}` — real rates including
  factual zeros; a provider failure would appear as `REQUEST_FAILED`, never `0`.
* several factor candidates were rotation symbols with `"fair rotation"` reasons,
  proving factor-blind markets still receive research exposure.
* snapshot ids are unique per cycle and snapshots are never mutated in place.

`PARTIAL` is correct: the OI sampling is bounded to 120 instruments per cycle, so the
remaining instruments are truthfully reported as `UNSUPPORTED` (not zero, not VALID).

## 2. Real ChiefTrader market selection

| Fact | Value |
|---|---|
| `selection_id` | `mkt_sel_11c46ae5...` |
| `scan_id` | `scan_32072a0b297...` (matches the snapshot) |
| status | `SUCCESS` |
| selection_state | `SELECTED` |
| provider / model | `deepseek` / `deepseek-flash` |
| latency_ms | 2005 |
| input / output tokens | 15201 / 219 |
| pool size | 30 (bounded) |
| directory pages offered | 2 (bounded) |
| selected symbols | `CNPYUSDT`, `ZECUSDT`, `BZUSDT` (3 of 30 pool entries) |
| persisted to `market_selections` | YES |
| duplicate guard (`scan_id` re-request) | YES — same `selection_id`, no second model call |

The model could also have returned `NO_RESEARCH`; that path is exercised deterministically
in `tests/opportunity/test_active_selection_gate3.py::test_chief_can_return_no_research`,
and the schema rejects any directional/order fields with
`error_code = AUTHORITY_LEAK:<path>`.

## 3. Real research round + lineage

For the first selected symbol the SAME ChiefTrader selected tools and made the final
decision:

```
symbol              = CNPYUSDT (matches the selected research target)
tools selected      = multi_timeframe_history, orderbook, momentum, volatility,
                      liquidity, funding, open_interest, market_regime
evidence items      = 8 (all symbol == CNPYUSDT)
decision action     = NO_TRADE
stored.scan_id      = scan_32072a0b297...      (== selection.scan_id)
stored.selection_id = mkt_sel_11c46ae5...   (== selection.selection_id)
```

So the factual chain

```
MarketObservationSnapshot -> MarketSelection -> ResearchTarget -> ToolSelection
-> DynamicEvidencePackage -> LLMDecision
```

was reconstructed from real runtime records. No `TradePlan`, `RiskDecision`, order or
fill exists for this decision, because the ChiefTrader chose `NO_TRADE`.

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
