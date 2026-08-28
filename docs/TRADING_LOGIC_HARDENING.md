# Trading Logic Wiring Hardening — Dominant Strategy / Strategy-Fit Decision Model

- Date: 2026-08-28 (UTC)
- Mode: PAPER ONLY
- Baseline after this change: see `.ai-memory/CURRENT_STATE.md`
- Safety authority untouched: RiskEngine, ExecutionAuthority, Ledger, Kill Switch unchanged.

## CORE_TRADING_DOCTRINE_V1 (permanent)

因子负责描述市场，策略负责解释机会，LLM 负责选择当前最合适的交易逻辑，RiskEngine 决定能不能执行。

FACTORS DESCRIBE THE MARKET.
STRATEGIES INTERPRET OPPORTUNITIES.
THE LLM SELECTS THE MOST APPROPRIATE TRADING LOGIC.
THE RISK ENGINE DECIDES WHETHER IT MAY BE EXECUTED.

The Live prompt carries this doctrine verbatim (`ChiefTraderEngine.render_prompt`).
Regression contract: `tests/runtime/test_chief_trader_entry.py`
(`test_doctrine_A/D/E/F`, exploration block). The doctrine survives exploration,
Daily Learning, Evolution, strategy contraction and any future real-money stage:
factors never execute, strategies never execute, the LLM only proposes,
RiskEngine always decides.

## PAPER exploration stage (STAGE_A_EXPLORATION)

Purpose (§0/§32): more realistic learning data — more completed trades, more
strategy/regime/factor coverage, honest positive AND negative samples. Explicitly
NOT short-term PAPER-PnL optimization. 多尝试 + 小仓位 + 更多完成交易 + 完整记录
原因 + 接受亏损样本.

Policy (centralized in `Settings`, guarded `enforce_exploration_safety`):
- `PAPER_EXPLORATION_MODE` valid ONLY when TRADING_MODE=PAPER,
  LIVE_TRADING_ENABLED=false, REAL_MONEY_ENABLED=false. Unsafe combos are
  REFUSED at config load (§30 hard lock; runtime property
  `exploration_mode_active` re-derives the truth).
- `exploration_min_fit = 0.40` (pre-LLM evidence gate)
- `exploration_min_confidence = 0.45` (post-LLM gate)
- NORMAL band: fit >= 0.55 AND confidence >= 0.55 -> `NORMAL_ENTRY`;
  otherwise the exploration band -> `EXPLORATION_ENTRY`
- `exploration_borderline_fit = 0.50`: fit 0.40-0.50 is the BORDERLINE band,
  sampled at `exploration_probability = 0.30` BEFORE any LLM spend; skips are
  persisted as counterfactual NO_TRADE with `EXPLORATION_SKIPPED`
- `exploration_size_fraction = 0.5` -> exploration entries use 0.0005 BTC vs
  0.001 BTC normal (§5/§7). Leverage policy unchanged; no extra leverage for
  exploration (§5).
- Decision classes persisted: `NORMAL_ENTRY` / `EXPLORATION_ENTRY` /
  `NO_TRADE` / (`EXPLORATION_SKIPPED` as rejection reason), recorded in
  DecisionEvidence (`decision_class`, `exploration_mode`, position size, entry
  price reference) and in SignalIntent metadata (§4)
- `entry_cooldown_seconds = 240` (~3 min, §6): separate NEW-entry cooldown
  distinct from the ~60s LLM cadence; blocked re-entries persist
  `ENTRY_COOLDOWN_ACTIVE` decisions
- One open position ⇒ entry path yields `POSITION_ALREADY_OPEN` (§6); ADD
  stays with the runtime bridge
- §8 time stop: bridge force-closes positions held longer than
  `exploration_max_holding_seconds` (4h, PAPER exploration only, reduce-only,
  `EXPLORATION_TIME_STOP`) so entries complete into outcome data. It is a
  data-completion guard, not a profit target: 4h respects the strategies'
  1m-bar horizons without manufacturing samples.

## Factor context fail-closed (§2)

A real FactorSnapshot and a real StrategyEvidencePackage are PREREQUISITES for
any Live entry evaluation. When the decision-context provider fails, returns
None (insufficient history), or yields no candidates, the adapter records
`FACTOR_SNAPSHOT_UNAVAILABLE` / `STRATEGY_EVIDENCE_UNAVAILABLE` NO_TRADE
decisions and the Live LLM is NOT invoked. Exploration MUST NEVER mean "trade
without evidence". Position safety (HOLD/ADD/REDUCE/EXIT), RiskEngine,
ExecutionAuthority, reconciliation and the kill switch live entirely outside
this entry path and stay alive.

## Memory -> Live (§1)

`LiveMemoryProvider` (llm_chief/memory_retrieval.py) retrieves bounded,
read-only, relevance-scored memory from the EXISTING canonical stores:
- `learning_lessons` — CONFIRMED lessons (top by confidence/evidence)
- `ai_market_patterns` — patterns for the current regime
- `ai_trade_episodes` — similar episodes (regime+symbol scored, top-5)
- `ai_compressed_experience` — compressed experience rules
Retrieved memory populates `ChiefTraderContext.knowledge` /
`similar_episodes` / `compressed_experience` (LLM prompt) and every
DecisionEvidence row records `memory_refs` + a memory summary so Daily
Learning/Evolution can audit what the brain actually saw. Memory is SOFT
EVIDENCE per the doctrine: retrieval failures are instrumented
(`LIVE_MEMORY_RETRIEVAL_FAILED`) and never block trading; memory has NO veto
path. The first seeded confirmed lesson (`lesson_20260828_funding_crowd`)
documents a real 2026-08-28 runtime observation (funding contradiction
lowering confidence without veto).

Coverage & calibration (§9/§10/§18–§21): `GET /exploration/status` (read-only)
aggregates decision classes, rejection reasons, strategy×regime coverage,
completed-trade outcomes (fills paired per symbol; attribution via
`signal_id` embedded in `client_order_id`), confidence/fit buckets. MAE/MFE are
NOT_AVAILABLE v1 (honest gap). Daily Learning includes the exploration summary
(`DailyReviewScheduler.run_once` → evidence + result) comparing NORMAL vs
EXPLORATION. Stages §22–§27: sample target 200 completed PAPER trades
(guideline, never a reason to bypass quality gates); STAGE_B CALIBRATION and
beyond are Evolution responsibilities via Candidate → Validation → SafePromotion.

Frontend (§29): System page 交易阶段 panel — 交易阶段 / 探索率 / 当前入场门槛 /
当前样本 (n / 200), real values only.

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
