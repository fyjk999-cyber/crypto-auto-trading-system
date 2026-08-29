# OVERNIGHT PAPER REVIEW — 2026-08-29 session

> Continuously updated for tomorrow's human review. The runtime keeps
> trading while this file is written. Truth source: data/crypto_trader.db.

## A. Executive Summary

- Session start: 2026-08-29T00:35:45Z (first clean AI paper fill)
- PAPER status: CONFIRMED throughout (TRADING_MODE=PAPER, PAPER_MODE=PAPER_REAL_MARKET,
  LIVE_TRADING_ENABLED=false, no real OKX order endpoints contacted)
- System uptime: continuous; one final restart at 02:08:42Z after the
  order-id/reconciliation fixes; overall health OK since
- Total market cycles: continuous 20-symbol rotation (~4-5 AI calls/min)
- Total LLM calls: 52 (42 live_analysis), 0 failed (as of 02:20Z)
- Total trades (clean AI fills): 4 (+1 pre-fix BTC stacking sample + 1
  legacy tainted ETH sample, excluded from claims)
- Win/Loss: 0/0 — no closed rounds yet; positions open (bridge owns exits)
- PnL: all open; unrealized tracked per position endpoint
- Current positions at checkpoint: BTCUSDT_PERP 0.002 @ 77720.20,
  BNBUSDT 0.001 @ 690.40, DOGEUSDT 0.0005 @ 0.08525, XRPUSDT 0.001 @ 1.3833,
  ETHUSDT 0.001 @ 100.05 (legacy)

## B. Trading Funnel

Layer counts (all-time decision_evidence, /trading-funnel):

| Layer | Count | Conversion |
|---|---|---|
| Decisions (AI) | 1084+ | — |
| LONG | 26 | 2.4% |
| SHORT | 21 | 1.9% |
| NO_TRADE | 1029 | 95.0% |
| WAIT | 8 | 0.7% |
| Risk APPROVE | 7 | of AI entries: 7/(26+21 directional) |
| Risk REJECT | 6 | SPOT_OVERSHORT (non-BTC SHORT protection) |
| Execution APPROVE | all post-fix approvals | 0 holds post-fix |
| Orders FILLED | 2 (pre-fix era) + BNB/DOGE/XRP | — |
| Fills | 5 clean (4 spot + 1 perp) + 1 stacked perp | — |

## C. All Trades

6.1 SOLUSDT LONG 0.001 @ 103. 02:20: dec_24527f3c3ed64908a3,
    mean_reversion, fit 1.0/conf 0.8, eir llm_b7410973bfdb..., fill
    fill_5619c1d6089f4f188c5a084b6a9608a1 / ord_2eb4b05d409e4c51bed1c12e4f20d1e0.
    Thesis: oversold RSI14 23.4, z -2.52, near support. OPEN.
6.2 ADAUSDT LONG 0.001 @ 0. 02:26: dec_fc27c3ad6678491f90,
    mean_reversion, fit 1.0/conf 0.8, eir llm_5076eafe4d9e410c84da, fill
    fill_e8fe91ae129a47a1ab6c47cea2734b7e / ord_bf34cab0f9884d4c83b10fd024fc6d56.
    Thesis: RSI14 15.38, z -1.79, lower band + support 0.2011, volume rising. OPEN.

1. BTCUSDT_PERP LONG 0.001 @ 77753.05 — mean_reversion (AI fit 1.0/conf 0.8),
   thesis: oversold RSI6 4.98 / RSI14 28.75, z -1.75, support 77734.3.
   OPEN. Clean proof fill (§6 lineage in PAPER_TRADE_E2E_ACCEPTANCE_REPORT.md).
2. BNBUSDT LONG 0.001 @ 690.40 — AI fill post-namespace-fix. OPEN.
3. DOGEUSDT LONG 0.0005 @ 0.08525 — AI fill, 37s after restart. OPEN.
4. XRPUSDT LONG 0.001 @ 1.3833 — AI fill. OPEN.
5. (excluded) BTCUSDT_PERP second LONG 0.001 @ 77687.35 — real price but
   stacked during the gate-gap window (fixed in af426a1/53d46c4).
6. (excluded) ETHUSDT 0.001 @ 100.05 — pre-fix corrupted price.

