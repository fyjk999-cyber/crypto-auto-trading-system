# OVERNIGHT_PAPER_SESSION

Session Start: 2026-08-29T00:35:45Z (first clean AI fill)
First AI Fill: fill_8396534b10d74e25843509a357d6e0ab — BTCUSDT_PERP LONG 0.001 @ 77753.05
Latest Checkpoint: 2026-08-29T10:12Z (cron-2; covers the missed 10:06:50Z ADA fill)

Runtime: ACTIVE
PAPER Mode: CONFIRMED (TRADING_MODE=PAPER, LIVE_TRADING_ENABLED=false, PAPER_MODE=PAPER_REAL_MARKET)
Market: OKX REAL (public data only)

Trades: 18 entry fills + 15 exit fills + 5 AI re-entries (LINK, XRP, AVAX, SUI, ETH @2435 - clean cycle replacing legacy taint) + BTC_PERP re-open SHORT @77582.55 - full lifecycle live
Wins: 0 (no closed rounds yet)
Losses: 0
Realized PnL: 0 (all positions open; bridge owns exits)
Open Positions:
  - BTCUSDT_PERP LONG 0.002 @ 77720.20 (bridge-managed; time stop ~04:35-05:02Z)
  - ETHUSDT 0.001 @ 100.05 (LEGACY tainted-price sample; not counted)
  - BNBUSDT 0.001 @ 690.40 (AI fill, real price)
  - DOGEUSDT 0.0005 @ 0.08525 (AI fill, real price)
  - XRPUSDT 0.001 @ 1.3833 (AI fill, real price)
  - SOLUSDT 0.001 @ 103.89 (AI fill 02:20:52Z, real price)
  - ADAUSDT 0.001 @ 0.2012 (AI fill 02:26:54Z, real price)

Live LLM Calls (overnight window): 80+ live_analysis / 0 failed
LONG: 26  SHORT: 21  NO_TRADE: 1029  WAIT: 8  (all-time decision_evidence counts)
Risk Reject: 6 (all SPOT_OVERSHORT on non-BTC symbols — correct protection)
Execution Hold: 0 since final fixes

Latest Learning Run: none yet (first Daily Review fires at configured window)
Candidate Lessons: none (session just entered PHASE 2)
Confirmed Lessons: see memory (CANDIDATE/VALIDATING/CONFIRMED lifecycle unchanged)
Repeated Mistakes: none observed post-fix
Completed (P1 fix 8d6f505): 11 reduce-only EXITs at real prices 07:18-07:19Z (incl BTC_PERP @77492.15, FUTURES_REALIZED_PNL posted); positions 19->9; LLM flow resumed; LINK re-entry @11.32 (dec_4ad69b3e, support_resistance_reversal, fit 0.7874). factor_snapshots persisting (31 rows). Remaining 8 legacy positions exit at true 4h anniversaries 07:31-08:51Z.

Current Issues:
  - MAE/MFE tracking = NOT_AVAILABLE (documented; episodes carry mfe/mae columns, capture pending)
  - FIXED 03:05Z: market_data health flag stuck UNHEALTHY after transient LTC fetch error (tick path never cleared flag) - ef2cd42, runtime restarted, overall OK restored. LTC fail-closed gate itself worked correctly.
  - Stacked BTC position 0.002 from the pre-fix gate-gap window (bridge-managed)
  - Multi-symbol perpetual SHORT protection (SPOT_OVERSHORT) by design

Truth sources (never duplicate): data/crypto_trader.db tables
(decision_evidence, llm_usage, risk_decisions, audit_events, orders, fills,
ledger_transactions, positions_projection, ai_trade_episodes,
trade_memory_records, daily reviews). This file is an INDEX ONLY.

## 2026-08-29T10:10Z quick re-fire (cron-2)
- 3-minute window after the 10:05Z checkpoint: 0 new fills (total 55), 0 stuck orders, 0 risk decisions, 0 LLM rows, 0 audit errors. Health ALL OK, lease held, kill switch clear, TRADING_MODE=PAPER, single backend PID. Gate decisions continuing across the 30-symbol universe. No other section changes warranted.

## 2026-08-29T10:12Z checkpoint (cron-2)
- New fill caught between re-fires: ADAUSDT BUY 0.001 @0.1994 @10:06:50Z (real price, full lineage in REVIEW C). fills total 56; 0 stuck orders; 0 errors; health ALL OK; lease held; kill switch clear; TRADING_MODE=PAPER.
- Watch: second consecutive strategy_fit_score=1.0 entry (OP 10:01, ADA 10:06) — evidence-adjusted fit appears to saturate at the ceiling when strategies align; does not gate trading legality (Risk/Authority unchanged) but flag for Daily Learning review.


## Latest Checkpoint: 2026-08-29T10:05Z (cron-2)
- Health: ALL OK; execution lease held (single backend PID); kill switch clear; TRADING_MODE=PAPER verified.
- Incident closed: 09:18-09:26Z lease-loss (harness deleted active lease row) -> normal single-writer recovery; kill switch never bypassed; zero duplicates; recon 9/9 OK. Invariants in DECISIONS.md.
- Expansion LIVE since ~09:36Z (bb4fa37): universe 30, 11 paper-perp contracts on one engine; new symbols observing (gate NO_TRADE rows legal); new-symbol decisions accumulating.
- Defect found by observation + fixed (1da8fee): EXPLORATION_ENTRY (0.0005) failed PAPER perp precision (step 0.001) -> AUTHORITY fail-closed (correct); contract quantity_step now 1e-5 so legal exploration sizes pass; regression test added; deployed 09:58Z.
- Fills since 09:30Z: TRXUSDT BUY 0.001 @0.33804 (09:43:08); OPUSDT BUY 0.001 @0.08775 (10:01:41). Both real market prices, full lineage. fills total 55, orders total 60; 0 stuck orders; 0 audit errors since 09:30Z.
- LLM: 15 live_analysis calls 09:30-09:50Z, all success. Risk: 4 decisions (2 SPOT_OVERSHORT rejects = correct protection; 2 APPROVE). Open positions: 15.
- Wins/Losses: no exits this window; realized PnL unchanged this window.
