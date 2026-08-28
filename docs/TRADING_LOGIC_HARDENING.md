# Trading Logic Wiring Hardening — Dominant Strategy / Strategy-Fit Decision Model

- Date: 2026-08-28 (UTC)
- Mode: PAPER ONLY
- Baseline after this change: see `.ai-memory/CURRENT_STATE.md`
- Safety authority untouched: RiskEngine, ExecutionAuthority, Ledger, Kill Switch unchanged.

## 1. Philosophy change

The Live Trading Brain no longer behaves like an all-conditions AND gate. The
canonical flow is now:

```
Market → FactorSnapshot(real) → Market Regime
      → 5 Strategy Candidates (fit scores, supporting/contradicting factors)
      → CryptoTrader-Live selects the DOMINANT strategy
      → evidence-weighted decision (contradictions reduce confidence, never auto-veto)
      → configurable minimum-edge gates
      → SignalIntent → RiskEngine → ExecutionAuthority → PAPER Execution → Ledger → DecisionEvidence
```

## 2. Implementation (reuse, no new brains)

- `src/crypto_trader/llm_chief/strategy_evidence.py` (new): `StrategyCandidate`,
  `StrategyEvidencePackage`, `StrategyEvidenceBuilder`. Runs the FIVE existing
  canonical strategies (`TrendFollowingStrategy`, `MomentumStrategy`,
  `BreakoutStrategy`, `MeanReversionStrategy`, `FundingBasisStrategy`) over real
  candles, classifies regime with the existing `RegimeEngine`, and derives
  deterministic factor attribution from `FeatureSnapshot` truth.
- Existing ensemble weights (trend 40 / momentum 20 / breakout 15 /
  mean_reversion 10 / funding 15) are PRIORS via `REGIME_FIT_MULTIPLIERS`
  (BULL/BEAR/RANGE/HIGH_VOL/EXTREME_RISK), never a weighted-average gate.
  Funding/basis dislocation (|funding+basis| > 0.0005) boosts the FundingBasis
  fit (×1.5) independent of the candle regime.
- `runtime/live_decision_context.py` (new): `LiveDecisionContextProvider`
  fetches real public OKX 1m candles (oldest-first), builds a REAL
  `FactorSnapshotContract` through the canonical `FactorToolGateway`, and
  assembles the package. No synthetic data: fetch failure ⇒ None ⇒ fail closed.
- `ChiefTraderContext` now carries `MarketRegime`, real `FactorSnapshot`
  (snapshot_id + factor_set_version), `StrategyEvidencePackage`, and the running
  `TradingRelease` versions. This replaces regime=UNKNOWN / quant_evidence=[] /
  factor_intelligence={} whenever market data is available.
- `TradingAnalysisResult` extended (structured output, no free text):
  `selected_strategy`, `strategy_fit_score`, `secondary_strategies`,
  `supporting_factors`, `contradicting_factors`, `dominant_factor`,
  `evidence_adjusted_confidence`, `invalidation_conditions`. The live_analysis
  output example anchors the model to the new schema.
- Live prompt rewritten to the required instruction: select the dominant
  strategy; contradictions lower confidence, not automatic veto; NO_TRADE only
  when no strategy has sufficient evidence-adjusted edge.

## 3. Hard gates vs soft evidence

HARD (may block): kill switch, stale/unhealthy market data, RiskEngine limits,
ExecutionAuthority, position-reversal protection, corrupted snapshot, provider
unavailable, exposure limits, plus the two configurable PAPER decision gates
below. SOFT (never a veto): all factor/strategy evidence.

## 4. Configurable PAPER-only decision gates (Settings)

- `live_min_strategy_fit = 0.45` — applies only when a real evidence package
  exists; blocks the LLM call when the BEST regime-adjusted directional fit is
  below noise level, recording an honest `INSUFFICIENT_STRATEGY_EDGE` NO_TRADE.
- `live_min_trade_confidence = 0.55` — when the LLM proposes LONG/SHORT but its
  evidence-adjusted confidence is below coin-flip, the adapter fails closed to
  NO_TRADE with `INSUFFICIENT_EVIDENCE_ADJUSTED_CONFIDENCE`.
- Rationale: conservative thresholds that never require unanimity; never tuned
  to manufacture trades. Evolution may propose changes via the candidate
  pipeline; live values cannot be modified silently.

## 5. Entry mapping (fail closed)

LONG/OPEN_LONG → BUY; SHORT/OPEN_SHORT → SELL; NO_TRADE/WAIT/ADD/REDUCE/EXIT/
HOLD/HEDGE/CLOSE → no signal; anything unrecognized → WAIT (fail closed) and
never an order. Position management remains owned by the runtime bridge; entry
vocabulary is LONG/SHORT/NO_TRADE/WAIT only.

## 6. Lineage & observability

Every Live decision (LLM or gate) persists DecisionEvidence with:
`factor_snapshot_id`, `factor_set_version`, `market_regime`, `selected_strategy`,
`strategy_version`, `llm_invocation_id`, `domain_model_version`, plus the full
candidate table, supporting/contradicting factors, and risk flags. Persistence
is best-effort and instrumented: failures are counted and logged
(`DECISION_EVIDENCE_PERSIST_FAILED`) and never block trading.

Read-only API: `GET /decision-context` (latest real decision context).
Frontend trade panel adds 策略适配（真实证据）: 市场状态 / 主策略 / 适配度 /
主要因子 / 支持 / 冲突 / 决策 / 证据调整置信度 — real values only,
NOT_AVAILABLE when absent.

## 7. Test coverage (§27 scenarios)

`tests/llm_chief/test_strategy_evidence.py`: A (trend dominant + funding
contradiction → LONG stands), B (range → mean reversion selected), C (breakout
without momentum requirement), D (funding dislocation → FundingBasis), E (all
weak → no directional edge), opposite-strong coexistence (F evidence level).
`tests/runtime/test_chief_trader_entry.py`: A through the adapter (BUY despite
contradiction), G (WAIT → no order), H (unknown action → no order),
ADD/REDUCE/EXIT → no entry, E gate blocks pre-LLM with lineage recorded,
low confidence fails closed, context-provider failure falls back to LLM,
persistence failure instrumented, SHORT/OPEN_LONG mapping.

## 8. Live PAPER observation

Restarted canonical stack; `LLM_PROVIDER_RUNTIME_VALIDATED=YES` (6/6). Live
decisions show real lineage (e.g. `fsnap_c65b1bf3…`, factorset-v1), real regime
(RANGE at observation time), five real candidates all NO_TRADE — the
deterministic gate recorded `INSUFFICIENT_STRATEGY_EDGE` honestly:
`NO_NATURAL_ENTRY_YET` is due to genuinely low strategy fit, verified by the
presence of all candidate scores (not missing factors or UNKNOWN regime).
