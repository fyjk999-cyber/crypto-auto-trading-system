# Backend integration status

## UI V2 blocking market contract

The latest backend exposes `/market` and `/market/sources`, but its OpenAPI has
no historical Kline endpoint and `/ws` currently emits only `runtime` events.
The V2 UI therefore shows real market summary values when available while the
candlestick area remains explicitly unavailable.

Required REST contract:

```http
GET /market/klines?symbol=BTCUSDT&interval=1m&limit=500
```

```json
{
  "symbol": "BTCUSDT",
  "interval": "1m",
  "source": "BINANCE_USDM_PUBLIC",
  "status": "HEALTHY",
  "supported_intervals": ["1m", "5m", "15m", "1h", "4h", "1d"],
  "candles": [
    {
      "open_time": "ISO-8601 timestamp",
      "open": "decimal string",
      "high": "decimal string",
      "low": "decimal string",
      "close": "decimal string",
      "volume": "decimal string",
      "close_time": "ISO-8601 timestamp"
    }
  ]
}
```

Required incremental WebSocket envelope:

```json
{
  "event_type": "kline",
  "event_version": "v1",
  "timestamp": "ISO-8601 timestamp",
  "payload": {
    "symbol": "BTCUSDT",
    "interval": "1m",
    "open_time": "ISO-8601 timestamp",
    "open": "decimal string",
    "high": "decimal string",
    "low": "decimal string",
    "close": "decimal string",
    "volume": "decimal string",
    "closed": false
  }
}
```

Frontend status: `BLOCKED_BACKEND_API` for REST candles and
`BLOCKED_BACKEND_EVENT` for realtime candle updates. No sample or random
candles are used.

The local UI uses existing read-only endpoints: `/health`, `/ready`, `/runtime`, `/account`,
`/positions`, `/orders`, `/killswitch`, and `/ws`.

| Endpoint | UI need | Current result | Expected DTO / impact |
|---|---|---|---|
| `/regime` | Current regime | 404 | Regime, source timestamp, confidence. Overview and signal context show `Not available yet`. |
| `/signals` | Trade evidence / WHY THIS TRADE | 404 | Votes, weights, confidence, leverage path, risk flags, stress result. No client calculation is performed. |
| `/strategies` | Live strategy status | 404 | Effective weight, direction, confidence, reason codes, ML Meta. |
| `/risk` | Portfolio risk state | 404 | Drawdown, multiplier, exposure, leverage, rejects. |
| `/margin` | Position margin and liquidation | 404 | Initial/maintenance margin, liquidation price/distance, funding PnL. |
| `/daily-reviews` | Daily review | 404 | Performance and failure attribution. |
| `/learning` | Learning state | 404 | Candidate/promotion state. |
| `/exchange-health` | Exchange health | 404 | REST/WS health and freshness. |

The UI does not synthesize values for these interfaces and no backend trading-core file was changed.
