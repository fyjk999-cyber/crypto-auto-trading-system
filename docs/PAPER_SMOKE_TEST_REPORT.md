# PAPER SMOKE TEST REPORT — LLM Integration Takeover

- Run date: 2026-08-28 (UTC)
- Baseline: `7b746df09ba5a8e2e9e10cd676fa5d14a2535f10` (`NEW_RUNTIME_QUALIFICATION_BASELINE_SHA`, supersedes `20a4db8…`, which superseded `af9e393…`)
- Environment: local runner `crypto_trader.runtime.local_runner` on 127.0.0.1:8000, TRADING_MODE=PAPER, LIVE_TRADING_ENABLED=false, OKX_DEMO=true, SQLite (`data/crypto_trader.db`), LLM=deepseek/deepseek-chat via shared `LLMGateway` + encrypted SecretStore
- Verdict: **PAPER_SMOKE_TEST = PASS**

## 1. Test gate

- `uv run pytest` → **654 passed, 7 skipped, 0 failed** (skips: 4 documented bare-skips in test_canonical_runtime_bootstrap.py + 3 postgres-URL-conditional)
- `uv run ruff check .` → clean
- Frontend: 21 vitest tests PASS, `tsc --noEmit` + vite build PASS (node v24.19.0)
- Alembic single head: `0017_domain_model_evidence`

## 2. §6 Provider runtime qualification (live)

`./scripts/llm_runtime_qualification.sh` against the running backend, run three times across the session (04:18, 04:56, 04:55/05:18 restarts):

```text
live_analysis                 PASS deepseek/deepseek-chat ~2.0-2.9s
daily_review                  PASS ~1.9-2.4s
daily_lesson_extraction       PASS ~1.9-2.4s
evolution_research            PASS ~1.9-2.2s
evolution_hypothesis          PASS ~1.8-2.3s
evolution_candidate_reasoning PASS ~1.9-2.5s
LLM_PROVIDER_RUNTIME_VALIDATED=YES
```

## 3. Environmental repair (pre-smoke blocker, resolved)

`https://api.deepseek.com` was unreachable at TLS layer: local VPN/TUN answered DNS with a fake-IP (`198.18.0.4`, reserved benchmark range) and the intercepted route hung ClientHello. Fix (opt-in, default-off): `DoHNetworkBackend`/`DoHTransport` in `OpenAICompatibleProvider` resolves via a JSON-DoH endpoint (`LLM_DOH_RESOLVER`, set to `https://dns.alidns.com/resolve` in `.env`) and dials the real address; TLS SNI + certificate validation unchanged. Post-fix probe: HTTP 401 in 0.25s (unauthenticated), full probes 2× `ok=True` @ ~2s. Committed `efc25b1`.

## 4. §13–§14 Canonical chain, live proof

Correlated trace captured live (real invocations, not fixtures):

```text
llm_usage:            llm_1592425c716b404eb2f7701027b3d018  brain=LIVE route=live_analysis
                      provider=deepseek model=deepseek-chat success=1 605 tokens 3256ms
decision_evidence:    dec_b8c21a5ce4c843f39fc59022584c94ad  BTCUSDT
                      analysis_evidence.llm_invocation_id = llm_1592425c716b404eb2f7701027b3d018
```

Every completed ChiefTrader decision (NO_TRADE included) is persisted as DecisionEvidence (`SqlEvidenceBackend`, best-effort, never blocks trading) carrying `llm_invocation_id`, provider, domain model version (`7b746df`).

## 5. Smoke windows (live, continuous)

| Window | UTC | Duration | Decisions | LLM live_analysis | Notes |
|---|---|---|---|---|---|
| A | 04:54:36→05:00:30 | ~6 min | 6 (all NO_TRADE) | 7/7 success | post-restart, qualification run |
| B | 05:09:30→05:47 | ~37.5 min | 21 (all NO_TRADE) | 16/16 success during healthy phases | incl. §17 injection + OKX blip |

- Decision cadence ~65s (60s `min_decision_interval_seconds` + LLM latency) — token burn bounded; window B total ≈ 8.3k tokens.
- 27 decisions total, 100% structured-output validation success (route output schema examples + DecisionId anchoring fixed the earlier `invalid_response` class).
- Orders: 0, Fills: 0 — every decision NO_TRADE (no edge presented; honest absence, no forced trades).
- Ledger: intact (initial entries only); kill switch never engaged; reconciliation never halted; runtime state RUNNING throughout.
- Restart semantics: after restart the entry path stays dormant (fail-closed) until LLM health is verified (UNVERIFIED → qualification → HEALTHY → decisions resume). Documented operational step: run qualification after restart.

