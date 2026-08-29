# OKX PUBLIC MARKET CAPABILITY MATRIX

Long-Goal §4 deliverable. Built from a LIVE audit of `https://www.okx.com/api/v5`
on 2026-08-29 (not from memory) plus a code audit of
`src/crypto_trader/exchange/okx.py` + `src/crypto_trader/market_registry/`.

Scope = public **market/instrument/price/liquidity/derivatives/history** data
only. Account/wallet/earn/payment APIs are out of scope by definition (§4).

Legend: [S]=Supported by OKX, [I]=Implemented in repo, [P]=Persisted,
[RT]=Realtime path, [H]=Historical path, [AI]=Feeds AI decisions,
[RS]=Feeds research/evidence only.

## 1. Instrument discovery

| Endpoint / Dataset | S | I | P | Notes |
|---|---|---|---|---|
| `/public/instruments?instType=SPOT` (1383 live) | ✓ | ✓ | ✓ `okx_instruments` | registry truth source |
| `/public/instruments?instType=SWAP` (459) | ✓ | ✓ | ✓ | 458 live + 1 preopen |
| `/public/instruments?instType=FUTURES` (187) | ✓ | ✓ | ✓ | dated futures |
| `/public/instruments?instType=OPTION&uly=...` | ✓ | count only | underlying count | research-only (§51) |
| `/public/underlying?instType=OPTION` | ✓ | ✓ | count | 4 underlyings at audit |
| `/public/instruments?instType=MARGIN` (196) | ✓ | not yet | – | Phase C candidate |
| Persisted fields | | ✓ | ✓ | instId, instType, uly, instFamily, baseCcy, quoteCcy, settleCcy, state, tickSz, lotSz, minSz, ctVal, ctValCcy, ctType, lever, expTime, listTime |
| Refresh path | | ✓ | ✓ | `python -m crypto_trader.market_registry.refresh` (OPS-only; never runtime DDL/DML) |
| Delisting handling | | ✓ | ✓ | absent instrument → state=DELISTED; excluded from tradeable universe (§52) |

## 2. Realtime market data

| Dataset | S | I | P | RT | AI | RS |
|---|---|---|---|---|---|---|
| Ticker single (`/market/ticker`) | ✓ | ✓ | engine cache | ✓ | ✓ | ✓ |
| **Tickers batch per class** (`/market/tickers?instType=`) | ✓ | ✓ | – | Layer-1 scan | ✓ | ✓ |
| Orderbook (`/market/books`) | ✓ | ✓ | engine cache | ✓ | ✓ | – |
| Trades snapshot (`/market/trades`) | ✓ | ✓ | – | ✓ | ✓ | ✓ |
| Mark price (`/public/mark-price`) | ✓ | ✓ | engine marks | ✓ | ✓ | – |
| Index tickers (`/market/index-tickers`) | ✓ | ✓ | – | ✓ | ✓ | ✓ |
| Funding rate (`/public/funding-rate`) | ✓ | ✓ | – | ✓ | ✓ | ✓ |
| Open interest single | ✓ | ✓ | – | ✓ | ✓ | ✓ |
| **Open interest batch** (`/public/open-interest?instType=SWAP`, incl. oiUsd) | ✓ | ✓ | – | ✓ | ✓ | ✓ |
| 24h stats (open/high/low/vol/volCcy/sodUtc0/8) | ✓ | ✓ (via tickers batch) | – | ✓ | ✓ | – |
| Basis (mark vs index) | ✓ | derivable | – | – | ✓ | ✓ |
| **WebSocket public channels** (tickers/books/trades/mark-price/funding-rate) | ✓ | partial (existing okx_public_data/ws layer) | cache | planned expansion | – | – |

## 3. Historical data (on-demand / backfill — §8)

| Dataset | S | I | H | Notes |
|---|---|---|---|---|
| Candles (`/market/candles`) | ✓ | ✓ | ✓ | hot recent context |
| History candles (`/market/history-candles`) | ✓ | ✓ | ✓ | paginated after/before |
| History trades (`/market/history-trades`) | ✓ | ✓ | ✓ | paginated |
| Funding rate history (`/public/funding-rate-history`) | ✓ | ✓ | ✓ | paginated |
| Mark/index candles | ✓ | not yet | – | Phase C candidate |
| Rubik stats (`/rubik/stat/taker-volume` etc.) | ✓ | not yet | – | Phase C candidate |

## 4. Universe layers (§10)

| Layer | Source |
|---|---|
| ALL MARKET | `okx_instruments` (SPOT 1383 / SWAP 458 / FUTURES 187 live at audit; option underlyings counted) |
| OBSERVABLE UNIVERSE | live + quote filter (SPOT USDT live = 395 at audit) + data-quality health |
| ACTIVE ANALYSIS UNIVERSE | Layer-1 batch tickers scan (cheap factual) |
| AI CANDIDATES | Market Observer AI (ATTENTION AUTHORITY — never a quant top-K gate, §11/§12) |
| TRADE CANDIDATES | Chief Trader AI decisions → Risk → Execution |

## 5. Capability status indicators (§91)

- `OKX_INSTRUMENT_DISCOVERY = READY` (live audit + persisted registry + refresh path)
- `OKX_PUBLIC_MARKET_DATA = PARTIAL` (batch tickers/OI/candles/trades/funding implemented; websocket expansion, mark/index candles, rubik pending)
- `DYNAMIC_MARKET_UNIVERSE = PARTIAL` (registry live; runtime wiring for universe feed = Phase C/D)

## 6. Rate-limit doctrine (§55/§56)

Batch endpoints FIRST (tickers/OI per class = 1 call per class), websocket for
high-frequency, REST only for snapshot/recovery/history. Per-symbol REST
polling loops across the whole universe are PROHIBITED.

## 7. Data quality (§53)

Missing fields stay NOT_AVAILABLE. Cross-symbol fallback (e.g. BTC price for
another symbol) is PROHIBITED and covered by regression tests. The resolver
never invents an instrument mapping; registry-checked resolution fails loud.
