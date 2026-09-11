# Main-Only Behavior Convergence — F90 → F0

Behavior-first closure of the 192 commits unique to `main` (`784216a926ac2af1431e517efc95ddb1c8e6ace4`) against the approved system base
`59fa21719a0aa80e58a0663499ae59a668345dfc`.

## Final counts

```
MAIN_ONLY_TOTAL = 192
ALREADY_PRESENT_BEHAVIORALLY (A) = 61
SUPERSEDED (B) = 22
DOCS_OR_RUNTIME_EVIDENCE_ONLY (C) = 79
STILL_REQUIRED_AND_PORTED (D) = 0
FORBIDDEN (E) = 30
UNRESOLVED = 0
A + B + C + D + E = 192
```

## Behavior evidence used (focused, on the approved base)

* order/position/reduce-only/reconciliation/ledger/health/bootstrap/market-data:
  `tests/integration/test_ledger.py`, `test_portfolio_reconciliation.py`,
  `test_order_manager.py`, `test_orphan_position_recovery.py`,
  `test_runtime_health_diagnostics.py`, `test_bootstrap.py`,
  `test_live_llm_position_lifecycle.py`, `tests/unit/test_order_state_machine.py`,
  `test_order_state_sync.py`, `test_risk.py`, `test_risk_scale_down.py`,
  `tests/runtime_unit`, `tests/unit/test_market_data.py` → **103 passed**;
* market intelligence / ChiefTrader / perpetual: `tests/opportunity`, `tests/llm_chief`,
  `tests/perpetual_unit` → **223 passed**;
* Growth V2 + system convergence on the frozen candidate: **1215 passed** (full suite).

## Classification rules applied

* **A** — the historical invariant is satisfied by the approved architecture and its tests
  (per-symbol feeds/context, snapshot immutability, evidence persistence, bounded budgets,
  reduce-only/short semantics, ledger-first hydration, scope-correct reconciliation,
  restart-safe order ids, health recovery, truthful volume naming).
* **B** — replaced by a stronger approved design (opportunity gate/top-k ranking, cheap
  scanner, fixed 20/30-symbol universes, round-robin adapter, strategy playbooks,
  strategy-selection UI) — restoring them would violate ChiefTrader-only direction
  authority and the broad-universe discovery architecture.
* **C** — CI/lint/test-stabilisation or runtime-evidence only; no executable semantic value.
* **E** — forbidden architectures (three-brain/evolution/self-modification/hierarchical
  brains) — unchanged from the previous audit.
* **D** — none: no main-only behavior proved missing-and-required on the approved base,
  therefore no code was ported.

## Full matrix (all 192 main-only commits)

