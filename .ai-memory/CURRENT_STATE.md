# CURRENT_STATE

- Updated: 2026-09-17T00:35+08:00 (cron-49 daily Growth jobs)
- Workstream: Low-Risk V2 SPEC Phase 5 (Growth) / Phase 7 (natural PAPER + >=72h soak).
- Acceptance SHA for soak window #4: `1ef721d6d491` (worktree `/tmp/lr2-soak2`,
  DB `/tmp/lr2-soak2/data/crypto_trader.db`, port 8010, PAPER only, LIVE disabled).

## This run (cron-49) - both jobs PASS
- Daily Top-10 freeze: `trading_day=2026-09-17`, `frozen=true`, `already_frozen=false`,
  live scanner returned 15 candidates -> 10 rows persisted (ranks 1-10, no dupes). Re-run reports
  `already_frozen=true`; `frozen_at` unchanged (first-freeze immutable).
- Growth lifecycle review: latest factual closed episode
  `episode_plan_75506599a561421eb23538d21ed56bd9` (KORUUSDT SHORT, closed 2026-09-16) ->
  entry VWAP 18.84 / exit VWAP 18.89 over 2 real fills -> `net_bps=-26.53927813163482` (loss) ->
  `written=2`, verdicts `[DEFECT, DEFECT]`.

## Blockers / defects found (see PHASE_7_RECEIPT.md for full evidence)
- **>=72h soak NOT met and the clock is broken.** Window #4 ran 4h28m39s, was down 13h58m03s,
  ran 4m44s more, then was killed. Total 4h33m24s non-contiguous. FINAL_STATUS = PARTIAL.
- **P1** `ai_trade_reviews` cannot be read back / re-run: `ExactDecimal` (String impl) vs migration
  `Numeric(38,18)`; SQLite stores `real`, so reads raise `DecimalError`. `list_reviews()` fails.
  Pre-existing (affects rows written 2026-09-15 too).
- **P1** Terminal deterministic exits (`RISK_HARD_EXIT`, `FAST_PROFIT_PROTECTION` 100%) close the
  position but leave the plan ACTIVE and create **no** `trade_episode`, so Growth reviews miss them.
- **P0 integrity** Port 8010 + the acceptance DB were taken over at 2026-09-16T16:29:09Z by a
  different SHA (`f319ecb`, `/Users/huhongjie/lowrisk-provider-durability`). DB writes after that
  boundary are not attributable to `1ef721d6d491`.

## Next
- Re-base the soak on a fresh, continuously-running window with a dedicated DB
  (single writer per acceptance window).
- Fix the `ai_trade_reviews` decimal round-trip and the missing episode on terminal exits.
