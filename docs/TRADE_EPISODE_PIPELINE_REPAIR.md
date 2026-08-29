# Trade Episode / Learning Pipeline Repair (P2)

- Date: 2026-08-29
- Scope: CLOSED TRADE -> Trade Outcome Attribution -> AITradeEpisode Persistence -> Daily Review Input
- Constraint compliance: NO trading-architecture changes (Chief Trader / Risk / Execution / sizing / entry-exit policy / prompt untouched). Episodes derive ONLY from naturally completed trades; no synthetic fills, no forced closes, no second truth source.

## Verdict

```
TRADE_EPISODE_PIPELINE = OPERATIONAL
COMPLETED_TRADE_CYCLES > 0 = YES (37 episodes)
AI_TRADE_EPISODES > 0 = YES (37 rows in ai_trade_episodes)
EXIT_REASON_CLASSIFICATION = TIME_STOP preserved (never AI_EXIT)
PARTIAL_CLOSE_NOT_COMPLETE = ENFORCED (flat-to-flat only)
QUARANTINED_EXCLUSION = ENFORCED (EVIDENCE_QUARANTINE fill ids skipped)
IDEMPOTENT_BACKFILL = ENFORCED (stable episode key, replay = no-op)
DAILY_REVIEW_INPUT = WIRED (load_episodes reads completed episodes)
```

## Root cause of ai_trade_episodes = 0

`LLMMemoryStore.save_episode` existed but was **never called** by any runtime
path. `trade_memory_records` (76 rows) are per-fill entry captures captured at
ENTRY time — they are not completed trades. The closed-trade -> episode
transition simply did not exist.

## Fix architecture

### 1. New module: `src/crypto_trader/governance/trade_episodes.py`

Canonical `fills ⋈ orders` replay per symbol (time-ordered):

- entry fills = non-reduce-only; exit fills = reduce-only (join `orders`).
- A cycle is COMPLETE only when signed position returns to exactly 0.
- Quarantined fills (audit action `EVIDENCE_QUARANTINE`, target `fill_*`) are
  excluded before replay.
- Weighted average entry/exit price; closed size = min(entry, exit) qty.
- Fees = `SUM(fill.fee)` over the cycle (entry + exit; no double counting).
- Perp GROSS realized PnL = `FUTURES_REALIZED_PNL` ledger metadata for the
  closing order (canonical source); spot GROSS = deterministic rebuild
  `(exit_avg - entry_avg) * qty * direction`. NET = gross - fees.
- `result` = WIN / LOSS / BREAKEVEN on net.
- Exit-reason classification (priority order, honest fallback):
  1. exit fill `payload.exit_reason` (durable, new),
  2. audit `AI_EXIT_INTENT` rows keyed by exit order id (durable),
  3. legacy: all exit fills `strategy_id='ai_brain'` AND holding >= 4h window
     -> `TIME_STOP`; otherwise `UNKNOWN`. **TIME_STOP is never relabelled AI_EXIT.**
- `episode_id = eps-{sha1_24(symbol|market_type|entry_fill_ids|exit_fill_ids)}`
  — stable across replays; UNIQUE constraint dedupes.
- `lineage_json` = entry/exit order ids + fill ids + entry decision/signal id
  + timestamps + quantities + MAE/MFE (`NOT_AVAILABLE` accepted).
- `persist_episode_sync` = insert-or-update derived fields (deterministic
  re-derivation from canonical facts), so reruns converge.

### 2. Runtime wiring (close-time, not review-time)

- `RuntimeEngine._settle_fill` (spot): after portfolio refresh, when the
  symbol's position is flat -> `_record_trade_episode`.
- Perp path: after a reduce-only fill is applied -> `_record_trade_episode`.
- `_record_trade_episode` is exception-safe: any failure logs
  `TRADE_EPISODE_RECORD_FAILED` and never blocks the trading path.

### 3. Durable exit-reason correlation (write side)

- `AIPositionRuntimeBridge._submit_exit` now stamps the exit `SignalIntent`
  metadata with `exit_reason` ∈ {TIME_STOP, RISK_EXIT, AI_EXIT} (observability
  only; the decision conditions are unchanged).
- `RuntimeEngine` perp fill payload passes `exit_reason` through onto the fill.
- Bridge also logs audit event `AI_EXIT_INTENT` (order-id keyed) for
  exit-intent traceability.

### 4. Schema (idempotent, minimal)

`ai_trade_episodes` gains `market_type`, `direction`, `exit_reason`,
`gross_pnl`, `fees`, `net_pnl`, `lineage_json` (runtime `ALTER TABLE` guard +
ORM mapping). Legacy rows read fine; existing episode rows are updated in
place with derived fields on rerun.

### 5. Daily Review input

`LLMMemoryStore.load_episodes` reads completed episodes (ORM-mapped, tested).
The scheduler keeps ingesting `trade_memory` entry experiences; completed
`AITradeEpisode` rows are now the outcome unit available for review.

## Live-database evidence (deterministic backfill, 2026-08-29)

- 34 backfilled episodes + 3 created live by the runtime hook = **37 total**.
- LINKUSDT documented case: entry 07:25:48 @ 11.32, exit 11:25:53 @ 11.326,
  `exit_reason=TIME_STOP`, `holding_time_seconds=14405` (NOT AI_EXIT).
- BTCUSDT_PERP: two cycles, holdings 24210 s / 14401 s, net −0.611312 /
  −0.124806 sourced from `FUTURES_REALIZED_PNL` ledger metadata.
- ENAUSDT_PERP natural 4h exit at 14:17:11Z carried
  `payload.exit_reason=TIME_STOP` through bridge -> engine -> fill -> episode.
- exit_reason distribution: 37 x TIME_STOP (all natural 4h time-stops),
  0 x AI_EXIT, 0 x UNKNOWN among ai_brain exits.

## Tests (15 targeted, all passing)

1. TIME_STOP exit creates a single episode; replay is idempotent.
2. Entry-only position creates no episode.
3. Partial close stays open; full close completes exactly once.
4. Same symbol, two cycles -> two distinct episodes.
5. Multiple entry fills -> weighted average entry price.
6. LONG (spot) and SHORT (perp, canonical engine path) PnL signs + direction.
7. Episode fees equal SUM of canonical fill fees; net = gross − fees.
8. Runtime hook creates the episode on the closing fill.
9. Quarantined entry fill -> no episode (taint excluded).
10. Perp gross from FUTURES_REALIZED_PNL ledger metadata (canonical precedence).
11. `AI_EXIT` classification via exit fill payload.
12. Foreign-strategy exit -> honest `UNKNOWN`.
13. `lineage_json` auditability (order/fill ids, decision id, MAE/MFE markers).
14. Daily review can read completed episodes (`load_episodes`).
15. Episode key stable across unrelated new cycles and reruns.

Full integration suite: 111 passed / 4 skipped; ruff clean on all touched files.

## Statistics semantics (separate counts, per task §30)

- Fill / Order / Entry / Exit counts: canonical `fills` / `orders` tables
  (entries = non-reduce-only fills; exits = reduce-only fills).
- Open trade cycles: flat-to-flat cycles still in progress are NOT stored.
- Completed trade episodes: `ai_trade_episodes` rows (currently 37).
- AITradeEpisodes available to Daily Review: same table via `load_episodes`.
