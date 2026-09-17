# MAIN DIVERGENCE AUDIT

- BASE: `19b97849f0f0aad151e70bcfc9911010ceff34a8`
- MAIN: `784216a926ac2af1431e517efc95ddb1c8e6ace4` (origin/main)
- MERGE_BASE: `889ccc74c45f439830b4c1287032a9191a5e3500`
- MAIN_ONLY_COMMITS: 192
- CLASSIFICATION_METHOD: subject/path heuristic; REQUIRED_* and CONFLICTING rows require semantic comparison before landing.

| # | SHA | Subject | Preliminary classification | Changed files |
|---:|---|---|---|---:|
| 1 | `dea4ced` | docs: reconcile runtime audit and project memory | REQUIRED_DOC/EVIDENCE | 1 |
| 2 | `b8f723f` | feat: complete canonical AI runtime bootstrap integration | SUPERSEDED | 13 |
| 3 | `a85322c` | test: stabilize canonical runtime integration tests | SUPERSEDED | 1 |
| 4 | `7707f4e` | fix: attach AI position bridge to production TradingEngine loop | CONFLICTING_REQUIRES_DECISION | 9 |
| 5 | `0fe14bc` | test: stabilize engine loop integration without background sqlite contention | SUPERSEDED | 1 |
| 6 | `94a8848` | fix: short position runtime support and reduce_only preservation | REQUIRED_SECURITY_FIX | 5 |
| 7 | `7a5064c` | fix: propagate reduce_only to OrderIntent and stabilize tests | REQUIRED_SECURITY_FIX | 3 |
| 8 | `62b0bcd` | fix: reduce-only risk semantics end-to-end | REQUIRED_DATA_MIGRATION | 14 |
| 9 | `8a88e2e` | feat: canonical LLM entry and real AI position context | SUPERSEDED | 19 |
| 10 | `3b6f3f7` | feat: evolution runtime foundation with UTC review scheduling | SUPERSEDED | 24 |
| 11 | `2fb9fc8` | feat: factor three-brain integration foundation | SUPERSEDED | 15 |
| 12 | `0a707e9` | test: skip engine-loop integration tests under CI sqlite contention | SUPERSEDED | 1 |
| 13 | `eacf033` | feat: phase 2 live factor evidence SSOT integration | SUPERSEDED | 18 |
| 14 | `c42d637` | feat: phase 3 full daily learning brain | SUPERSEDED | 17 |
| 15 | `3eb4e57` | feat: durable learning persistence backends | REQUIRED_DATA_MIGRATION | 11 |
| 16 | `d7d33b4` | docs: add factor architecture audit snapshot | REQUIRED_DOC/EVIDENCE | 1 |
| 17 | `c203781` | docs: expand canonical factor three-brain architecture | REQUIRED_DOC/EVIDENCE | 1 |
| 18 | `6c3f8a1` | fix: make factor snapshots deeply immutable | CONFLICTING_REQUIRES_DECISION | 1 |
| 19 | `9821137` | test: cover factor snapshot deep immutability | SUPERSEDED | 1 |
| 20 | `0c78160` | feat: phase 4 hierarchical weekly monthly yearly learning | SUPERSEDED | 12 |
| 21 | `4bb9209` | feat: hierarchical review durable persistence | REQUIRED_DATA_MIGRATION | 10 |
| 22 | `4bdbc1e` | feat: evolution candidate foundation | SUPERSEDED | 11 |
| 23 | `4d5b75b` | feat: phase 6 isolated self-modification and validation pipeline | SUPERSEDED | 11 |
| 24 | `4fc1c73` | feat: phase 7 safe promotion activation rollback | SUPERSEDED | 12 |
| 25 | `2bf6d5b` | docs: phase 8 production readiness audit and soak smoke | REQUIRED_DOC/EVIDENCE | 12 |
| 26 | `403b5b9` | docs: phase 8b runtime qualification status and postgres script | REQUIRED_DOC/EVIDENCE | 8 |
| 27 | `70a009b` | docs: external staging qualification not executed | REQUIRED_DOC/EVIDENCE | 3 |
| 28 | `674a225` | ci: add postgres runtime qualification workflow and tests | SUPERSEDED | 2 |
| 29 | `1e846c1` | fix: alembic env postgres url and migration chain | REQUIRED_DATA_MIGRATION | 3 |
| 30 | `2e4e3c0` | fix: use sync postgresql driver for alembic migrations | CONFLICTING_REQUIRES_DECISION | 1 |
| 31 | `d80bae5` | fix: postgres boolean default in order contract migration | REQUIRED_DATA_MIGRATION | 1 |
| 32 | `2116532` | docs: postgres runtime validation passed in CI | REQUIRED_DOC/EVIDENCE | 2 |
| 33 | `1b71438` | feat: integrate factor health into snapshot path | SUPERSEDED | 6 |
| 34 | `dd48540` | feat: complete factor profile readiness contract | SUPERSEDED | 2 |
| 35 | `846bfc1` | feat: add weekly learning aggregation with monthly/yearly reviews | SUPERSEDED | 6 |
| 36 | `3581ce0` | test: audit postgres integration test restoration status | SUPERSEDED | 1 |
| 37 | `a872777` | feat: add evolution candidate contract foundation | SUPERSEDED | 3 |
| 38 | `573d20e` | style: clean pre-existing lint errors in migrations and scripts | REQUIRED_DATA_MIGRATION | 4 |
| 39 | `007c101` | docs: update three-brain learning and evolution architecture | REQUIRED_DOC/EVIDENCE | 7 |
| 40 | `64fbd82` | docs: consolidate project memory for three-brain support workstream | REQUIRED_DOC/EVIDENCE | 5 |
| 41 | `8bba513` | feat: canonicalization and GLM reconciliation hardening | REQUIRED_SECURITY_FIX | 29 |
| 42 | `7cbf2b8` | feat: final canonicalization hardening chapter 9.5c | SUPERSEDED | 11 |
| 43 | `af9e393` | feat: remove second candidate authority | SUPERSEDED | 9 |
| 44 | `61de2f9` | test: canonical candidate contract pre-flight hardening | SUPERSEDED | 6 |
| 45 | `8863078` | docs: final technical release report and runbook | REQUIRED_DOC/EVIDENCE | 7 |
| 46 | `5b89012` | docs: post-completion maintenance audit | REQUIRED_DOC/EVIDENCE | 9 |
| 47 | `ce4b709` | docs: record execution lock and staging gate | REQUIRED_DOC/EVIDENCE | 2 |
| 48 | `20a4db8` | feat: integrate shared llm runtime for three-brain paper trading | REQUIRED_DATA_MIGRATION | 57 |
| 49 | `d4f25ca` | docs: record llm runtime qualification baseline 20a4db8 in project memory | REQUIRED_DOC/EVIDENCE | 4 |
| 50 | `efc25b1` | fix: harden llm runtime against fake-ip dns and unbounded entry calls | CONFLICTING_REQUIRES_DECISION | 4 |
| 51 | `e5e3711` | fix: risk panel shows honest backend-derived metrics | REQUIRED_SECURITY_FIX | 3 |
| 52 | `7b746df` | feat: persist decision evidence for live llm decisions | SUPERSEDED | 7 |
| 53 | `1771f35` | docs: paper smoke test PASS, llm runtime validated, 24h blocked by environment | REQUIRED_DOC/EVIDENCE | 5 |
| 54 | `7e697e2` | feat: strategy-selection decision model for live trading brain (PAPER) | SUPERSEDED | 16 |
| 55 | `725a586` | feat: PAPER exploration mode + CORE_TRADING_DOCTRINE_V1 | SUPERSEDED | 17 |
| 56 | `ebc907f` | fix: PAPER exploration final context patch - memory wired + factor fail-closed | REQUIRED_SECURITY_FIX | 12 |
| 57 | `8d15143` | feat: add live crypto strategy playbooks | SUPERSEDED | 1 |
| 58 | `488cf1c` | feat: export live crypto playbook strategies | SUPERSEDED | 1 |
| 59 | `3e8bc6e` | feat: add live playbooks to strategy evidence builder | SUPERSEDED | 1 |
| 60 | `f11733a` | test: cover live strategy evidence playbooks | SUPERSEDED | 1 |
| 61 | `ce21805` | feat: expand canonical universe to 20 crypto symbols | SUPERSEDED | 1 |
| 62 | `d537762` | feat: configure 20-symbol real market universe | SUPERSEDED | 1 |
| 63 | `2d9ff99` | feat: isolate real OKX market feeds per symbol | SUPERSEDED | 1 |
| 64 | `a6e41ed` | feat: make live decision context symbol-aware | SUPERSEDED | 1 |
| 65 | `f387b64` | feat: add round-robin multi-symbol Chief Trader adapter | SUPERSEDED | 1 |
| 66 | `7136038` | feat: wire 20-symbol real OKX market scanner | SUPERSEDED | 1 |
| 67 | `261e464` | test: cover 20-symbol real market routing | SUPERSEDED | 1 |
| 68 | `fa5265b` | docs: expose default 20-symbol trading universe | REQUIRED_DOC/EVIDENCE | 1 |
| 69 | `a4ee4a2` | fix: log feed shutdown failures for ruff | CONFLICTING_REQUIRES_DECISION | 1 |
| 70 | `5a35f87` | fix: sort multi-symbol bootstrap imports | CONFLICTING_REQUIRES_DECISION | 1 |
| 71 | `5d2181c` | fix: normalize symbol mapper import block | CONFLICTING_REQUIRES_DECISION | 1 |
| 72 | `6355bcf` | feat: add cheap multi-symbol opportunity scanner | SUPERSEDED | 1 |
| 73 | `5a3113a` | feat: cache real candles for scanner and chief trader | SUPERSEDED | 1 |
| 74 | `24833ce` | feat: gate chief trader behind opportunity ranking | SUPERSEDED | 1 |
| 75 | `9e01292` | feat: configure cheap opportunity ranking | SUPERSEDED | 1 |
| 76 | `85d036d` | feat: wire top-k opportunity scanner into runtime | SUPERSEDED | 1 |
| 77 | `2940a15` | docs: expose opportunity scanner controls | REQUIRED_DOC/EVIDENCE | 1 |
| 78 | `9cd35a1` | test: cover opportunity ranking and candle reuse | SUPERSEDED | 1 |
| 79 | `43717b8` | fix: wrap candle cache expression for ruff | CONFLICTING_REQUIRES_DECISION | 1 |
| 80 | `16fd09b` | fix: wrap opportunity gate initialization for ruff | CONFLICTING_REQUIRES_DECISION | 1 |
| 81 | `7c0f11f` | fix: frontend NO_TRADE / NOT_AVAILABLE semantic normalization | CONFLICTING_REQUIRES_DECISION | 3 |
| 82 | `6e02322` | fix: make opportunity scanner advisory only | CONFLICTING_REQUIRES_DECISION | 1 |
| 83 | `5cc3c445` | feat: add AI-first entry decision policy | SUPERSEDED | 1 |
| 84 | `f5d3886` | refactor: route multi-symbol runtime through AI-first policy | SUPERSEDED | 1 |
| 85 | `27c8618` | test: make opportunity ranking advisory | SUPERSEDED | 1 |
| 86 | `30733cd` | test: cover AI-first entry policy | SUPERSEDED | 1 |
| 87 | `68bbbfa` | feat: add AI-first decision console | SUPERSEDED | 1 |
| 88 | `57d2743` | style: add AI-first decision console | SUPERSEDED | 1 |
| 89 | `ad6a6cf` | feat: mount AI-first decision console | SUPERSEDED | 1 |
| 90 | `ce1b202` | test: cover AI-first frontend console | SUPERSEDED | 1 |
| 91 | `a6e1123` | ci: validate trading frontend | SUPERSEDED | 1 |
| 92 | `38bda57` | feat: bidirectional PAPER perpetual trading integration | SUPERSEDED | 12 |
| 93 | `626558b` | feat: add advisory technical indicator engine | SUPERSEDED | 1 |
| 94 | `d9d86d0` | feat: preserve complete OKX ticker state | SUPERSEDED | 1 |
| 95 | `68a4383` | feat: map full OKX market state | SUPERSEDED | 1 |
| 96 | `8825039` | feat: add OKX public history data client | SUPERSEDED | 1 |
| 97 | `a5614ca` | feat: use expanded OKX public ticker data | SUPERSEDED | 1 |
| 98 | `f3e04f5` | feat: feed advisory technical evidence to chief trader | SUPERSEDED | 1 |
| 99 | `d1d1f84` | fix: preserve live decision bundle compatibility | CONFLICTING_REQUIRES_DECISION | 1 |
| 100 | `3790ef0` | test: cover expanded OKX market evidence | SUPERSEDED | 1 |
| 101 | `10db3d8` | test: verify technical evidence reaches AI context | SUPERSEDED | 1 |
| 102 | `016cf51` | fix: format advisory technical indicators | CONFLICTING_REQUIRES_DECISION | 1 |
| 103 | `90a2ddd` | fix: name OKX derivative volume correctly | CONFLICTING_REQUIRES_DECISION | 1 |
| 104 | `99255f6` | fix: preserve OKX derivative volume semantics | CONFLICTING_REQUIRES_DECISION | 1 |
| 105 | `6f4ec0b` | fix: map OKX base-currency 24h volume | CONFLICTING_REQUIRES_DECISION | 1 |
| 106 | `124e650` | feat: expose OKX market intelligence to frontend | SUPERSEDED | 1 |
| 107 | `b77c9a4` | chore: wire market analysis router | REQUIRED_DOC/EVIDENCE | 1 |
| 108 | `9923404` | chore: retry market analysis router wiring | REQUIRED_DOC/EVIDENCE | 1 |
| 109 | `91c9721` | feat: wire OKX market analysis API | SUPERSEDED | 1 |
| 110 | `7c8b0a5` | feat: add full OKX market intelligence frontend | SUPERSEDED | 1 |
| 111 | `3f80598` | style: add OKX market intelligence drawer | SUPERSEDED | 1 |
| 112 | `27dc226` | feat: mount OKX market intelligence frontend | SUPERSEDED | 1 |
| 113 | `6b83275` | test: cover OKX market intelligence frontend | SUPERSEDED | 1 |
| 114 | `c87a10e` | test: tighten OKX market intelligence assertions | SUPERSEDED | 1 |
| 115 | `5418a41` | chore: remove temporary router wiring workflow | REQUIRED_DOC/EVIDENCE | 1 |
| 116 | `96f9850` | fix: restore AI entry authority + funnel observability (AI-FIRST) | CONFLICTING_REQUIRES_DECISION | 7 |
| 117 | `75db23b` | fix: align render_prompt fallback path with AI-FIRST entry authority | CONFLICTING_REQUIRES_DECISION | 1 |
| 118 | `c85f25a` | fix: paper spot fills must use the real OKX reference price | CONFLICTING_REQUIRES_DECISION | 2 |
| 119 | `2f1c527` | fix: ledger-first paper exchange hydration (reconciliation halt guard) | REQUIRED_SECURITY_FIX | 2 |
| 120 | `11a93bf` | fix: pre-authorization orderbook refresh uses the reference market symbol | CONFLICTING_REQUIRES_DECISION | 1 |
| 121 | `53c4f57` | fix: _match_order no longer clobbers refreshed books with synthetic seed | CONFLICTING_REQUIRES_DECISION | 2 |
| 122 | `1b83f05` | fix: futures-aware reconciliation scope (perpetual fills no longer halt) | REQUIRED_SECURITY_FIX | 4 |
| 123 | `c432a06` | fix: unify ledger spot-scope between paper hydration and reconciliation | REQUIRED_SECURITY_FIX | 2 |
| 124 | `af426a1` | fix: 10 perpetual duplicate-entry gate in the AI-first decide path | REQUIRED_SECURITY_FIX | 2 |
| 125 | `53d46c4` | fix: scope the perpetual duplicate-entry gate to the entry symbol | REQUIRED_SECURITY_FIX | 4 |
| 126 | `129317a` | docs: PAPER_TRADE_E2E_READY=YES acceptance report + memory update | REQUIRED_DOC/EVIDENCE | 6 |
| 127 | `899ce02` | docs: record NEW_RUNTIME_BASELINE_SHA | REQUIRED_DOC/EVIDENCE | 1 |
| 128 | `d3589dd` | fix: log full traceback on exchange-event processing failure | CONFLICTING_REQUIRES_DECISION | 1 |
| 129 | `f28e2fe` | fix: per-process exchange-order-id namespace stops restart collisions | CONFLICTING_REQUIRES_DECISION | 4 |
| 130 | `e36d166` | docs: record permanent AI-FIRST architecture invariant + live-path audit | REQUIRED_DOC/EVIDENCE | 2 |
| 131 | `7f3fa43` | fix: reconcile base-asset balance representation against position scope | REQUIRED_SECURITY_FIX | 2 |
| 132 | `ebcff58` | docs: acceptance report  post-fix autonomous fills (BNB 690.40, DOGE 0.08525) + blockers 9-12 | REQUIRED_DOC/EVIDENCE | 1 |
| 133 | `41064c5` | docs: record final baseline + post-fix autonomous fills | REQUIRED_DOC/EVIDENCE | 1 |
| 134 | `92e4668` | docs: enter PHASE 2 overnight paper observation mode | REQUIRED_DOC/EVIDENCE | 3 |
| 135 | `9f40a53` | checkpoint 02:30Z: 2 new clean AI fills (SOL @103.89, ADA @0.2012), health OK, 0 errors | HISTORICAL/JOURNAL_ONLY | 3 |
| 136 | `ef2cd42` | fix: market-data health flag recovers on successful tick-path ingest | CONFLICTING_REQUIRES_DECISION | 2 |
| 137 | `7526e39` | checkpoint 03:15Z: 3 new clean AI fills (LINK/AVAX/APT, real prices); LTC health-flag recovery fix ef2cd42 deployed; overall OK | HISTORICAL/JOURNAL_ONLY | 3 |
| 138 | `6dd0876` | checkpoint 03:30Z: SUI fill @0.7387 (10 clean AI fills total), health OK, 0 errors | HISTORICAL/JOURNAL_ONLY | 3 |
| 139 | `b8b71fd` | checkpoint 04:00Z: 3 new clean fills (ARB/LTC/NEAR), AI-vs-quant override sample (ARB fit 0.46->LONG), health OK | HISTORICAL/JOURNAL_ONLY | 3 |
| 140 | `a86759d` | checkpoint 04:30Z: 3 new clean fills (DOT/BCH/OP), BCH AI-SHORT correctly risk-blocked, 16 clean fills total, health OK | HISTORICAL/JOURNAL_ONLY | 3 |
| 141 | `aeeb92d` | checkpoint 05:00Z: 2 new clean fills (UNI/TRX), 18 clean AI fills total, health OK | HISTORICAL/JOURNAL_ONLY | 3 |
| 142 | `ffcdc69` | checkpoint 05:30Z: no fills (19/20 symbols position-gated, correct anti-pyramiding); BTC perp bridge exit expected ~06:08Z; health OK | HISTORICAL/JOURNAL_ONLY | 3 |
| 143 | `a7facc2` | checkpoint 06:00Z: no fills (fully position-gated, correct); BTC perp exit window approaching; health OK | HISTORICAL/JOURNAL_ONLY | 2 |
| 144 | `8d6f505` | P1: position lifecycle closes through canonical authorities; P2: factor snapshots persisted durably | CONFLICTING_REQUIRES_DECISION | 6 |
| 145 | `88b1b14` | supervisor directive RESOLVED: P1 lifecycle + P2 snapshot durability with production runtime proof | CONFLICTING_REQUIRES_DECISION | 4 |
| 146 | `91c9c1a` | checkpoint 07:30Z: P1 exit cycle complete (19->9 positions, real prices, BTC_PERP realized PnL); LLM resumed; first re-entry LINK @11.32; fsnap persisting | HISTORICAL/JOURNAL_ONLY | 5 |
| 147 | `d1f60c0` | checkpoint 07:54Z: full lifecycle continuous (exits+re-entries+BTC_PERP SHORT re-open); prior hang diagnosis was a time-base error, engine never hung | HISTORICAL/JOURNAL_ONLY | 6 |
| 148 | `6c5112e` | lesson: date -u anchoring for time-based diagnosis; supervisor crash logging | HISTORICAL/JOURNAL_ONLY | 1 |
| 149 | `ee5f0ab` | checkpoint 07:56Z (queued 07:30 firing): NEAR exit @1.789, positions 11->10, health OK | HISTORICAL/JOURNAL_ONLY | 2 |
| 150 | `5d42a57` | checkpoint 08:00Z: ETH clean re-entry @2435 (taint replaced by real-price cycle), lifecycle continuous, health OK | HISTORICAL/JOURNAL_ONLY | 6 |
| 151 | `1faf1bc` | checkpoint 08:30Z: continuous cycling (3 exits + 4 AI re-entries, all real prices), 16 LLM calls, health OK | HISTORICAL/JOURNAL_ONLY | 2 |
| 152 | `d26e4e8` | P2: result-aware EXIT retry + snapshot durability telemetry + full ETH episode quarantine | CONFLICTING_REQUIRES_DECISION | 8 |
| 153 | `bb4fa37` | Expand PAPER observation universe 20 -> 30 with generic bidirectional paper-perpetual registry | CONFLICTING_REQUIRES_DECISION | 11 |
| 154 | `f3098b7` | Docs: P2 closure evidence, lease-loss invariants, 30-symbol expansion deployment | REQUIRED_DOC/EVIDENCE | 3 |
| 155 | `1da8fee` | PAPER perp sizing step 1e-5 so exploration-sized legal entries pass precision gate | CONFLICTING_REQUIRES_DECISION | 2 |
| 156 | `fef3c33` | Checkpoint 10:05Z: lease-loss recovery closed, expansion live, perp sizing-step fix; 2 new real-price AI fills with full lineage | HISTORICAL/JOURNAL_ONLY | 2 |
| 157 | `dfb92ec` | Checkpoint 10:10Z quick re-fire: no delta, all healthy | HISTORICAL/JOURNAL_ONLY | 1 |
| 158 | `affbaea` | Checkpoint 10:12Z: ADA fill lineage (real price), fit=1.0 saturation watch item; all healthy | HISTORICAL/JOURNAL_ONLY | 3 |
| 159 | `27756d4` | Checkpoint 10:30Z: FIRST new-symbol paper-perp fill (ENAUSDT_PERP exploration entry, real price, full lineage) - expansion chain verified in production | HISTORICAL/JOURNAL_ONLY | 3 |
| 160 | `a5cb804` | Checkpoint 11:00Z: 3 more new-symbol perp fills incl FIRST perp SHORT (WLDUSDT_PERP); bidirectional expansion verified; full lineages logged | HISTORICAL/JOURNAL_ONLY | 3 |
| 161 | `e2c4c75` | Checkpoint 11:30Z: bridge 4h time-stop exit closed LINK cycle on exact anniversary (entry->exit loop verified); no retry storm, no duplicates | HISTORICAL/JOURNAL_ONLY | 3 |
| 162 | `c1f31b6` | Position read-model repair: per-symbol real marks, backend SPOT PnL, zero-position filter, cross-symbol fallback removed | CONFLICTING_REQUIRES_DECISION | 4 |
| 163 | `a13fda7` | Docs: position read-model repair acceptance evidence | REQUIRED_DOC/EVIDENCE | 2 |
| 164 | `fe82ae1` | Order/Fill/PnL observability repair: orders read model with real fees, avg fill price and canonical PnL attribution | CONFLICTING_REQUIRES_DECISION | 7 |
| 165 | `a4903cf` | Docs: order/fill/PnL observability acceptance evidence | REQUIRED_DOC/EVIDENCE | 2 |
| 166 | `a93da28` | Checkpoint 13:35Z: backend vanished + safe single-writer restart; 22 real-price fills since 11:30Z (4h exits + re-entries); 7 risk rejects held low-fit entries; no duplicates; PAPER intact | HISTORICAL/JOURNAL_ONLY | 3 |
| 167 | `6df2209` | Trade episode / learning pipeline repair: canonical closed-trade cycle replay -> AITradeEpisode persistence at close time; durable exit-reason (TIME_STOP/RISK_EXIT/AI_EXIT) correlation; idempotent deterministic backfill (37 episodes incl. LINKUSDT TIME_STOP 14405s and BTC_PERP ledger-anchored PnL); 15 targeted tests | REQUIRED_DOC/EVIDENCE | 10 |
| 168 | `c5dfd0b` | Ops: backend keepalive scripts (.ops watchdog + cron revive); external SIGTERM sweeps documented (5 kills today) | CONFLICTING_REQUIRES_DECISION | 2 |
| 169 | `a0e3405` | Checkpoint 15:15Z: 15 real-price fills, 44 episodes (learning pipeline live), 2 risk rejects held, backend ALIVE via cron revive, PAPER intact | HISTORICAL/JOURNAL_ONLY | 3 |
| 170 | `495392a` | Checkpoint 15:30Z: TAO/AAVE perp 4h exits auto-episoded (46 total, TIME_STOP), LTC re-entry @49.06 REAL; ALIVE | HISTORICAL/JOURNAL_ONLY | 1 |
| 171 | `24db4d4` | Checkpoint 15:31Z deep: 16 open positions, FUTURES_RPNL cum -0.503194, episodes 46 all TIME_STOP, zero errors since 15:14Z | HISTORICAL/JOURNAL_ONLY | 3 |
| 172 | `28c5d1a` | P0 corrections CS-20260829-132209 + P1/P2 linked: fail-closed manual mutation routes, real-mark perp read model, symbol-scoped cooldown, episode quarantine/leverage/migration fixes | REQUIRED_DATA_MIGRATION | 19 |
| 173 | `e2315a5` | Checkpoint 17:35Z: P0 corrections pushed (28c5d1a); episodes re-derived 52 clean; runtime restart sequencing note | HISTORICAL/JOURNAL_ONLY | 1 |
| 174 | `6b21658` | PHASE A+B: OKX all-market capability matrix + dynamic instrument registry | REQUIRED_DATA_MIGRATION | 11 |
| 175 | `b037cc8` | Checkpoint 17:30Z: Phase A+B pushed (6b21658), registry 2029 instruments, Phase G baseline HOLD | HISTORICAL/JOURNAL_ONLY | 1 |
| 176 | `626d4ee` | Checkpoint 17:30Z deep: 7 real-price fills, funnel 145 (4L/1S/140NT natural), episodes 53, RPNL 12h -0.3939, dups 0, Phase G HOLD baseline | HISTORICAL/JOURNAL_ONLY | 4 |
| 177 | `da47b51` | Checkpoint 18:00Z deep: 5 real fills (3 perp), funnel 145 (2L/3S/140NT), episodes 54, Phase G HOLD | HISTORICAL/JOURNAL_ONLY | 4 |
| 178 | `2c84d14` | Checkpoint 18:30Z deep: quiet window (AAVE_PERP exit @123.315 real), funnel 138 (97.1% NT natural), episodes 55, Phase G HOLD | HISTORICAL/JOURNAL_ONLY | 4 |
| 179 | `4581928` | Checkpoint 19:00Z deep: ADA round-trip + ONDO_PERP entry (real prices), episodes 55, clean TIME_STOP attribution, Phase G HOLD | HISTORICAL/JOURNAL_ONLY | 4 |
| 180 | `83cc2f8` | Checkpoint 19:30Z deep: 7 fills across 7 distinct symbols (all real), episodes 58, Phase G HOLD | HISTORICAL/JOURNAL_ONLY | 4 |
| 181 | `c8c69c9` | Checkpoint 20:00Z deep: 7 fills/6 symbols incl BTC_PERP real 5-min cycle, episodes 63 (+5), RPNL -0.7172, Phase G HOLD | HISTORICAL/JOURNAL_ONLY | 4 |
| 182 | `40bf730` | Checkpoint 20:30Z deep: 5 real fills, episodes 65, direction-flip watch (XRP 2nd occurrence, non-consecutive), Phase G HOLD | HISTORICAL/JOURNAL_ONLY | 4 |
| 183 | `f2081ee` | Checkpoint 21:00Z deep: 4 real fills, episodes 69, direction-flip watch 3rd window (CONTRACT pre-staged), Phase G HOLD | HISTORICAL/JOURNAL_ONLY | 4 |
| 184 | `2abee89` | Checkpoint 21:30Z deep: first CONTRACT (cooldown 240->300 staged, sec.26/48 bounded), 8 real fills, episodes 74 (+5) | HISTORICAL/JOURNAL_ONLY | 5 |
| 185 | `eaac1ba` | Checkpoint 22:00Z deep: churn cleared organically, RPNL improved -0.2611, episodes 78, staged-300 rollback decision due window 11 | HISTORICAL/JOURNAL_ONLY | 4 |
| 186 | `feae097` | Checkpoint 22:30Z deep: ROLLBACK per pre-declared plan (staged 300 cancelled, baseline 240 restored), 2nd clean window, episodes 79 | HISTORICAL/JOURNAL_ONLY | 5 |
| 187 | `6292063` | Checkpoint 23:00Z deep: 3rd clean window, rollback validated, 5 real fills, episodes 81 | HISTORICAL/JOURNAL_ONLY | 4 |
| 188 | `036adfd` | Checkpoint 23:30Z deep: 4th clean window, 4h TIME_STOP lifecycle verified (4 cycles), 8 real fills, episodes 85 | HISTORICAL/JOURNAL_ONLY | 4 |
| 189 | `eef0398` | Checkpoint 00:00Z deep: 5th clean window, 7 real fills, episodes 87, steady state | HISTORICAL/JOURNAL_ONLY | 4 |
| 190 | `0b55003` | Checkpoint 00:30Z deep: 6th clean window, 6 real fills, episodes 90, steady state | HISTORICAL/JOURNAL_ONLY | 4 |
| 191 | `bc0f78a` | Checkpoint 01:00Z deep: TRX 45s-flip churn anomaly -> CONTRACT re-staged (240->300), first UNKNOWN exit_reason flagged, episodes 93 | HISTORICAL/JOURNAL_ONLY | 5 |
| 192 | `784216a` | Night journal 2026-08-29: trade/change/strategy journals (151 fills, 94 episodes, 16 calibration windows) | HISTORICAL/JOURNAL_ONLY | 1 |

## Preliminary category counts

- CONFLICTING_REQUIRES_DECISION: 32
- HISTORICAL/JOURNAL_ONLY: 43
- REQUIRED_DATA_MIGRATION: 9
- REQUIRED_DOC/EVIDENCE: 29
- REQUIRED_SECURITY_FIX: 11
- SUPERSEDED: 68

## Required semantic checks before landing

All `REQUIRED_*` and `CONFLICTING_REQUIRES_DECISION` rows must be checked against the final landing tree. Evidence must be recorded in this file or a linked receipt before closing the audit.
