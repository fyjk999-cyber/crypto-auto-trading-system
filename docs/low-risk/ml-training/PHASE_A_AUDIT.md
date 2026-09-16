# PHASE A AUDIT - LOW-RISK V2 ML TRAINING CLOSURE

Status: COMPLETE (audit only; no training DB created, no code changed, no soak touched)
Baseline: 115571c98e352d8507841f69650aeaac374f1055 (branch codex/low-risk-v2-inplace-evolution)
Audit branch: codex/low-risk-v2-ml-closure (new dedicated worktree)
Soak note: the PAPER soak process was observed already shut down gracefully before this task started
("Shutting down ... Finished server process"); it was not restarted or modified by this task.

## 1. Market Scanner (existing - KEEP)

Files: src/crypto_trader/market_data/opportunity/{scanner,universe,eligibility,factors,service,board}.py

- Candidate generation: OR-based; ONE independently TRIGGERED factor nominates a symbol
  (FactorCandidate); multiple triggers merge into richer evidence; never a signal or authority.
- Universe: live OKX /api/v5/public/instruments SWAP list normalized via SymbolMapper; 6h refresh,
  24h max stale, fail-closed UniverseUnavailable; no static fallback.
- Symbol filtering: eligibility.py + dynamic universe.
- Factor triggers: factors.py detectors with TRIGGERED/NOT_TRIGGERED/UNAVAILABLE and per-observation
  facts + observed_at; DETECTOR_VERSION="factors-v1".
- Scoring: FactorCandidate.priority follows the strongest single factor; ranking is review order only.
- Timestamps: observed_at per observation, ScanStats.last_scan_at; cycle via scan_once()/run_forever().
- Rotation: round-robin eligible non-candidates included so factor-blind spots cannot hide.
- API: GET /opportunity/candidates, /opportunity/board, /opportunity/stats (real data).

## 2. Real market data availability

Sources: market_data/okx_public_feed.py, market_data/state.py, exchange/okx.py::get_trades

- OHLCV candles: YES (closed-candle cache; ATR/closes/highs/lows).
- trades stream: YES (get_trades; trades are evidence-only, excluded from core health).
- taker buy/sell: YES; CVD: YES.
- L1 book: YES (bid/ask, qty, spread_bps). L5: YES (imbalance_l5).
- L10: NO - MarketState exposes L5 only (gap; record NULL/quality flag until feed extension).
- microprice: YES; spread: YES; depth: partial (bid_qty/ask_qty/book levels, no USD depth aggregate).
- OI + OI change: YES; funding: YES.
- basis: partial via index-price inputs, no first-class basis_bps.
- relative volume: partial (volume_24h_usd vs cohort_median_turnover_usd).
- trade count / velocity / notional / large trades: YES.
- ATR / realized vol: YES (indicator library + strategy realized_volatility).
- liquidity quality: partial (cohort turnover + spread/depth); liquidity tier is a Phase B ADD.

## 3. ExpertEvidence25 (KEEP/EXTEND)

factors/expert/{models,engine,context,indicators,types}.py: frozen REQUIRED_MODELS (25),
ModelEvidence with direction/score/confidence/family/support/counter/neutral/metrics,
authority=EVIDENCE_ONLY, not_an_order=True; ExpertEvidenceEngine builds all 25 from ExpertInputs;
build_consensus collapses families and preserves strongest support/counter; consensus is never an
order trigger; callers pass evidence into Core LLM context only.

## 4. Growth (KEEP/EXTEND)

- Daily Top10: market_data/opportunity/daily_freeze.py + migration 0027; decision-time first-freeze.
- Outcome labels: outcomes.py horizons 15m/30m/1h/4h/12h/24h, four labels, gross/net bps,
  MFE/MAE, all-in cost input; OpportunityOutcomeRecorder -> opportunity_outcomes (0028).
- Cost basis: AllInCostEstimate (expert types) + evaluate_opportunity all_in_cost_bps.
- Reviews: learning/review_taxonomy.py (7 reviews), growth_persistence.py -> ai_trade_reviews.
- Gaps: +1m/+5m horizons missing; long/short net returns not split; future_high/low and realized
  vol not persisted; labels not NET_EDGE-threshold driven.

## 5. #21 ORDER FLOW ML and #25 META FORECAST (ADAPT)

File factors/expert/models.py: model_21_order_flow_ml (~line 921), meta forecast (~line 1130),
registry MODEL_FUNCS (~1225).

- #21 current: deterministic logistic proxy over cvd_ratio, imbalance_l5, normalized 15m velocity;
  confidence from trade_count; metrics artifact_status=PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED.
- #25 current: confidence-weighted combination of the other 24 evidences; expected move proxy
  4x 15m ATR pct versus costs.total_cost_bps; same provisional status.
- Available inputs for training: ExpertInputs + MarketState + SymbolFacts.
- Authority: EVIDENCE_ONLY / not_an_order; promotion may only change evidence, never
  Core LLM authority, Risk hard safety, or ExecutionAuthority.

## 6. Reusable persistence (KEEP/EXTEND; no second truth source)

alembic head 0028_opportunity_outcomes. Reuse: market_snapshots (raw L1/L2, short retention),
factor_snapshots (per-symbol/timeframe JSON - EXTEND for scanner features), factor_performance /
factor_attribution / factor_decay / factor_catalog, daily_opportunity_top10, opportunity_outcomes,
llm_decisions, risk_decisions, trade_episodes, trade_memory_records, ai_trade_reviews,
ai_market_patterns, audit_events, orders/order_events/fills.

## CURRENT -> ACTION MAP

| CURRENT | ACTION | EXACT INTEGRATION POINT |
|---|---|---|
| Market Scanner cycle | KEEP | OpportunityService.scan_once() |
| candidate/universe/factors | KEEP | scanner.py, universe.py, factors.py |
| MarketState/OKX feed | EXTEND | L10/basis/depth-tier if feed exposes; else NULL + quality flags |
| ExpertEvidence25 | KEEP | ExpertEvidenceEngine; #21/#25 evidence-only |
| #21 proxy | ADAPT | same model id; load versioned artifact, fall back to proxy if absent |
| #25 proxy | ADAPT | same model id; meta model over 01-24 + scanner/regime/cost inputs |
| freezer + outcomes | EXTEND | add +1m/+5m, long/short net returns, future_high/low, realized vol |
| persistence | EXTEND | migrations 0029+: scan snapshot/control sample + artifact metadata; reuse factor_snapshots JSON |
| Growth reliability | EXTEND | aggregate asset x regime x horizon x model x version |
| training store | ADD (derived only) | analytics/training tables or DB; trading truth stays canonical |

## P0/P1

- P0: none from the audit; soak already stopped gracefully and was not touched.
- P1: L10/basis gaps; control sampling and SCAN_SNAPSHOT persistence absent; #21/#25 artifact
  loader/versioning absent.

## Next (Phase B)

Extend scan_once() with a ScanSnapshotCollector persisting SCAN_SNAPSHOT rows (candidate + control
samples, market/25-model/economics/Growth fields) through an additive migration on this branch,
while the scanner's discovery responsibility remains unchanged.
