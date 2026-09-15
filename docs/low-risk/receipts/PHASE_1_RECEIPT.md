# PHASE 1 RECEIPT — EVOLVE EXISTING MARKET/DATA PIPELINE

Status: **PASS**
Date: 2026-09-16 (+08:00)

## Identity

| Item | Value |
|---|---|
| BASE_SHA (phase start) | `de5c5f7571fdfc37297101aa3915e786279909ac` (+ PHASE_0 commit `c7e5757`) |
| FINAL_PHASE_SHA | recorded by the commit containing this receipt (see git log) |
| BRANCH | `codex/low-risk-v2-inplace-evolution` |
| WORKTREE | `/Users/huhongjie/Documents/ChatGPT/crypto-low-risk-v2` |
| MIGRATIONS | none added (head remains `0023_opportunity_lineage`) |
| PAPER/LIVE | PAPER only; no runtime started; no live trading enabled |

## Existing modules inspected / reused

- `market_data/okx_public_feed.py::OKXPublicMarketFeed` (`refresh`, `_state`, `_refresh_ticker/_book/_mark/_index/_funding/_oi`, `_update_source_ages`)
- `market_data/state.py::MarketState/SourceStatus/DataHealth` (`overall_health`, `mark_healthy_from_sources`, `invalidate`, `compute_basis`)
- `market_data/orderbook.py::OrderBook` (`apply_snapshot`, `bids/asks` levels)
- `exchange/okx.py::OKXAdapter._public_request` + existing market methods
- `market_data/opportunity/{universe,scanner,factors,eligibility,service,board}.py`
- `runtime/bootstrap.py::build_system` (evidence-only scanner wiring)
- `market_data/new_risk_gate.py::can_add_risk` (new-risk gating on core health; unchanged)

## KEEP / EXTEND / ADAPT / DEPRECATE / ADD

| Action | Component | Detail |
|---|---|---|
| KEEP | `OkxUniverseManager`, `FactorScanner`, `OpportunityBoard`, `RotationScheduler` | full-market discovery/rotation unchanged |
| KEEP | `EligibilityFilter` legacy verdict semantics | all new inputs optional; callers without microstructure keep identical results (regression-tested) |
| KEEP | `MarketState.health/new_risk_allowed` semantics | ticker+orderbook remain execution-critical; unchanged |
| KEEP | closed-candle-only rule (`row[8] == "1"`) | live trades/book are separate observations, never candles |
| KEEP | `new_risk_gate.can_add_risk` | stale/incomplete core data still blocks new risk only |
| EXTEND | `OKXAdapter` | added `get_trades(inst_id, limit)` → `/api/v5/market/trades` (keyless) |
| EXTEND | `MarketState` | taker buy/sell volume, CVD, trade count/notional, large-trade count, window seconds, last trade price, L5/L10 depth, imbalance, microprice, spread bps, `evidence_quality` + degraded reasons; `EVIDENCE_ONLY_SOURCES` excluded from core health |
| EXTEND | `OKXPublicMarketFeed` | `_refresh_trades` (bounded dedup window), bounded LRU multi-symbol cache (`max_cached_symbols`, pinned execution symbol), L5/L10 microstructure derivation |
| EXTEND | `SymbolFacts` | optional factual microstructure/taker-flow fields |
| EXTEND | `OpportunityScannerService` | optional `state_provider` attaches factual state to facts + prefilter inputs; `evidence_quality` recorded per row |
| EXTEND | `EligibilityFilter` | optional `book_spread_bps`, `depth_usd_l5`, `trade_notional_window_usd` with `THIN_BOOK` / `NO_TRADE_ACTIVITY` reasons (engineering defaults, configurable) |
| EXTEND | `runtime/bootstrap.py` | scanner wired to the canonical feed's bounded state cache as evidence provider |
| ADAPT | none | no existing behavior superseded |
| DEPRECATE | none | no removal |
| ADD | `tests/low_risk/test_phase1_market_evidence.py` | 7 new V2 tests |
| ADD (noted, not built) | taker-flow model / CVD evidence model | Phase 2 will consume `MarketState.cvd` via the 25-model layer (no new authority) |

## Files changed