| SHA | Date | Class | Family / subsystem | Title |
|---|---|---|---|---|
| `dea4ced9d` | 2026-08-26 | C | documentation | docs: reconcile runtime audit and project memory |
| `b8f723f7e` | 2026-08-26 | A | runtime bootstrap / position review | feat: complete canonical AI runtime bootstrap integration |
| `a85322c76` | 2026-08-26 | C | test/lint stabilisation | test: stabilize canonical runtime integration tests |
| `7707f4e9c` | 2026-08-26 | A | runtime bootstrap / position review | fix: attach AI position bridge to production TradingEngine loop |
| `0fe14bc73` | 2026-08-26 | C | test/lint stabilisation | test: stabilize engine loop integration without background sqlite contention |
| `94a88481a` | 2026-08-26 | A | order/position correctness | fix: short position runtime support and reduce_only preservation |
| `7a5064ca3` | 2026-08-26 | A | order/position correctness | fix: propagate reduce_only to OrderIntent and stabilize tests |
| `62b0bcd1a` | 2026-08-26 | A | order/position correctness | fix: reduce-only risk semantics end-to-end |
| `8a88e2e6b` | 2026-08-26 | A | runtime bootstrap / position review | feat: canonical LLM entry and real AI position context |
| `3b6f3f701` | 2026-08-27 | E | legacy brain/evolution architecture | feat: evolution runtime foundation with UTC review scheduling |
| `2fb9fc8f3` | 2026-08-27 | E | legacy brain/evolution architecture | feat: factor three-brain integration foundation |
| `0a707e94c` | 2026-08-27 | C | test/lint stabilisation | test: skip engine-loop integration tests under CI sqlite contention |
| `eacf03383` | 2026-08-27 | E | legacy brain/evolution architecture | feat: phase 2 live factor evidence SSOT integration |
| `c42d63719` | 2026-08-27 | E | legacy brain/evolution architecture | feat: phase 3 full daily learning brain |
| `3eb4e577a` | 2026-08-27 | E | legacy brain/evolution architecture | feat: durable learning persistence backends |
| `d7d33b416` | 2026-08-27 | C | documentation | docs: add factor architecture audit snapshot |
| `c203781ba` | 2026-08-27 | C | documentation | docs: expand canonical factor three-brain architecture |
| `6c3f8a111` | 2026-08-27 | A | market data / evidence | fix: make factor snapshots deeply immutable |
| `982113767` | 2026-08-27 | A | market data / evidence | test: cover factor snapshot deep immutability |
| `0c7816085` | 2026-08-27 | E | legacy brain/evolution architecture | feat: phase 4 hierarchical weekly monthly yearly learning |
| `4bb92092f` | 2026-08-27 | E | legacy brain/evolution architecture | feat: hierarchical review durable persistence |
| `4bdbc1ec9` | 2026-08-27 | E | legacy brain/evolution architecture | feat: evolution candidate foundation |
| `4d5b75bcd` | 2026-08-27 | E | legacy brain/evolution architecture | feat: phase 6 isolated self-modification and validation pipeline |
| `4fc1c73cd` | 2026-08-27 | E | legacy brain/evolution architecture | feat: phase 7 safe promotion activation rollback |
| `2bf6d5bd4` | 2026-08-27 | C | documentation | docs: phase 8 production readiness audit and soak smoke |
| `403b5b9a6` | 2026-08-27 | C | documentation | docs: phase 8b runtime qualification status and postgres script |
| `70a009be9` | 2026-08-27 | C | documentation | docs: external staging qualification not executed |
| `674a22509` | 2026-08-27 | C | CI/lint evidence only | ci: add postgres runtime qualification workflow and tests |
| `1e846c1f8` | 2026-08-27 | A | migration portability code | fix: alembic env postgres url and migration chain |
| `2e4e3c0d3` | 2026-08-27 | A | migration portability code | fix: use sync postgresql driver for alembic migrations |
| `d80bae58b` | 2026-08-27 | A | migration portability code | fix: postgres boolean default in order contract migration |
| `21165323b` | 2026-08-27 | C | documentation | docs: postgres runtime validation passed in CI |
| `1b7143864` | 2026-08-27 | A | market data / evidence | feat: integrate factor health into snapshot path |
| `dd48540d9` | 2026-08-27 | A | market data / evidence | feat: complete factor profile readiness contract |
| `846bfc17e` | 2026-08-27 | E | legacy brain/evolution architecture | feat: add weekly learning aggregation with monthly/yearly reviews |
| `3581ce019` | 2026-08-27 | C | documentation | test: audit postgres integration test restoration status |
| `a87277704` | 2026-08-27 | E | legacy brain/evolution architecture | feat: add evolution candidate contract foundation |
| `573d20eda` | 2026-08-27 | C | CI/lint evidence only | style: clean pre-existing lint errors in migrations and scripts |
| `007c1013e` | 2026-08-27 | C | documentation | docs: update three-brain learning and evolution architecture |
| `64fbd82e2` | 2026-08-27 | C | documentation | docs: consolidate project memory for three-brain support workstream |
| `8bba513f0` | 2026-08-27 | E | legacy brain/evolution architecture | feat: canonicalization and GLM reconciliation hardening |
| `7cbf2b81d` | 2026-08-27 | E | legacy brain/evolution architecture | feat: final canonicalization hardening chapter 9.5c |
| `af9e393bc` | 2026-08-27 | E | legacy brain/evolution architecture | feat: remove second candidate authority |
| `61de2f9d2` | 2026-08-27 | E | legacy brain/evolution architecture | test: canonical candidate contract pre-flight hardening |
| `8863078ab` | 2026-08-27 | C | documentation | docs: final technical release report and runbook |
| `5b890126b` | 2026-08-27 | C | documentation | docs: post-completion maintenance audit |
| `ce4b709e9` | 2026-08-27 | C | documentation | docs: record execution lock and staging gate |
| `20a4db828` | 2026-08-28 | E | legacy brain/evolution architecture | feat: integrate shared llm runtime for three-brain paper trading |
| `d4f25cab0` | 2026-08-28 | C | documentation | docs: record llm runtime qualification baseline 20a4db8 in project memory |
| `efc25b199` | 2026-08-28 | A | provider boundedness / network hardening | fix: harden llm runtime against fake-ip dns and unbounded entry calls |
| `e5e371129` | 2026-08-28 | A | order/position correctness | fix: risk panel shows honest backend-derived metrics |
| `7b746df09` | 2026-08-28 | A | market data / evidence | feat: persist decision evidence for live llm decisions |
| `1771f3519` | 2026-08-28 | C | documentation | docs: paper smoke test PASS, llm runtime validated, 24h blocked by environment |
| `7e697e218` | 2026-08-28 | B | legacy strategy-selection / exploration UI | feat: strategy-selection decision model for live trading brain (PAPER) |
| `725a58669` | 2026-08-28 | B | legacy strategy-selection / exploration UI | feat: PAPER exploration mode + CORE_TRADING_DOCTRINE_V1 |
| `ebc907f7e` | 2026-08-28 | B | legacy strategy-selection / exploration UI | fix: PAPER exploration final context patch - memory wired + factor fail-closed |
| `8d151433a` | 2026-08-28 | B | round-robin / fixed universe / playbooks | feat: add live crypto strategy playbooks |
| `488cf1c40` | 2026-08-28 | B | round-robin / fixed universe / playbooks | feat: export live crypto playbook strategies |
| `3e8bc6e75` | 2026-08-28 | B | round-robin / fixed universe / playbooks | feat: add live playbooks to strategy evidence builder |
| `f11733a86` | 2026-08-28 | B | round-robin / fixed universe / playbooks | test: cover live strategy evidence playbooks |
| `ce21805a4` | 2026-08-28 | B | round-robin / fixed universe / playbooks | feat: expand canonical universe to 20 crypto symbols |
| `d537762d5` | 2026-08-28 | E | legacy brain/evolution architecture | feat: configure 20-symbol real market universe |
| `2d9ff999f` | 2026-08-28 | A | market data / evidence | feat: isolate real OKX market feeds per symbol |
| `a6e41ed07` | 2026-08-28 | A | market data / evidence | feat: make live decision context symbol-aware |
| `f387b642f` | 2026-08-28 | B | round-robin / fixed universe / playbooks | feat: add round-robin multi-symbol Chief Trader adapter |
| `71360387d` | 2026-08-28 | E | legacy brain/evolution architecture | feat: wire 20-symbol real OKX market scanner |
| `261e4646c` | 2026-08-28 | E | legacy brain/evolution architecture | test: cover 20-symbol real market routing |
| `fa5265ba4` | 2026-08-28 | C | documentation | docs: expose default 20-symbol trading universe |
| `a4ee4a2fd` | 2026-08-28 | C | test/lint stabilisation | fix: log feed shutdown failures for ruff |
| `5a35f87ce` | 2026-08-28 | C | test/lint stabilisation | fix: sort multi-symbol bootstrap imports |
| `5d2181c01` | 2026-08-28 | A | market data / evidence | fix: normalize symbol mapper import block |
| `6355bcfa8` | 2026-08-28 | B | legacy opportunity gate / scanner / candle cache | feat: add cheap multi-symbol opportunity scanner |
| `5a3113ac2` | 2026-08-28 | B | legacy opportunity gate / scanner / candle cache | feat: cache real candles for scanner and chief trader |
| `24833ce54` | 2026-08-28 | B | legacy opportunity gate / scanner / candle cache | feat: gate chief trader behind opportunity ranking |
| `9e0129237` | 2026-08-28 | B | legacy opportunity gate / scanner / candle cache | feat: configure cheap opportunity ranking |
| `85d036d53` | 2026-08-28 | B | legacy opportunity gate / scanner / candle cache | feat: wire top-k opportunity scanner into runtime |
| `2940a1515` | 2026-08-28 | C | documentation | docs: expose opportunity scanner controls |
| `9cd35a142` | 2026-08-28 | B | legacy opportunity gate / scanner / candle cache | test: cover opportunity ranking and candle reuse |
| `43717b8a8` | 2026-08-28 | B | legacy opportunity gate / scanner / candle cache | fix: wrap candle cache expression for ruff |
| `16fd09bcd` | 2026-08-28 | B | opportunity/factor gating | fix: wrap opportunity gate initialization for ruff |
| `7c0f11fa6` | 2026-08-28 | A | frontend/API contract | fix: frontend NO_TRADE / NOT_AVAILABLE semantic normalization |
| `6e02322db` | 2026-08-28 | B | legacy opportunity gate / scanner / candle cache | fix: make opportunity scanner advisory only |
| `5cc3c4459` | 2026-08-28 | E | legacy brain/evolution architecture | feat: add AI-first entry decision policy |
| `f5d388602` | 2026-08-28 | E | legacy brain/evolution architecture | refactor: route multi-symbol runtime through AI-first policy |
| `27c8618f5` | 2026-08-28 | B | legacy opportunity gate / scanner / candle cache | test: make opportunity ranking advisory |
| `30733cd1e` | 2026-08-28 | E | legacy brain/evolution architecture | test: cover AI-first entry policy |
| `68bbbfae6` | 2026-08-28 | E | legacy brain/evolution architecture | feat: add AI-first decision console |
| `57d274347` | 2026-08-28 | E | legacy brain/evolution architecture | style: add AI-first decision console |
| `ad6a6cffd` | 2026-08-28 | E | legacy brain/evolution architecture | feat: mount AI-first decision console |
| `ce1b2028c` | 2026-08-28 | E | legacy brain/evolution architecture | test: cover AI-first frontend console |
| `a6e11237d` | 2026-08-28 | C | CI/lint evidence only | ci: validate trading frontend |
| `38bda573a` | 2026-08-28 | B | legacy strategy-selection / exploration UI | feat: bidirectional PAPER perpetual trading integration |
| `626558bf1` | 2026-08-28 | A | market data / evidence | feat: add advisory technical indicator engine |
| `d9d86d003` | 2026-08-28 | A | market data / evidence | feat: preserve complete OKX ticker state |
| `68a4383bb` | 2026-08-28 | A | market data / evidence | feat: map full OKX market state |
| `8825039c8` | 2026-08-28 | A | market data / evidence | feat: add OKX public history data client |
| `a5614cae5` | 2026-08-28 | A | market data / evidence | feat: use expanded OKX public ticker data |
| `f3e04f599` | 2026-08-28 | A | market data / evidence | feat: feed advisory technical evidence to chief trader |
| `d1d1f84d1` | 2026-08-28 | A | market data / evidence | fix: preserve live decision bundle compatibility |
| `3790ef0c0` | 2026-08-28 | A | market data / evidence | test: cover expanded OKX market evidence |
| `10db3d87d` | 2026-08-28 | A | market data / evidence | test: verify technical evidence reaches AI context |
| `016cf5134` | 2026-08-28 | A | market data / evidence | fix: format advisory technical indicators |
| `90a2ddd3c` | 2026-08-28 | A | market data / evidence | fix: name OKX derivative volume correctly |
| `99255f687` | 2026-08-28 | A | market data / evidence | fix: preserve OKX derivative volume semantics |
| `6f4ec0b27` | 2026-08-28 | A | market data / evidence | fix: map OKX base-currency 24h volume |
| `124e650ab` | 2026-08-28 | A | market data / evidence | feat: expose OKX market intelligence to frontend |
| `b77c9a4ed` | 2026-08-28 | A | frontend/API contract | chore: wire market analysis router |
| `9923404b4` | 2026-08-28 | A | frontend/API contract | chore: retry market analysis router wiring |
| `91c972156` | 2026-08-28 | A | market data / evidence | feat: wire OKX market analysis API |
| `7c8b0a5fa` | 2026-08-28 | A | frontend/API contract | feat: add full OKX market intelligence frontend |
| `3f8059882` | 2026-08-28 | A | frontend/API contract | style: add OKX market intelligence drawer |
| `27dc2261b` | 2026-08-28 | A | frontend/API contract | feat: mount OKX market intelligence frontend |
| `6b83275f7` | 2026-08-28 | A | frontend/API contract | test: cover OKX market intelligence frontend |
| `c87a10e29` | 2026-08-28 | A | frontend/API contract | test: tighten OKX market intelligence assertions |
| `5418a4188` | 2026-08-28 | B | legacy strategy-selection / exploration UI | chore: remove temporary router wiring workflow |
| `96f985065` | 2026-08-29 | E | legacy brain/evolution architecture | fix: restore AI entry authority + funnel observability (AI-FIRST) |
| `75db23b4f` | 2026-08-29 | E | legacy brain/evolution architecture | fix: align render_prompt fallback path with AI-FIRST entry authority |
| `c85f25a42` | 2026-08-29 | A | order/position correctness | fix: paper spot fills must use the real OKX reference price |
| `2f1c527e6` | 2026-08-29 | A | order/position correctness | fix: ledger-first paper exchange hydration (reconciliation halt guard) |
| `11a93bf9d` | 2026-08-29 | A | order/position correctness | fix: pre-authorization orderbook refresh uses the reference market symbol |
| `53c4f5739` | 2026-08-29 | A | order/position correctness | fix: _match_order no longer clobbers refreshed books with synthetic seed |
| `1b83f053b` | 2026-08-29 | A | order/position correctness | fix: futures-aware reconciliation scope (perpetual fills no longer halt) |
| `c432a06ea` | 2026-08-29 | A | order/position correctness | fix: unify ledger spot-scope between paper hydration and reconciliation |
| `af426a1ae` | 2026-08-29 | E | legacy brain/evolution architecture | fix: 10 perpetual duplicate-entry gate in the AI-first decide path |
| `53d46c411` | 2026-08-29 | A | order/position correctness | fix: scope the perpetual duplicate-entry gate to the entry symbol |
| `129317ab3` | 2026-08-29 | C | documentation | docs: PAPER_TRADE_E2E_READY=YES acceptance report + memory update |
| `899ce027f` | 2026-08-29 | C | documentation | docs: record NEW_RUNTIME_BASELINE_SHA |
| `d3589dd89` | 2026-08-29 | A | order/position correctness | fix: log full traceback on exchange-event processing failure |
| `f28e2fe78` | 2026-08-29 | A | order/position correctness | fix: per-process exchange-order-id namespace stops restart collisions |
| `e36d1665b` | 2026-08-29 | C | documentation | docs: record permanent AI-FIRST architecture invariant + live-path audit |
| `7f3fa43b3` | 2026-08-29 | A | order/position correctness | fix: reconcile base-asset balance representation against position scope |
| `ebcff5899` | 2026-08-29 | C | documentation | docs: acceptance report  post-fix autonomous fills (BNB 690.40, DOGE 0.08525) + blockers 9 |
| `41064c5c5` | 2026-08-29 | C | documentation | docs: record final baseline + post-fix autonomous fills |
| `92e46684c` | 2026-08-29 | C | documentation | docs: enter PHASE 2 overnight paper observation mode |
| `9f40a5322` | 2026-08-29 | C | runtime journal / evidence | checkpoint 02:30Z: 2 new clean AI fills (SOL @103.89, ADA @0.2012), health OK, 0 errors |
| `ef2cd428c` | 2026-08-29 | A | order/position correctness | fix: market-data health flag recovers on successful tick-path ingest |
| `7526e3906` | 2026-08-29 | C | runtime journal / evidence | checkpoint 03:15Z: 3 new clean AI fills (LINK/AVAX/APT, real prices); LTC health-flag reco |
| `6dd0876a6` | 2026-08-29 | C | runtime journal / evidence | checkpoint 03:30Z: SUI fill @0.7387 (10 clean AI fills total), health OK, 0 errors |
| `b8b71fd57` | 2026-08-29 | C | runtime journal / evidence | checkpoint 04:00Z: 3 new clean fills (ARB/LTC/NEAR), AI-vs-quant override sample (ARB fit  |
| `a86759d0d` | 2026-08-29 | C | runtime journal / evidence | checkpoint 04:30Z: 3 new clean fills (DOT/BCH/OP), BCH AI-SHORT correctly risk-blocked, 16 |
| `aeeb92dbc` | 2026-08-29 | C | runtime journal / evidence | checkpoint 05:00Z: 2 new clean fills (UNI/TRX), 18 clean AI fills total, health OK |
| `ffcdc698f` | 2026-08-29 | C | runtime journal / evidence | checkpoint 05:30Z: no fills (19/20 symbols position-gated, correct anti-pyramiding); BTC p |
| `a7facc272` | 2026-08-29 | C | runtime journal / evidence | checkpoint 06:00Z: no fills (fully position-gated, correct); BTC perp exit window approach |
| `8d6f50582` | 2026-08-29 | A | order/position correctness | P1: position lifecycle closes through canonical authorities; P2: factor snapshots persiste |
| `88b1b14d9` | 2026-08-29 | C | documentation | supervisor directive RESOLVED: P1 lifecycle + P2 snapshot durability with production runti |
| `91c9c1a29` | 2026-08-29 | C | runtime journal / evidence | checkpoint 07:30Z: P1 exit cycle complete (19->9 positions, real prices, BTC_PERP realized |
| `d1f60c042` | 2026-08-29 | C | runtime journal / evidence | checkpoint 07:54Z: full lifecycle continuous (exits+re-entries+BTC_PERP SHORT re-open); pr |
| `6c5112e27` | 2026-08-29 | C | documentation | lesson: date -u anchoring for time-based diagnosis; supervisor crash logging |
| `ee5f0ab29` | 2026-08-29 | C | runtime journal / evidence | checkpoint 07:56Z (queued 07:30 firing): NEAR exit @1.789, positions 11->10, health OK |
| `5d42a5735` | 2026-08-29 | C | runtime journal / evidence | checkpoint 08:00Z: ETH clean re-entry @2435 (taint replaced by real-price cycle), lifecycl |
| `1faf1bc1f` | 2026-08-29 | C | runtime journal / evidence | checkpoint 08:30Z: continuous cycling (3 exits + 4 AI re-entries, all real prices), 16 LLM |
| `d26e4e8f7` | 2026-08-29 | A | order/position correctness | P2: result-aware EXIT retry + snapshot durability telemetry + full ETH episode quarantine |
| `bb4fa37cb` | 2026-08-29 | B | round-robin / fixed universe / playbooks | Expand PAPER observation universe 20 -> 30 with generic bidirectional paper-perpetual regi |
| `f3098b792` | 2026-08-29 | C | documentation | Docs: P2 closure evidence, lease-loss invariants, 30-symbol expansion deployment |
| `1da8fee3e` | 2026-08-29 | A | order/position correctness | PAPER perp sizing step 1e-5 so exploration-sized legal entries pass precision gate |
| `fef3c33c1` | 2026-08-29 | C | runtime journal / evidence | Checkpoint 10:05Z: lease-loss recovery closed, expansion live, perp sizing-step fix; 2 new |
| `dfb92ec61` | 2026-08-29 | C | runtime journal / evidence | Checkpoint 10:10Z quick re-fire: no delta, all healthy |
| `affbaeac5` | 2026-08-29 | C | runtime journal / evidence | Checkpoint 10:12Z: ADA fill lineage (real price), fit=1.0 saturation watch item; all healt |
| `27756d43e` | 2026-08-29 | C | runtime journal / evidence | Checkpoint 10:30Z: FIRST new-symbol paper-perp fill (ENAUSDT_PERP exploration entry, real  |
| `a5cb80403` | 2026-08-29 | C | runtime journal / evidence | Checkpoint 11:00Z: 3 more new-symbol perp fills incl FIRST perp SHORT (WLDUSDT_PERP); bidi |
| `e2c4c7503` | 2026-08-29 | C | runtime journal / evidence | Checkpoint 11:30Z: bridge 4h time-stop exit closed LINK cycle on exact anniversary (entry- |
| `c1f31b671` | 2026-08-29 | A | order/position correctness | Position read-model repair: per-symbol real marks, backend SPOT PnL, zero-position filter, |
| `a13fda777` | 2026-08-29 | C | documentation | Docs: position read-model repair acceptance evidence |
| `fe82ae1dc` | 2026-08-29 | A | order/position correctness | Order/Fill/PnL observability repair: orders read model with real fees, avg fill price and  |
| `a4903cf88` | 2026-08-29 | C | documentation | Docs: order/fill/PnL observability acceptance evidence |
| `a93da2892` | 2026-08-29 | C | runtime journal / evidence | Checkpoint 13:35Z: backend vanished + safe single-writer restart; 22 real-price fills sinc |
| `6df220918` | 2026-08-29 | A | order/position correctness | Trade episode / learning pipeline repair: canonical closed-trade cycle replay -> AITradeEp |
| `c5dfd0baa` | 2026-08-29 | C | documentation | Ops: backend keepalive scripts (.ops watchdog + cron revive); external SIGTERM sweeps docu |
| `a0e3405e2` | 2026-08-29 | C | runtime journal / evidence | Checkpoint 15:15Z: 15 real-price fills, 44 episodes (learning pipeline live), 2 risk rejec |
| `495392a99` | 2026-08-29 | C | runtime journal / evidence | Checkpoint 15:30Z: TAO/AAVE perp 4h exits auto-episoded (46 total, TIME_STOP), LTC re-entr |
| `24db4d40f` | 2026-08-29 | C | runtime journal / evidence | Checkpoint 15:31Z deep: 16 open positions, FUTURES_RPNL cum -0.503194, episodes 46 all TIM |
| `28c5d1a0c` | 2026-08-30 | A | migration portability code | P0 corrections CS-20260829-132209 + P1/P2 linked: fail-closed manual mutation routes, real |
| `e2315a5f5` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 17:35Z: P0 corrections pushed (28c5d1a); episodes re-derived 52 clean; runtime  |
| `6b21658a4` | 2026-08-30 | A | market data / evidence | PHASE A+B: OKX all-market capability matrix + dynamic instrument registry |
| `b037cc809` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 17:30Z: Phase A+B pushed (6b21658), registry 2029 instruments, Phase G baseline |
| `626d4ee6b` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 17:30Z deep: 7 real-price fills, funnel 145 (4L/1S/140NT natural), episodes 53, |
| `da47b51fd` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 18:00Z deep: 5 real fills (3 perp), funnel 145 (2L/3S/140NT), episodes 54, Phas |
| `2c84d140f` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 18:30Z deep: quiet window (AAVE_PERP exit @123.315 real), funnel 138 (97.1% NT  |
| `45819287e` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 19:00Z deep: ADA round-trip + ONDO_PERP entry (real prices), episodes 55, clean |
| `83cc2f81b` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 19:30Z deep: 7 fills across 7 distinct symbols (all real), episodes 58, Phase G |
| `c8c69c975` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 20:00Z deep: 7 fills/6 symbols incl BTC_PERP real 5-min cycle, episodes 63 (+5) |
| `40bf7309f` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 20:30Z deep: 5 real fills, episodes 65, direction-flip watch (XRP 2nd occurrenc |
| `f2081ee1b` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 21:00Z deep: 4 real fills, episodes 69, direction-flip watch 3rd window (CONTRA |
| `2abee8930` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 21:30Z deep: first CONTRACT (cooldown 240->300 staged, sec.26/48 bounded), 8 re |
| `eaac1baf9` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 22:00Z deep: churn cleared organically, RPNL improved -0.2611, episodes 78, sta |
| `feae09759` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 22:30Z deep: ROLLBACK per pre-declared plan (staged 300 cancelled, baseline 240 |
| `629206372` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 23:00Z deep: 3rd clean window, rollback validated, 5 real fills, episodes 81 |
| `036adfd5d` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 23:30Z deep: 4th clean window, 4h TIME_STOP lifecycle verified (4 cycles), 8 re |
| `eef03980d` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 00:00Z deep: 5th clean window, 7 real fills, episodes 87, steady state |
| `0b55003d7` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 00:30Z deep: 6th clean window, 6 real fills, episodes 90, steady state |
| `bc0f78a96` | 2026-08-30 | C | runtime journal / evidence | Checkpoint 01:00Z deep: TRX 45s-flip churn anomaly -> CONTRACT re-staged (240->300), first |
| `784216a92` | 2026-08-30 | C | runtime journal / evidence | Night journal 2026-08-29: trade/change/strategy journals (151 fills, 94 episodes, 16 calib |
