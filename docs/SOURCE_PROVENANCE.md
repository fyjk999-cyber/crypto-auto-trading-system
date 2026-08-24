# SOURCE PROVENANCE

Reference repositories were READ-ONLY. Anything reused was copied out or ported
as semantics into this new project and then modified here. Nothing was ever
written back to a reference repository.

Reference baselines:
- SilverQuant: local archive `/Users/huhongjie/Downloads/SilverQuant-main` (no git metadata)
- kalshi-paper-trader (v1): commit `fadb6dd2ab7767829948d2ce7a9c5f49bf392c85`, branch `codex/v3-f1-weather-trace`
- kalshi-paper-trader-v2 (v2): commit `7cc5d25ca770be03e4098cdcc1b5da38659a398c`, branch `codex/v3-f1-weather-trace`

## SilverQuant

| Source path | New destination | Type | Changes made | Reason |
|---|---|---|---|---|
| `backend/app/core/clock.py` | `src/crypto_trader/domain/clock.py` | PORTED | Removed CN/HK session tables, T+1 day-change logic, qfq; kept Clock/SimClock deterministic step contract | Single time source and deterministic replay |
| `backend/app/core/gateway.py` | `src/crypto_trader/exchange/base.py` | INSPIRED | Removed synchronous `place_order()->Fill`; replaced with async adapter contract + normalized events; Decimal fields | ExecutionGateway abstraction, but crypto requires async order lifecycle |
| `backend/app/core/paper_broker.py` | `src/crypto_trader/simulator/exchange.py` | INSPIRED | Not copied; implemented as full ExchangeAdapter so paper and live share one core | Avoid a second trading core |
| `backend/app/data/sources/base.py` | `src/crypto_trader/market_data/service.py` | INSPIRED | Added snapshot+delta, sequence gap, resync, health | DataSource abstraction, extended for WebSocket-first crypto |
| `backend/app/data/providers.py` | `src/crypto_trader/exchange/binance.py` | INSPIRED | Provider chain/fallback idea kept; Binance transport implemented independently | Exchange replaceability |
| `backend/app/order/manager.py` | `src/crypto_trader/order/manager.py` | INSPIRED | Replaced frozen-sync state machine with 12-state async machine; added client_order_id idempotency, duplicate fill/event handling | OrderManager responsibility, but crypto semantics differ |
| `backend/app/risk/guard.py` | `src/crypto_trader/risk/engine.py` | INSPIRED | Removed A-share lot/T+1/price-limit/CNY-HKD rules; system-level crypto limits only | Risk separation |
| `backend/app/services/audit.py` | `src/crypto_trader/observability/audit.py` | INSPIRED | DB-first structured audit with run_id/order ids | Audit/trace |
| `backend/app/services/trace_db_store.py` | `src/crypto_trader/ledger/projections.py` | INSPIRED | Trace persistence idea generalized into ledger replay | Replayable audit |
| `backend/app/review/replay.py` | `src/crypto_trader/ledger/projections.py` | PORTED | Deterministic replay idea; implemented on append-only ledger | Rebuild projections after restart |

## Kalshi v1 (kalshi-paper-trader)

Used as context only in phase 0/1 for the historical paper-engine path. No code was
directly copied from the v1 working tree; the reusable v2 design files were read
from the v2 working tree (see below). The local v1 tree contained pre-existing
untracked files which were not touched.

## Kalshi v2 (kalshi-paper-trader-v2)

| Source path | New destination | Type | Changes made | Reason |
|---|---|---|---|---|
| `lib/v2/decimal.mjs` | `src/crypto_trader/domain/money.py` | PORTED | JS FixedDecimal semantics ported to Python `Decimal` with string-only parsing and float rejection | Decimal-safe core |
| `lib/v2/ledger.mjs` | `src/crypto_trader/ledger/service.py` + `projections.py` | PORTED | Atomic balanced journal and invariant kept; Kalshi paper settlement legs replaced with crypto spot buy/sell journals | Ledger-first atomic accounting |
| `lib/v2/execution-authority.ts` | `src/crypto_trader/execution/authority.py` | PORTED | Removed Kalshi signal/learning checks; kept lease/mode/kill/order-expiry/market-freshness/orderbook/balance/duplicate/precision/min-notional/rate-budget gates | Final authority before execution |
| `lib/v2/run-lease.ts` | `src/crypto_trader/runtime/lease.py` | PORTED | DB CAS lease instead of config table token; same renew/expire/recover contract | Single-writer engine |
| `lib/v2/orderbook.mjs` | `src/crypto_trader/market_data/orderbook.py` | PORTED | Normalized Decimal levels, sequence validation, invalidation/resync semantics | Reliable market data |
| `lib/v2/replay.mjs` | `src/crypto_trader/ledger/projections.py` | PORTED | Deterministic replay with ordering; JS hash not ported | Recovery/audit |
| `lib/v2/resting-order-ledger.ts` | `src/crypto_trader/order/manager.py` | INSPIRED | Resting order lifecycle + persisted events; crypto states and ack/fill reordering added | Async order lifecycle |
| `lib/v2/risk.mjs` | `src/crypto_trader/risk/engine.py` | INSPIRED | System-level risk limits list kept; Kalshi market categories removed | System risk only |
| `lib/v2/engine.ts` | `src/crypto_trader/runtime/engine.py` | INSPIRED | Single orchestration path; crypto event loop and adapter events added | Runtime pipeline |
| `lib/v2/run-observability.ts` | `src/crypto_trader/observability/` | INSPIRED | Structured logging + audit events | Observability |
| `tests/v2-domain.test.mjs`, `tests/v2-chaos.test.mjs`, `tests/v2-sqlite-integration.test.mjs`, `tests/v3-runtime-safety.test.mjs` | `tests/chaos/test_chaos.py`, `tests/integration/*` | PORTED (test cases) | Rewritten in Python for crypto invariants | Chaos/integration coverage |

## Completely new code
- `src/crypto_trader/domain/models.py`, `enums.py`, `identifiers.py`, `errors.py`
- `src/crypto_trader/persistence/` (exact-decimal SQLAlchemy type, all ORM models, DB)
- `src/crypto_trader/exchange/binance.py` REST signing/error mapping/WS stream
- `src/crypto_trader/exchange/okx.py`, `exchange/bybit.py` boundaries
- `src/crypto_trader/reconciliation/`
- `src/crypto_trader/runtime/event_bus.py`, `scheduler.py`, `health.py`, `state_machine.py`
- `src/crypto_trader/api/`
- `src/crypto_trader/strategy/`
- `migrations/`, CI, all Python tests
