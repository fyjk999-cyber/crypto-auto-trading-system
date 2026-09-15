# PHASE 2 RECEIPT — 25-MODEL EXPERT EVIDENCE LAYER

Status: **PASS**
Date: 2026-09-15T18:09Z (2026-09-16 02:09 +08:00)

## Identity

| Item | Value |
|---|---|
| BASE_SHA | `8c3d410` (phase 1) |
| FINAL_PHASE_SHA | commit containing this receipt |
| BRANCH | `codex/low-risk-v2-inplace-evolution` |
| WORKTREE | `/Users/huhongjie/Documents/ChatGPT/crypto-low-risk-v2` |
| MIGRATIONS | none (head `0023_opportunity_lineage`) |
| PAPER/LIVE | PAPER only; no runtime started; no live trading |

## Existing modules inspected / reused

- `factors/registry.py`, `factors/catalog.py`, `factors/models.py`, `factors/calculators/*` (momentum/trend/volatility/volume/orderflow/funding/open_interest)
- `factors/regime/*`, `factors/anomaly/*`, `factors/analytics.py`
- `market_data/opportunity/factors.py` (`Candle`, `SymbolFacts`, factor families, `validate_no_direction_semantics`)
- `market_data/state.py` (Phase 1 facts: CVD/taker flow/depth/microprice/funding/OI/basis)
- `market_data/okx_public_feed.py` (per-symbol bounded caches)
- `llm_chief/context.py`, `llm_chief/engine.py` (prompt contract), `llm_chief/runtime_strategy.py`, `llm_chief/position_manager.py`, `runtime/bootstrap.py`

## KEEP / EXTEND / ADAPT / DEPRECATE / ADD

| Action | Component | Detail |
|---|---|---|
| KEEP | `factors/calculators/*`, `factors/registry.py`, `factors/catalog.py` | existing math retained as the primitive layer; unchanged callers/tests |
| KEEP | `market_data/opportunity/factors.py` 9 evidence factors | untouched; still evidence-only with `validate_no_direction_semantics()` |
| KEEP | no order authority anywhere in evidence path | static source test enforces no `ExecutionAuthority`/`OrderManager`/`SignalIntent`/`submit_order`/`process_signal`/`TradePlan` references |
| EXTEND | `market_data/okx_public_feed.py` | `get_closed_candles(symbol, bar, limit)` bounded per-(symbol,bar) cache, closed-flag-only rows, OKX bar casing map (`1h`→`1H`, `4h`→`4H`) |
| EXTEND | `llm_chief/context.py` | new optional `model_evidence` field included in `estimate_tokens()` |
| EXTEND | `llm_chief/engine.py` | prompt carries `ExpertEvidence25: {...}` |
| EXTEND | `llm_chief/runtime_strategy.py` | optional `expert_engine`; package attached to Chief context; failure never gates |
| EXTEND | `llm_chief/position_manager.py` | same for OPEN-position reassessment |
| EXTEND | `runtime/bootstrap.py` | wires `ExpertEvidenceEngine` to canonical feed caches (per-TF factual candles + market state) |
| ADAPT | none | no existing behavior superseded |
| DEPRECATE | none | no removal |
| ADD | `factors/expert/` subpackage | `types.py` (contract + 25-model registry), `indicators.py`, `context.py` (inputs, all-in cost, resampling), `models.py` (25 models), `engine.py` (package + consensus) |
| ADD | `tests/low_risk/test_phase2_expert_evidence.py` | 12 new tests |

No new top-level package, service, table or ledger. Everything lives under the existing `crypto_trader.factors` subsystem and uses the existing `Candle` DTO.

## The 25 models (all implemented)

01 EMA Multi-TF · 02 MACD · 03 ADX+DI · 04 RSI Context · 05 Bollinger Regime · 06 VWAP Deviation · 07 ATR/NATR · 08 Volume Breakout · 09 CVD/Taker Flow · 10 Price+OI · 11 SMA Structure · 12 SuperTrend · 13 Stochastic RSI · 14 ROC · 15 CCI · 16 Price Z-Score · 17 Support/Resistance · 18 OBV · 19 MFI · 20 CMF · 21 Order Flow ML · 22 Order Book Imbalance · 23 Funding+Basis · 24 Market Regime · 25 Meta Forecast.

