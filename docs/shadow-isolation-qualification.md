# Shadow isolation qualification — current evidence

Candidate: `2dd172f435d5866a1cf06d7ad5ea685f65643c8d` (production unified base)
Measurement: `tests/integration/_shadow_isolation_probe.py`, executed in its **own
subprocess** by `tests/integration/test_shadow_runtime_isolation.py`.

Values below are from a real run of that probe, not estimates.

## Why the probe runs out of process

The heavy measurements (10,000 observations, saturated event loop, deadline
schedulers) create real asyncio load. Run inside the shared pytest process they
left background tasks alive and perturbed **unrelated** tests
(`test_research_attention_authority`, `test_engine_authority_end_to_end`)
depending on collection order. A flaky test that breaks other tests is worse than
no test, so the measurement runs in its own interpreter and the pytest file
asserts on the parsed JSON.

## Q1 — provider request count

Both modes perform **identical** market-data work; only the shadow sidecar
differs. The counter patches the feed class, so feeds created indirectly are
counted too.

```text
                    provider_requests   breakdown
MODE A  (disabled)          6           _refresh_ticker 1, _refresh_book 1,
                                        _refresh_mark 1, _refresh_index 1,
                                        _refresh_funding 1, _refresh_oi 1
MODE B_100 (100 candidates) 6           identical
MODE C_SATURATION (10k)     6           identical

SHADOW_ATTRIBUTABLE_PROVIDER_REQUEST_DELTA = 0
```

**Non-vacuity guard, and why it was necessary.** The counter pre-populates one
key per patched feed method, so a non-empty breakdown proves nothing. The probe
originally never drove the market-data path at all, so *every* mode reported 0
and the delta passed for the wrong reason. The probe now exercises the real feed
once per mode through an offline stub client, and the guard asserts for every mode
that at least one instrumented method fired, that **all** of them fired, and that
the total is non-zero.

The guard was verified by falsification: with the provider exercise temporarily
disabled the guard **fails** (`len([]) == 0`); with it restored the file passes
10/10.

## Q2 — event loop lag

Sampled in-process by the probe; units are microseconds.

```text
                        median     p95      p99      max
MODE A  (disabled)      0.603 us  0.702 us 0.758 us 0.763 us
MODE B_100              0.682 us  0.705 us 0.748 us 0.758 us
MODE C_SATURATION       0.576 us  0.699 us 0.738 us 0.773 us
```

## Q2b — scheduling under saturation (10,000 observations)

Real `DeadlineScheduler` instances for the three realtime cadences run concurrently
with the saturation workload:

```text
POSITION_REVIEW   runs 25   misses 0
MARKET_SCAN       runs 10   misses 0
RECONCILIATION    runs  5   misses 0
```

```text
POSITION_REVIEW_STARVATION = NO
MARKET_SCAN_STARVATION     = NO
RECONCILIATION_STARVATION  = NO
```

## Q3 — tap cost on the decision path

```text
MODE B_100        tap median 0.0098 ms   p99 0.0313 ms   (100 samples)
MODE C_SATURATION tap median 0.0097 ms   p99 0.0237 ms   (10000 samples)
```

Per-observation cost does not grow between 100 and 10,000 observations, i.e. it is
flat rather than quadratic.

## Scope of these claims — do not overstate

This evidence shows that under heavy shadow load **there is no sustained event
loop starvation**, and that the shadow sidecar adds **no** provider requests. It is
an in-process, instrumented measurement inside a dedicated subprocess.

It is **not** production runtime telemetry: it is not collected from the running
PAPER deployment, and the schedulers exercised are dedicated `DeadlineScheduler`
instances standing in for the realtime cadences rather than the production loops
being individually instrumented.

## Isolation invariants (asserted elsewhere, unchanged by this work)

```text
SHADOW_LLM_CALLS              = 0
SHADOW_PROVIDER_REQUEST_DELTA = 0
SHADOW_POSITION_CAPACITY_DELTA = 0
SHADOW_ACCOUNTING_DELTA       = 0
SHADOW_REAL_ORDER_WRITES      = 0
SHADOW_REAL_FILL_WRITES       = 0
SHADOW_REAL_POSITION_WRITES   = 0
```

## Versioning

Superseded prototype: `ecf40f5c8b7e6c7dcc2191fa819532abfa2544b3` — an earlier
qualification branch whose provider count was vacuous and whose saturation
measurement ran inside the shared pytest process. Retained as history only; it is
not a deployment candidate.

Current work lives on `qualification/final-unified-evidence`, based on
`2dd172f435d5866a1cf06d7ad5ea685f65643c8d`, and carries **no production `src/`
change**.
