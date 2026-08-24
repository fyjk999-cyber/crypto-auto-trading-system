# Local UI installation report

## Scope

Cloud deployment is paused. This change installs the existing React/Vite UI in
`frontend/` and connects it to the local, existing FastAPI read endpoints. No
trading, alpha, risk, execution, order, ledger, or exchange-adapter backend
code was changed for this UI task.

## Start locally

In terminal 1, prepare the local SQLite directory once and start the existing
API:

```bash
cd /Users/huhongjie/Documents/ChatGPT/虚拟货币交易系统
mkdir -p data
uv run alembic upgrade head
uv run uvicorn crypto_trader.api.app:app --host 127.0.0.1 --port 8000
```

In terminal 2, start the UI:

```bash
cd /Users/huhongjie/Documents/ChatGPT/虚拟货币交易系统
./scripts/start-ui.sh
```

Open `http://127.0.0.1:5173/`.

The UI uses `http://127.0.0.1:8000` and `ws://127.0.0.1:8000/ws` by default.
During Vite development, same-origin proxy routes avoid requiring a backend
CORS change.

## Validation performed

- `npm install --no-audit --no-fund` completed and generated
  `frontend/package-lock.json`.
- `npm test`: 3 tests passed.
- `npm run build`: TypeScript check and Vite production build passed.
- Browser verification confirmed ten navigation routes, PAPER mode, a connected
  WebSocket while the local API was running, no browser-console errors, and
  no invented values.
- The existing API returned 200 for `/health`, `/ready`, `/runtime`,
  `/account`, `/positions`, `/orders`, and `/killswitch`; the UI treats missing
  optional endpoints as unavailable rather than fabricating a value.

## Existing backend gaps made visible

The following endpoints currently return 404 from the existing backend and
are displayed as unavailable: `/regime`, `/signals`, `/strategies`, `/risk`,
`/margin`, `/daily-reviews`, `/learning`, and `/exchange-health`.

The UI does not call any POST endpoint, does not call Binance directly, and
does not expose a kill-switch action.
