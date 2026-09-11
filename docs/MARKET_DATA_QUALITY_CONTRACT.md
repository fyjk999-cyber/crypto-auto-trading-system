# Market Data Quality Contract

Implemented in `src/crypto_trader/market_data/quality.py`, enforced by
`OpportunityScannerService`, the factor detectors and the ChiefTrader tool registry.

## 1. Fact representation

```python
Fact(
    value,          # the factual value, or None when unusable
    source,         # provider/endpoint or derived-expression label
    observed_at,    # provider data time (per source)
    received_at,    # local receipt time
    unit,
    quality,        # one of the states below
    reason,         # human-readable, non-secret explanation
)
```

Quality states: `VALID`, `MISSING`, `STALE`, `FUTURE_TIMESTAMP`, `NON_FINITE`,
`REQUEST_FAILED`, `UNSUPPORTED`, `ESTIMATED`, `PARTIAL`, `MALFORMED`.

Only `VALID`, `ESTIMATED` and `PARTIAL` are usable for computation. No other state may
enter ranking, factor strength, liquidity comparison, OI change, turnover calculation or
market-selection context.

## 2. Funding contract

OKX public endpoint: `GET /api/v5/public/funding-rate`.

* `instId` is **required**; batch mode is `instId=ANY&instType=SWAP`
  (verified live: 657 rows returned; `instType` alone returns HTTP 400 / code `50014`
  "Parameter instId can not be empty").
* A batch failure yields `REQUEST_FAILED` for every symbol — never `0`.
* An instrument absent from a successful batch yields `MISSING`
  (a bounded per-instrument fallback is attempted first).
* `VALID funding = 0` is preserved as a real factual zero and is `usable`.
* Malformed/non-finite rates yield `MALFORMED` / `NON_FINITE`.

Evidence: `tests/opportunity/test_market_truth_gate1.py`,
`tests/opportunity/test_real_okx_public_gate5.py`.

## 3. Timestamp integrity

`timestamp_fact(raw_ms, now, max_age_seconds, max_future_skew_seconds)` returns
`(observed_at, quality, reason)` and distinguishes:

| Input | Quality |
|---|---|
| absent | `MISSING` |
| malformed / out of range | `MALFORMED` |
| NaN / ±Inf | `NON_FINITE` |
| more than `max_future_skew_seconds` ahead | `FUTURE_TIMESTAMP` |
| older than `max_age_seconds` | `STALE` |
| otherwise | `VALID` |

A future timestamp is **retained as raw truth** and never clamped to age 0.
Eligibility refuses a symbol whose ticker timestamp quality is not `VALID`
(`TICKER_TIMESTAMP_<STATE>` exclusion reason), so a future timestamp can never act as a
freshness proof.

Independent observed times are retained per source:
`ticker_observed_at`, `funding_observed_at`, `oi_observed_at`, `candles_observed_at`.

## 4. Numeric integrity

`numeric_fact(...)` rejects `NaN`, `+Inf`, `-Inf`, malformed decimals, and impossible
negatives/zeros. `_finite()` performs the same rejection for every provider row field.
Rejected values become `None` + a non-usable quality state — they are never coerced to 0.

## 5. Candle truth

`CandleTruth` reports:

```
requested_count, received_count, closed_count, unique_closed_count,
contiguous_tail_count, gap_count, latest_closed_at, quality, analysis_ready
```

Rules:

* only CLOSED candles (`confirm == "1"`) are accepted for historical factor computation;
* closed candles are deduplicated by open timestamp;
* temporal ordering is enforced (ascending);
* gaps (`> 1.5 × bar`) break the contiguous tail and set `quality = PARTIAL`;
* `analysis_ready` is driven by `contiguous_tail_count`, never by `requested_count`;
* `as_dict()["candles_available_is_requested_count"]` is always `False`.

Example: requesting 120 candles and receiving 20 closed usable ones is reported as
`requested=120, unique_closed=20, contiguous_tail=20, coverage_ratio=0.1667` — never as
"120 candles available" or `PREWARM_READY`.

## 6. Orderbook quantity wiring

The batch ticker supplies `best_bid_price`, `best_bid_size`, `best_ask_price`,
`best_ask_size`. `ORDERBOOK_IMBALANCE` therefore reports:

```
imbalance_scope = TOP_OF_BOOK
depth_semantics = "best bid/ask size only; full depth is an explicit tool request"
```

Full-depth imbalance is **not** claimed. If the factors ever require depth, it must come
from an explicit read-only tool call.

## 7. OI factual time series

`OiTimeSeries` stores timestamped samples (`symbol`, `open_interest`, `observed_at`,
`source`, `quality`) for the broad observable set — not only for symbols that receive
expensive candle analysis.

Windows are data-driven (`5m`, `15m`, `1h`; default `15m`) with explicit tolerance
(`15m ± 180s`). Change is measured against the sample closest to `T - window`:

* fewer than 2 samples, stale latest sample, or no baseline within tolerance
  → `OI_CHANGE_UNAVAILABLE` (`quality = UNSUPPORTED`);
* irregular "last N calls" are never compared as if elapsed time were equal.

## 8. Estimated turnover semantics

OKX SWAP tickers expose `vol24h` (contracts) and `volCcy24h` (base currency) — there is
no exact USD turnover field. The system derives

```
estimated_quote_turnover_24h = volCcy24h × last_price
quality = ESTIMATED
source  = "derived: OKX volCcy24h x last price"
```

It is never described as an exact historical OKX USD turnover field. Source units are
preserved in the facts.

## 9. Failure → quality mapping (fail closed)

| Failure | Reported state |
|---|---|
| tickers batch empty/error | snapshot `FAILED`, no candidates |
| OI batch error | `REQUEST_FAILED`; snapshot `PARTIAL` when other data exists |
| funding batch error | `REQUEST_FAILED` per symbol |
| candle request timeout | `REQUEST_FAILED` for that symbol, snapshot `PARTIAL` |
| instrument unsupported | `UNSUPPORTED` |
| derived approximation | `ESTIMATED` |
| partially usable group | `PARTIAL` |