Every output carries: model_id/version/family, timeframes, LONG/SHORT/NEUTRAL/UNAVAILABLE, direction_score, confidence, theory, supporting/counter/neutral evidence, regime compatibility, strategy compatibility, entry/exit/reassessment use, invalidation, data_quality, freshness, sample_size, reliability tier, metrics, unavailable_reason.

Honest labels: models 21 and 25 are `PROVISIONAL_ENGINEERING_PROXY_NOT_TRAINED` (no numpy/xgboost dependency added; Growth must validate/train real artifacts before they can be treated as formal). Reliability tiers are `UNVALIDATED/PROVISIONAL/EMERGING/CANDIDATE/FORMAL_VALIDATION` with `<20 / 20–49 / 50–99 / >=100` initial engineering thresholds (configurable, not law).

## Consensus (recommendation, not authority)

`build_consensus()` produces raw counts, raw score, family-collapsed votes (EMA/SMA/MACD/SuperTrend cannot count as four independent facts), effective independent evidence count, correlation-adjusted score, strongest support, strongest 3 counterarguments (devil's advocate), full raw opposition, regime, data quality, and hard flags `authority="EVIDENCE_ONLY"`, `not_an_order=True`.

## Files changed

- `src/crypto_trader/factors/expert/{__init__,types,indicators,context,models,engine}.py` (new)
- `src/crypto_trader/market_data/okx_public_feed.py`
- `src/crypto_trader/llm_chief/context.py`, `engine.py`, `runtime_strategy.py`, `position_manager.py`
- `src/crypto_trader/runtime/bootstrap.py`
- `tests/low_risk/test_phase2_expert_evidence.py`
- `docs/low-risk/receipts/PHASE_2_RECEIPT.md`

## Backward compatibility

- Existing `factors/*` and `market_data/opportunity/factors.py` semantics unchanged; all prior factor tests pass.
- `ChiefTraderContext.model_evidence` is optional/default `None`; prompt renders `UNAVAILABLE` when absent → existing callers and tests unaffected.
- `ExpertEvidenceEngine` failure returns `None` and never raises into the strategy review (try/except at both call sites) → evidence can never block or change authority.
- `get_closed_candles` is additive; live (`confirm != "1"`) candles are excluded.

## Tests and evidence

Focused:

```
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/low_risk -q
→ 19 passed (7 phase 1 + 12 phase 2)
```

Full regression:

```
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests -q
→ 672 passed, 1 warning in 77.69s   (baseline was 653)
```

Ruff: `/src/crypto_trader/` and `tests/low_risk/` → **All checks passed**.

Phase 2 tests prove: exact 25-model registry; all models evaluate on factual-shaped series with bounded score/confidence; insufficient data → UNAVAILABLE (no fabrication); opposition counts/evidence preserved; 20L/0S/5N differs from 20L/5S/0N; family correlation collapse ≤ 9 families; expensive all-in cost suppresses meta score and emits `EXPECTED_EDGE_BELOW_ALL_IN_COST`; deterministic model output for identical facts; resampling correctness; no order-authority references; prompt carries `ExpertEvidence25`.

### Real OKX public evidence (25/25 live)

`PYTHONPATH=$PWD/src .venv/bin/python /tmp/lr_v2_phase2_live_smoke.py` — BTC-USDT-SWAP, 2026-09-15T18:09Z:

```
LIVE_25: OK
models_total: 25   models_available: 25   models_unavailable: 0
regime: HIGH_VOLATILITY
long: 8   short: 4   neutral: 13
effective_independent_evidence: 4
correlation_adjusted_score: 0.07396
strongest_counterarguments:
  01_EMA_MULTI_TF 15m/1h/4h SHORT votes against the long composite
unavailable: []
authority: EVIDENCE_ONLY    not_an_order: true
```

This is factual: real closed OKX candles per timeframe (1m/5m/15m/1h/4h) plus the real market state (CVD/taker flow/L5 depth/funding/OI/basis). No fake inputs and no order path.

## P0 / P1

- P0: none. No authority path introduced or modified; all existing execution/risk tests remain green.
- P1: models 21/25 are provisional proxies (labelled); reliability scores are unvalidated until Growth supplies outcomes; broad-universe per-symbol multi-TF fetches are bounded by cache TTL (60s) and only run for symbols under review.

## Next phase

PHASE 3 — evolve `ai_decision` fusion/conflict into recommendation-only consensus (30D/90D correlation + opposition), preserving existing callers and proving no direct execution path.
