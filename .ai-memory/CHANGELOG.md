# CHANGELOG

- 2026-08-26T04:24:25.048757+00:00: Final AI autonomous runtime wiring + forward shadow smoke.
- 2026-09-17T00:35+08:00: cron-49 daily Growth jobs against acceptance window #4
  (`1ef721d6d491`). Top-10 freeze PASS (`2026-09-17`, 10 rows, re-run `already_frozen=true`,
  first-freeze immutable) and Growth lifecycle review PASS (`written=2`, KORUUSDT SHORT
  `net_bps=-26.53927813163482` -> `[DEFECT, DEFECT]`). Runtime was found dead (clean stop
  2026-09-16 10:26:21 +08) and restarted DB-preserving; it was then killed at
  2026-09-16T16:29:09Z when a different SHA (`f319ecb`) took port 8010 and the SAME acceptance DB.
  The >=72h soak clock is therefore broken (4h33m24s non-contiguous) and FINAL_STATUS stays
  PARTIAL. New P1s recorded: `ai_trade_reviews` decimal round-trip raises `DecimalError` on read
  (blocks re-run and `list_reviews`), and terminal deterministic exits create no `trade_episode`.