## 6. §17 LLM failure isolation — LIVE injection cycle

- 05:20:00 `PUT /llm/providers/deepseek {enabled:false}` → status NOT_CONFIGURED, route gate closes.
- 05:20:00→05:23:30 (3.5 min outage): runtime stayed `RUNNING`, health OK, reconciliation NOT halted, **0 LLM invocations, 0 decisions, 0 orders** (fail-closed, no token spend).
- 05:23:38 re-enable + `POST /llm/test` OK (2.3s) → health HEALTHY → decisions resumed 05:25:26 and 05:26:29 (~65s cadence), 3/3 subsequent invocations success.
- Earlier natural outage (pre-smoke, 04:3x): 86s timeouts → circuit breaker → fail-safe NO_TRADE; runtime unaffected (llm_usage rows retained).

## 7. Market-data environmental failure (observed, handled)

05:31→05:37 OKX resolution failed entirely (local VPN DNS instability; DoH confirmed real records still exist). Runtime: `market_data FAIL BTCUSDT invalidated`, overall UNHEALTHY, entry path dormant, **0 LLM invocations during outage** (no spend without market truth), ledger intact. Market recovered ~05:37; decisions auto-resumed (~05:43); health flag recovers on next WS orderbook ingest. Failure isolation holds in both directions (LLM path independent of market path).

## 8. §16 Closed-loop fixture (deterministic, synthetic)

`scripts/closed_loop_soak_smoke.py` (isolated temp DB, PAPER_SYNTHETIC, time-compressed):
`SOAK_SMOKE daily COMPLETED weekly_period 2026-W35 promotion ACTIVE` → `SOAK_SMOKE_OK`
(engine loop + evidence write + DailyReviewPipeline + weekly/hierarchical review + SafePromotionCoordinator dry-run).

## 9. §18 Daily learning smoke

- Scripted: pipeline COMPLETED (above).
- Live DB: `DailyReviewScheduler.run_once()` → `{'date': '2026-08-28', 'daily_pnl': '0', 'trade_count': 0, 'win_rate': '0', 'profit_factor': '999', 'llm_review': None}` — honest empty review (no trades exist).

## 10. §19 Evolution smoke

- Evolution routes qualified against the real provider (evolution_research / evolution_hypothesis / evolution_candidate_reasoning PASS).
- Hierarchical weekly review + promotion dry-run OK (closed-loop fixture). No candidates created/promoted (proposal-only, validation-required policy).

## 11. §12 Risk panel

`/risk` now returns derived `metrics` (effective_leverage from entry notional/equity, margin ratio 0 when flat, `current_drawdown`/`risk_multiplier` explicitly NOT_AVAILABLE) — frontend renders honest values (空仓 / 无保证金占用 / NOT_AVAILABLE), never fabricated numbers. No RiskEngine semantics changed (`e5e3711`).

## 12. Acceptance flags

```text
PAPER_SMOKE_TEST = PASS
LIVE_LLM_ACTUAL_INVOCATION = YES        (27 real decisions, correlated evidence)
STRUCTURED_LLM_OUTPUT_VALIDATED = YES   (27/27 parsed & schema-validated)
LLM_PROVIDER_RUNTIME_VALIDATED = YES
DECISION_EVIDENCE_WRITTEN = YES         (NO_TRADE included)
FAILURE_ISOLATION_VALIDATED = YES       (live injection + natural outages)
PAPER_ONLY_MAINTAINED = YES             (0 orders, 0 fills)
NEW_RUNTIME_QUALIFICATION_BASELINE_SHA = 7b746df09ba5a8e2e9e10cd676fa5d14a2535f10
```

## 13. 24H qualification decision

- PostgreSQL is not available on this machine (no psql/brew service/docker). Official 24H requires persistent PostgreSQL.
- Local network is environmentally unstable (VPN/TUN fake-IP DNS broke LLM TLS; later dropped OKX resolution entirely for ~6 min).
- Per §21: **24H_PAPER_QUALIFICATION_READY = NO**, **CHAPTER_10 = BLOCKED_BY_ENVIRONMENT** (environment only; no P0/P1 defect, no secret exposure, no protected-core redesign).
- Requirements to unblock: PostgreSQL `DATABASE_URL` + `./scripts/postgres_runtime_qualification.sh`, stable DNS (VPN rule fix for api.deepseek.com + okx, or `LLM_DOH_RESOLVER` already wired), then rerun smoke and start Chapter 10.