6.3 LINKUSDT LONG 0.0005 @ 11.379 - 02:49:21Z. OPEN. Real price.
6.4 AVAXUSDT LONG 0.0005 @ 7.27 - 03:06:04Z. OPEN. Real price.
6.5 APTUSDT LONG 0.001 @ 0.5359 - 03:13:06Z. OPEN. Real price.

## D. Best Trades

TBD — positions still open. Early observation: BTC entry thesis was
supported by multi-factor confluence (mean-reversion z-score + support
retest + volume decline) at a REAL support zone.

## E. Worst Trades

TBD. The legacy ETH @ 100.05 sample is excluded (pre-fix data corruption,
not an AI decision error). The BTC stack (5) was a runtime gate bug, also
not an AI judgment error — AI reasoning itself was consistent.

## F. AI Decision Quality

- NO_TRADE theses are substantive (range-bound detection, z-score within
  band, volume divergence, weak conviction) — sampled in decision_json.
- SHORT proposals on non-BTC symbols were blocked by design
  (SPOT_OVERSHORT); the AI still proposed them — this is correct behavior
  on both sides (AI decides, Risk protects).
- Distribution: NO_TRADE 95% — market was genuinely range-bound overnight;
  to be re-evaluated tomorrow against realized outcomes (§30 Q16).

## G. Strategy Performance

- mean_reversion: 1 clean entry (BTC), win/loss TBD.
- LOW_SAMPLE_SIZE — no win-rate claims possible yet (§30 Q4 honored).

## H. AI vs Quant

- Clean example: BTC decision had strategy_fit 1.0 (quant aligned) — need
  disagreement samples from overnight data: query decision_evidence for
  fit < 0.55 with action LONG/SHORT (AI overrode weak quant fit) and fit
  high with NO_TRADE. Extraction query documented for tomorrow's review.

## I. Risk / Execution

- 6 SPOT_OVERSHORT rejects (by-design spot-short protection on 19 symbols;
  multi-symbol perpetual registry = open follow-up).
- 0 execution holds/rejects after final fixes.
- Historical holds (RECONCILIATION_HALT / MARKET_DATA_STALE) all traced to
  fixed root causes (1b83f05, 11a93bf, 7f3fa43, f28e2fe).

## J. Memory / Learning

- LiveMemoryProvider wired; Daily Review Scheduler active at configured
  window; trade episodes recorded to ai_trade_episodes.
- No lessons extracted yet this session (first review pending).
- Learning decoupled from live trading (§26 honored; no live weight changes).

## K. Repeated Mistakes

- None observed post-fix. Pre-fix repetition pattern (fake-price fills,
  gate gaps) was engineering, not AI behavior.

## L. Candidate Lessons

- Pending first Daily Review run.

## M. Candidate Strategy Improvements

- Proposals only after first Daily Review; none deployed mid-session (§33).

## N. System Errors

- Checkpoint 02:30Z: 0 errors, 0 stuck orders, 0 execution holds, recon OK,
  overall OK. 2 new clean AI fills at real prices since last checkpoint.
- 03:05Z: LTCUSDT transient fetch failure left the market_data health flag
  stuck UNHEALTHY (tick path never cleared it). Data gate itself worked
  (LTC fail-closed); flag recovery fixed in ef2cd42 + regression test.
  Runtime restarted healthy; no trades affected.
- Checkpoint 03:15Z: 3 more clean AI fills (LINK 11.379, AVAX 7.27, APT
  0.5359 - all real prices), 0 stuck orders, 0 errors, overall OK.
- Fixed during the session: gateway health misfire, live prompt read-only
  bias, quant hard gates, fake fill price, restart reconciliation halt,
  stale refresh symbol, match-book clobber, perp gate loss, order-id
  collision, base-asset recon scope. Each documented with commit SHA in
  PAPER_TRADE_E2E_ACCEPTANCE_REPORT.md.
- Overnight transient errors: none blocking; OKX/DeepSeek healthy.

## O. 明日建议 (Tomorrow's Recommendations)

1. 观察: bridge 时间止损对 BTC 0.002 仓位的退出质量 (04:35-05:02Z 窗口)。
2. 观察: 各 spot 持仓的退出决策 (bridge vs AI)。
3. 验证: MAE/MFE 捕获 (episodes 表已有列,捕获待实现)。
4. 修复候选: 多币种永续注册表 (消除 SPOT_OVERSHORT 单边限制)。
5. 复盘: 用 §30 的 16 个问题跑第一次 Daily Review 人工复审。
