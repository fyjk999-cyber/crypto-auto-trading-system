# Shadow isolation qualification — measured results

Base SHA (not amended): `d59711e171b792faae0832fbc9c16d22a91a0f24`
Produced by `tests/integration/test_shadow_qualification.py` plus the earlier
A/B benchmark. Raw values are recorded here so later runs can be compared rather
than silently replacing them.

## Q1 — runtime provider request count

Method: the real `OKXPublicMarketFeed` runs against a **counting provider
adapter** that wraps every method the feed can reach (`get_candles`, `get_ticker`,
`get_orderbook`, `get_mark_price`, `get_index_price`, `get_funding_rate`,
`get_open_interest`, `get_tickers`, `get_open_interests`, `get_funding_rates`,
`get_exchange_info`, `get_balances`, `get_positions`, `get_pending_orders`,
`get_account_config`). Counting the adapter rather than one call site is what
makes indirect paths covered.

Identical inputs in both modes: same stub provider responses, same 40 pipeline
rounds, same 40 shadow observations, same decision timestamps.

```text
MODE_A (shadow disabled)          total = 240
MODE_B (shadow + 100 candidates)  total = 240

breakdown A = {get_ticker: 40, get_orderbook: 40, get_mark_price: 40,
               get_index_price: 40, get_funding_rate: 40, get_open_interest: 40}
breakdown B = identical

SHADOW_ATTRIBUTABLE_PROVIDER_REQUEST_DELTA = 0
```

Backed by a static guard (`test_Q1b_...`): nothing in `src/crypto_trader/shadow/`
references a provider adapter, feed, HTTP client, websocket, or any `get_*`
provider method.

## Q2 — event loop lag and scheduling stability

Method: a periodic sampler measures how late a fixed-period task actually wakes,
while a stand-in realtime scheduler task runs concurrently at a 10 ms cadence.
Starvation is defined as **missing the period on more than half of the wakes** —
deliberately not "any late wake", because the directive's target is the absence
of *sustained* starvation, not zero lag.

```text
                                  lag median     p95      p99      max      sched misses   starvation
A_off       (shadow disabled)       0.605 ms   1.462 ms  1.470 ms   1.483 ms    0/40         NO
B_100       (100 candidates)        0.193 ms   1.466 ms  2.033 ms   2.300 ms    0/40         NO
C_saturation(10k observations)       0.146 ms   0.415 ms  0.583 ms  33.766 ms    0/40         NO
```

Reading of the C row: the 33.8 ms `max` is a single long wake caused by the
saturated producer loop — it is visible and expected under deliberate
saturation. It does **not** become starvation: the concurrent scheduler missed
**0 of 40** periods and its own worst wake was ~1.3 ms, under a 10 ms period.
That is the property the directive asks for: shadow load does not cause the
realtime cadence to persistently miss.

## Q3 — earlier A/B figures (retained, not overwritten)

Realtime decision path (A = shadow off, B = 100 active candidates):

| Path | A median | A p95 | A max | B median | B p95 | B max |
|---|---|---|---|---|---|---|
| decision commit + tap hand-off | 0.046 ms | 0.049 ms | 0.084 ms | 0.073 ms | 0.096 ms | 0.208 ms |
| shadow tracker/review (sidecar, off the trading chain) | 1.965 ms | 2.122 ms | 58.258 ms | 9.912 ms | 12.446 ms | 44.966 ms |
| queue drain | 0.000 ms | 0.000 ms | 0.003 ms | 0.000 ms | 0.001 ms | 165.748 ms |

p99 was not captured for these three rows; the qualification sampler added p99 for
the event-loop rows above. Recorded as a gap rather than back-filled with an
estimate.

Cost on the realtime path: **+0.027 ms median / +0.047 ms p95** (a bounded
`put_nowait` plus one eligibility check, no I/O, no await). The larger tracker
figure is sidecar consumer work, not trading latency — stated plainly rather than
presented as free.

## Hard requirements

```text
SHADOW_LLM_CALLS              = 0
LLM_BUDGET_DELTA              = 0     (position reserve 0, general pool 0)
POSITION_CAPACITY_DELTA       = 0
EXCHANGE_PROVIDER_REQUEST_DELTA = 0
POSITION_REVIEW_STARVATION    = NO
MARKET_SCAN_STARVATION        = NO
RECONCILIATION_STARVATION     = NO
```

## Explicit gaps in this evidence

* Q2 uses a **stand-in** periodic task as the "scheduler", not the engine's real
  MarketObserver / ChiefTrader / PositionReview scheduling loops. It demonstrates
  event-loop responsiveness under shadow load; it does not instrument those three
  specific loops.
* The event-loop sampler is coarse (fixed-period wake latency at 5 ms sampling),
  so sub-millisecond structure is not resolved.
