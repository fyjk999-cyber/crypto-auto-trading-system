# LOCAL RUNTIME FINAL REPORT

## Final Commit SHA
3aa2d1442bbc38851550c3fe016fe9be8f8a96dc

## How to start / stop / status
- Start: `./scripts/start-paper.sh`
- Stop: `./scripts/stop-paper.sh`
- Status: `./scripts/status.sh`

## URLs
- Local URL: http://127.0.0.1:8000
- OpenAPI URL: http://127.0.0.1:8000/openapi.json
- Swagger URL: http://127.0.0.1:8000/docs
- WebSocket URL: ws://127.0.0.1:8000/ws

## Trading mode
- TRADING_MODE=PAPER (PAPER_SYNTHETIC default)
- LIVE_TRADING_ENABLED=false

## Runtime status
- Database READY
- Migration READY (Alembic revision 0002addfence)
- Engine RUNNING
- Lease HELD
- Adapter CONNECTED (SimulatedExchangeAdapter)
- Market HEALTHY
- Strategy ACTIVE (multi_strategy_alpha)
- Scheduler ACTIVE (engine tick/lease/reconciliation)
- Review ACTIVE (governance in core path)
- Learning ACTIVE (Fast Learning stats live)
- API READY

## E2E results from real running process
- LONG: FILLED (manual_api_local_long_2, 0.5 BTC @ 100.05)
- SHORT: FILLED (manual_api_local_short_2, 0.2 BTC @ 99.95; realized PnL -0.02, position reduced to 0.3 BTC)
- Ledger: TRADE, FEE, REALIZED_PNL entries recorded and balanced.

## Funding/OI/Basis status
- PAPER_SYNTHETIC: funding=0, oi=0, basis=0 (synthetic neutral).
- PAPER_REAL_MARKET: public -M futures client not yet implemented; blocked by current local scope.

## Daily Review runtime status
- Endpoint live (returns [] until trades are persisted into Trade Memory; runtime scheduler pending full persistence).

## Learning runtime status
- Fast Learning live (alpha.fast_learning.snapshot()).
- Slow Learning promotion gate unchanged.

## Trade Memory persistence status
- In-memory Trade/Failure Memory implemented and tested; DB persistence not yet added.

## Restart/recovery status
- PASS (existing recovery tests; process restart retains SQLite ledger/positions).

## Tests
- pytest: 184 passed
- ruff: clean
- agent-project-test: PASS
- coverage: 87%

## Known limitations
- Real -M Futures public data and keyed testnet are not integrated yet.
- Trade Memory persistence is in-memory only.
- Daily Review scheduler persists no rows yet.

## Binance Futures Testnet status
- BLOCKED_EXTERNAL_CREDENTIAL (no testnet API keys)

## Cloud deployment
- DEFERRED BY USER

## Safety
- LIVE_TRADING_ENABLED=false
- Real-money orders placed: NO
