# OKX DEMO credential API contract required by the frontend

## Current state

The current FastAPI OpenAPI document exposes no OKX credential, status, or
connection-validation endpoint. The frontend therefore renders the DEMO-only
configuration form as a non-submitting shell and never persists credentials in
the browser.

The existing backend also has no historical Kline endpoint and its WebSocket
does not currently publish the required Kline envelope. The frontend preserves
the existing `/market/klines` request path and shows the explicit unavailable
state rather than generating sample candles.

## Existing Binance Kline contract

```http
GET /market/klines?symbol=BTCUSDT&interval=1m&limit=500
```

The backend response must contain `symbol`, `interval`, `source`, `status`,
`supported_intervals`, and decimal-string candles with `open_time`, `open`,
`high`, `low`, `close`, and `volume` fields.

The WebSocket must emit an envelope with `event_type: "kline"` and a payload
containing the same symbol, interval, and candle values. Until both interfaces
are available, frontend status remains `BACKEND_UNAVAILABLE`; it does not
synthesize price, funding, OI, or candle data.

## Required server-owned contract

The backend must own encryption, secret storage, credential validation, audit
logging, and all exchange communication. It must never return an API secret or
passphrase to the browser.

### `POST /exchange/okx/credentials`

Accept only over an authenticated, CSRF-protected transport:

```json
{
  "api_key": "...",
  "api_secret": "...",
  "api_passphrase": "..."
}
```

The endpoint stores encrypted values server-side for the fixed `DEMO`
environment. It returns no secrets.

### `GET /exchange/okx/status`

```json
{
  "provider": "OKX",
  "environment": "DEMO",
  "configured": true,
  "authenticated": true,
  "key_suffix": "ABCD",
  "account_mode": "...",
  "position_mode": "...",
  "health": "HEALTHY"
}
```

### `POST /exchange/okx/validate`

Validates stored DEMO credentials without returning raw exchange errors or
credentials. The response may report a safe status and a sanitized message.

No LIVE selector or live-trading enablement is part of this contract.
