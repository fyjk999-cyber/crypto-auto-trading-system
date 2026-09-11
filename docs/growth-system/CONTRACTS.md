# Growth-system contracts

This file is the machine-verifiable contract index. Each contract names the
implementation, the tests that bind it and what it explicitly does **not**
promise.

## C1 — Financial truth (G01)

Implementation: `src/crypto_trader/governance/daily_review.py`,
`src/crypto_trader/governance/scheduler.py`,
`src/crypto_trader/governance/factual_learning.py`.
Tests: `tests/growth_system/test_financial_truth.py`.

| Rule | Contract |
| --- | --- |
| Per-trade net | `net = gross(realized) - fees + funding` |
| Aggregate | `DailyReviewStats.gross_pnl`, `.fees`, `.funding_pnl`, `.net_pnl` are separate fields; wins/losses/expectancy/win-rate/long-short use **net** |
| Funding provenance | A record with `funding_provenance` in `{PROVEN, KNOWN_ZERO, KNOWN_VALUE, SETTLED, NO_OP}` is complete; `UNKNOWN/UNPROVEN/INCOMPLETE/QUARANTINED` or missing provenance under `STRICT` is incomplete |
| Unknown funding | `net_pnl = null`, `net_status = INCOMPLETE_UNKNOWN_FUNDING`, `unknown_funding_count > 0`; the knowledge pipeline must not promote the day (C5) |
| Breakeven | `net == 0` increments `breakeven_count`, never win/loss |
| Profit factor | nullable ratio with `profit_factor_status ∈ {OK, NO_LOSSES, NO_SAMPLES, INCOMPLETE_FUNDING}`. `NO_LOSSES`/`NO_SAMPLES` → `null`. `999` is not allowed, and an amount is never substituted for a ratio |
| Compatibility layer | `legacy_metrics()` and `profit_factor_compat`/`win_rate_compat` return `Decimal("0")` for undefined values **together with** the status fields. `DailyReviewRunORM` non-null columns receive the same compatibility values while `output_ref` carries `net_status` and `pf_status` |
| Funding unknown is not zero | The legacy mirror `daily_pnl` may contain a partial value for an incomplete day but is always paired with a non-`COMPLETE` `net_status` |
| Factual episodes | `_episode_record` marks `funding_provenance="PROVEN"`; factual episodes only exist after `TradeEpisodeStore` proved single ownership + funding coverage |
| Legacy DB rows | The scheduler reads legacy `TradeMemoryRecordORM` under `STRICT`, so those days are reported incomplete rather than as complete net PnL |
| PF for factual aggregates | `factual_learning` stores `profit_factor_status` and `descriptive_only` in `applicability_scope_json`; `confidence_basis=SAMPLE_COUNT_ONLY`; review rows carry `CAUSAL_CLAIM:NONE` and `confidence=0` |

Not promised: a complete net figure when funding is unknown; a profit factor
when no loss sample exists; that “result descriptor” rows are causal
explanations (G02/G04 supersede them).

## C2 — Structured Review (G02)

Status: implemented in `src/crypto_trader/learning/growth_review.py`.
See the module docstring and `tests/growth_system/test_review_schema_and_refs.py`
for the exact schema/ref rules.

## C3 — Idempotent stages (G03)

Status: implemented in `src/crypto_trader/learning/growth_pipeline.py`.
See `CONCURRENCY_AND_INTEGRATION.md`.

## C4 — Knowledge promotion and compression (G04)

Status: implemented in `src/crypto_trader/learning/growth_knowledge.py`.

## C5 — Legacy import (G05)

Status: implemented in `src/crypto_trader/learning/growth_import.py` as
dry-run/isolated-copy only.

## C6 — Chief retrieval (G06)

Status: retrieval adapter in `src/crypto_trader/learning/growth_retrieval.py`;
production bootstrap wiring is an integration package (public file).
