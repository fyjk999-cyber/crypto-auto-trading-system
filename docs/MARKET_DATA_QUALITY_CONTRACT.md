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
`REQUEST_FAILED`, `UNSUPPORTED`, `NOT_SAMPLED`, `ESTIMATED`, `PARTIAL`, `MALFORMED`.

`UNSUPPORTED` and `NOT_SAMPLED` are deliberately different:

| State | Meaning |
|---|---|
| `UNSUPPORTED` | the provider/instrument/field combination fundamentally cannot supply the fact (capability limitation) |
| `NOT_SAMPLED` | the fact IS supported but was not collected in this bounded cycle (coverage decision) |

A rotating coverage gap must never be reported as provider incapability or as a
runtime failure, and DeepSeek must never read "not collected this cycle" as
"this market has no such fact".

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

## 6a. Missing vs zero at the provider boundary

The OKX client passes provider fields through unchanged — a missing field is
`None`, never a defaulted string:

```python
raw = data["data"][0]
return {
    "open_interest": raw.get("oi"),        # None when absent
    "open_interest_ccy": raw.get("oiCcy"),
    "open_interest_usd": raw.get("oiUsd"),
    "source_timestamp": raw.get("ts"),
}
```

Downstream classification then decides:

| Provider value | Result |
|---|---|
| `"0"` | `VALID` zero (a real factual zero) |
| field absent | `MISSING` (or `NOT_SAMPLED` when simply not collected) |
| `"abc"` / negative | `MALFORMED` |
| `"NaN"` / `"Infinity"` | `NON_FINITE` |

A missing provider value can never become a `VALID` zero.

OI provenance strings name the real endpoint: `OKX /api/v5/public/open-interest`
(plural `open-interests` appears only in documentation of the invalid-path test).

## 6b. Open interest contract (live-verified)

`GET /api/v5/public/open-interest?instType=SWAP` (no `instId`) is the broad form
and returns one row per instrument. Live verification at correction time:

```
HTTP 200 · code 0 · 478 rows · 463 of them -USDT-SWAP (the whole discovery universe)
fields: instId, instType, oi (contracts), oiCcy (base ccy), oiUsd (notional), ts
```

Notable contract details, all observed directly:

| Request | Result |
|---|---|
| `/api/v5/public/open-interest?instType=SWAP` | works (broad) |
| `/api/v5/public/open-interest?instType=SWAP&instId=<real>` | works (single) |
| `/api/v5/public/open-interest?instType=SWAP&instId=ANY` | code 51001 — `ANY` is NOT valid for OI (it IS valid for funding) |
| `/api/v5/public/open-interests?instType=SWAP` (plural path) | HTTP 404 |

So the primary source is ONE broad request; per-instrument calls remain only as a
bounded fallback for instruments absent from a successful broad response, and
`oi_sample_max_symbols` now bounds that fallback (not a 120-symbol rotation).

## 7. OI factual time series

`OiTimeSeries` stores timestamped samples (`symbol`, `open_interest`, `observed_at`,
`source`, `quality`) for the broad observable set — not only for symbols that receive
expensive candle analysis.

Windows are data-driven (`5m`, `15m`, `1h`; default `15m`) with explicit tolerance
(`15m ± 180s`). Change is measured against the sample closest to `T - window`:

* samples keep the **provider observation timestamp** (`oi_observed_at` from the
  OKX payload), never the scan start time; identical provider timestamps
  deduplicate so a re-published instant cannot fake an acceleration;
* a provider OI of exactly `0` is a VALID factual sample and is stored; a zero
  baseline yields `MISSING` (`ZERO_BASELINE`) rather than dividing by zero;
* a negative or non-finite value never enters the series.

Window-change quality maps evidence limitations to evidence states, reserving
`UNSUPPORTED` for genuine capability absence:

| Situation | Quality | Reason marker |
|---|---|---|
| unimplemented window (e.g. `7h`) | `UNSUPPORTED` | `unknown OI window` |
| fewer than 2 timestamped samples | `MISSING` | `INSUFFICIENT_HISTORY` |
| no sample before the latest | `MISSING` | `NO_COMPARABLE_BASELINE` |
| nearest baseline outside tolerance | `MISSING` | `NO_BASELINE_IN_WINDOW` |
| baseline OI is zero | `MISSING` | `ZERO_BASELINE` |
| latest sample older than the window | `STALE` | `STALE` |
| non-finite sample value | `NON_FINITE` | `NON_FINITE` |

Comparison always selects the factual sample closest to `T - window` within the
configured tolerance; scan iteration numbers, array positions and request counts
are never used as time.

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