- `src/crypto_trader/exchange/okx.py` (+16)
- `src/crypto_trader/market_data/state.py` (+~95)
- `src/crypto_trader/market_data/okx_public_feed.py` (+~130)
- `src/crypto_trader/market_data/opportunity/factors.py` (SymbolFacts extension)
- `src/crypto_trader/market_data/opportunity/eligibility.py` (optional prefilter inputs)
- `src/crypto_trader/market_data/opportunity/service.py` (state_provider, facts + prefilter wiring)
- `src/crypto_trader/runtime/bootstrap.py` (state_provider wiring)
- `tests/low_risk/test_phase1_market_evidence.py` (new)

No schema/migration changes. No new package, table, service daemon or ledger.

## Backward compatibility

- `MarketState` gains defaulted fields only; `overall_health()` explicitly excludes `EVIDENCE_ONLY_SOURCES = {"trades"}` so a missing trades stream cannot halt execution-critical health (regression test `tests/local_stability/test_market_semantics.py` passes).
- `EligibilityFilter.evaluate` new parameters are keyword-only with `None` defaults → existing callers' verdicts are unchanged (test `test_eligibility_prefilter_is_evidence_only_and_optional`).
- `SymbolFacts` new fields default to `None`/empty → existing factor code unaffected.
- `OpportunityScannerService(state_provider=...)` optional → existing bootstrap/test constructions unchanged.
- `OKXAdapter.get_trades` is additive.
- One canonical source of truth: all facts live on `MarketState` / `SymbolFacts`; no parallel market service or cache.

## Tests and evidence

Focused command (this worktree):

```
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/low_risk -q
→ 7 passed
```

New tests prove:
1. taker buy/sell volume + CVD + trade count/notional + window derived from real OKX payload shapes;
2. duplicate `tradeId`s deduped; trade window bounded (`deque(maxlen)`), repeated refreshes keep only bounded facts;
3. missing trades → `evidence_quality=DEGRADED` + `TRADES_UNAVAILABLE`, `health=HEALTHY`, `new_risk_allowed=True`, trade facts cleared (never fabricated);
4. book failure → `health=UNAVAILABLE`, `new_risk_allowed=False`, `evidence_quality=UNAVAILABLE`;
5. multi-symbol cache bounded + pinned execution symbol retained;
6. prefilter `THIN_BOOK` / `NO_TRADE_ACTIVITY` applied only when facts provided; legacy verdicts unchanged;
7. evidence layer source contains no `ExecutionAuthority`/`OrderManager`/`submit_order`/`process_signal`/`SignalIntent` references.

Regression:

```
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests -q
→ (see FINAL_PHASE evidence below; full suite run for this phase)
```

Ruff: `ruff check` on all changed files → **All checks passed**.

### Real OKX public market smoke (keyless, factual)

Command: `PYTHONPATH=$PWD/src .venv/bin/python /tmp/lr_v2_phase1_live_smoke.py` (2026-09-16 +08:00), BTC-USDT-SWAP:

```
LIVE_SMOKE: OK
health: HEALTHY            evidence_quality: HEALTHY
best_bid: 76952.9          best_ask: 76953
spread_bps: 0.012994...
depth_bid_5: 324.84        depth_ask_5: 882.12   imbalance_l5: -0.4617
microprice: 76952.9269...
taker_buy_volume: 123.00   taker_sell_volume: 199.86   cvd: -76.86
trade_count: 100           trade_notional: 24846083.715   large_trade_count: 10
trades_window_seconds: 3.417
funding_rate: 0.00006504...  open_interest: 2800939.69   basis: -0.00040268...
sources: ticker/orderbook/mark_price/index_price/funding/open_interest/trades = HEALTHY
```

This proves the extended feed speaks the real OKX public API and produces traceable factual evidence; no order path was touched.

## P0 / P1

- P0: none. Existing canonical safety (new-risk gate, authority, lease, reconciliation) untouched.
- P1: trades are fetched only per-symbol for symbols the feed has polled (review/position symbols); broad-universe CVD remains unavailable by design (batch endpoint does not exist) — Phase 2 must treat missing CVD as degraded evidence, not noise. Scanner prefilter uses microstructure only when a factual state exists.

## Next phase

PHASE 2 — evolve factor/analytics into the 25-model expert evidence layer, reusing `factors/calculators/*`, `factors/regime/*`, `opportunity/factors.py`, extending canonical evidence DTOs, preserving raw opposition, and keeping models evidence-only (no order authority).
