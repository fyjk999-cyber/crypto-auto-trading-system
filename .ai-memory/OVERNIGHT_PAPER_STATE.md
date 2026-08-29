# OVERNIGHT_PAPER_SESSION

Session Start: 2026-08-29T00:35:45Z (first clean AI fill)
First AI Fill: fill_8396534b10d74e25843509a357d6e0ab — BTCUSDT_PERP LONG 0.001 @ 77753.05
Latest Checkpoint: 2026-08-29T05:00:00Z

Runtime: ACTIVE
PAPER Mode: CONFIRMED (TRADING_MODE=PAPER, LIVE_TRADING_ENABLED=false, PAPER_MODE=PAPER_REAL_MARKET)
Market: OKX REAL (public data only)

Trades: 18 entry fills + 14 exit fills + 4 AI re-entries (LINK @11.32, XRP @1.3809, AVAX @7.27, SUI @0.7361) + BTC_PERP re-open SHORT 0.001 @77582.55 - full lifecycle live
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
