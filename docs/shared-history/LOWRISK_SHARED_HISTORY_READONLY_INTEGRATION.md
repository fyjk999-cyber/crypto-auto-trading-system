# LOWRISK ⇄ SHARED MARKET HISTORY — READ-ONLY INTEGRATION

Status: ENGINEERING COMPLETE (not deployed)
Baseline: `6ced1da3008edf49eac086596ff4f208ee7b0821` (the factually running PAPER runtime)
Deployment: **not authorized** — `LOWRISK_SHARED_HISTORY_ENABLED = false` in production

## 1. What this adds

The single seam through which LowRisk can read the shared factual historical market
data source. It is a landing/integration change only: no strategy, risk, sizing,
leverage, execution, DeepSeek, Factor, Expert, ML or Growth semantics are touched.

| Path | Change |
| --- | --- |
| `src/crypto_trader/shared_history/` | new read-only client + evidence adapter |
| `src/crypto_trader/config.py` | five new Settings fields, `shared_history_enabled: bool = False` |
| `tests/shared_history/` | 83 deterministic tests |
| `scripts/shared_history_probe.py` | runtime acceptance probe (read-only) |

Nothing else in the runtime was modified. There is no change to any factor formula,
ML feature schema, Risk threshold, provider state or execution path.

## 2. Architecture position

```
OKX  ->  Shared Market History Service (sole writer)  ->  Parquet + DuckDB
                                                              |
                                                    localhost read API :8770
                                                              |
                        LowRisk SharedHistoryClient  <- GET only, loopback only
                                                              |
                       SharedHistoryEvidence (bounded cache, provenance, as-of)
                                                              |
                              EVIDENCE ONLY  ->  Factor / Expert / ML / Growth
```

Authority is unchanged and one-directional:

* **Shared History** supplies historical market facts. It holds no direction, risk,
  position, sizing, leverage, order or exit authority.
* **DeepSeek Chief** remains LowRisk's directional authority.
* **Risk** remains LowRisk's hard safety authority.
* **Execution** keeps its existing PAPER authority.

## 3. Reuse, not duplication

The consumer client already existed in the Shared Market History project and had
already been accepted ("Low-Risk client PASS"). It is **reused**, not rewritten:

    source : src/shared_market_history/clients/base.py
             src/shared_market_history/clients/lowrisk/client.py
    repo   : crypto-auto-trading-system (shared-market-history project)
    HEAD   : 8fcb90a77705e28c308d0dd25717996a2572f5d2
    blob   : base.py 5b95f5748a29f6f6a6b8425ca4716621cf4f31b6
             lowrisk/client.py 8bb105c7ea0dddc39ba0ea673f56ce216826fc17

Because the producer package is not a LowRisk dependency and must not become one
(§ "consumers never learn storage internals"), the client is vendored by source with
its provenance recorded in the module header. Exactly two changes were made, both
required by this integration's contract:

1. The POST transport and the three `batch_*` methods that used it are removed —
   the LowRisk path is GET-only.
2. Loopback-only URL enforcement is added — the source client accepted any host.

Everything else (method names, parameters, query construction, the informational
`X-Consumer: lowrisk` header, timeout handling, exception types) is preserved. No
duplicate client was written.

## 4. Read interface

`SharedHistoryClient` / `SharedHistoryEvidence` expose the full required interface:

`health()` · `universe()` · `latest_candles(symbol, timeframe, limit)` ·
`historical_candles(symbol, timeframe, start, end)` · `features(symbol)` ·
`regime(symbol)` · `funding(symbol)` · `open_interest(symbol)`
(plus `metadata`, `stats` and `analogs`, which are GET reads already in the contract)

Transport: GET only, loopback only, `X-Consumer: lowrisk` as an informational header
that grants no permission.

## 5. Failure semantics

Failures never become numbers.

| Condition | Result |
| --- | --- |
| feature flag off | `DATA_UNAVAILABLE`, reason `SHARED_HISTORY_DISABLED`, no I/O |
| service unreachable | `DATA_UNAVAILABLE`, reason `SHARED_HISTORY_UNREACHABLE` |
| HTTP error (incl. the 500 defect) | `DATA_UNAVAILABLE`, reason `SHARED_HISTORY_HTTP_ERROR` |
| malformed payload | `DATA_UNAVAILABLE`, reason `SHARED_HISTORY_MALFORMED_PAYLOAD` |
| empty series | `DATA_UNAVAILABLE`, reason `NO_ROWS_FOR_REQUEST`, zero rows |
| fact after `decision_as_of` | whole payload rejected, reason `FUTURE_DATA_LEAKAGE_REJECTED` |

Invariants held and tested: `UNAVAILABLE != ZERO`, `STALE != FRESH`,
`PARTIAL_HISTORY != COMPLETE`. An unavailable result carries no rows at all, so a
caller cannot mistake an outage for a flat market.

## 6. Temporal integrity

For a decision at `decision_as_of` no fact after that instant is ever returned:

* `end` is clamped to `decision_as_of` before the request is sent;
* `as_of` is forwarded to the service;
* any payload whose row timestamps **or** envelope `max_source_timestamp` postdate
  the decision instant is rejected whole — never silently trimmed.

`SHARED_HISTORY_FUTURE_ROWS_VISIBLE = 0`, with a counter proving rejection fires.

## 7. Bounded reads and bounded cache

Row limits are clamped to 10 000 and time ranges are bounded. The cache has an
explicit TTL, an explicit entry bound with eviction, and retains source, freshness,
schema version and read time on every hit. Expired entries are refetched; a failed
refetch yields `DATA_UNAVAILABLE` rather than an unlabelled stale value. Failed and
empty reads are never cached. Full multi-year or full-market history is never
materialised into LowRisk.

## 8. Enabling it

The production default is off, so the untouched runtime performs no shared-history
I/O and its trading behavior is unchanged:

```python
shared_history_enabled: bool = False          # production default
shared_history_base_url: str = "http://127.0.0.1:8770"
shared_history_timeout_seconds: float = 20.0
shared_history_cache_ttl_seconds: float = 60.0
shared_history_cache_max_entries: int = 256
```

Enable it only inside an isolated integration candidate during acceptance. The
existing LowRisk settings mechanism is reused; no duplicate flag was introduced.

```python
from crypto_trader.shared_history import shared_history_from_settings

evidence = shared_history_from_settings()          # honours the flag
candles = evidence.latest_candles("BTCUSDT", "1h", decision_as_of=now_ms)
if candles.available:
    ...  # evidence only
else:
    ...  # DATA_UNAVAILABLE: no direction, risk or execution change
```

## 9. Write and administrative prohibition

The integration cannot write. Proven statically and at runtime:

    LOWRISK_SHARED_HISTORY_WRITE_PATHS            = 0
    LOWRISK_SHARED_HISTORY_ADMIN_PATHS            = 0
    LOWRISK_DIRECT_PARQUET_PATHS                  = 0
    LOWRISK_DIRECT_DUCKDB_PATHS                   = 0
    LOWRISK_CHECKPOINT_MUTATION_PATHS             = 0
    NO_INSERT_NO_UPDATE_NO_DELETE_NO_ALTER        = PASS
    NO_POST_NO_PUT_NO_PATCH_NO_DELETE_HTTP        = PASS
    LOWRISK_WRITABLE_FDS_ON_SHARED_HISTORY        = 0
    LOWRISK_DIRECT_FDS_ON_SHARED_HISTORY          = 0

There is no Parquet append/overwrite/delete, no DuckDB DDL/DML, no checkpoint
mutation, no backfill, no ingestion, no retention, no compaction, no repair, no
pruning, no metadata mutation and no writer-lock acquisition.

## 10. Runtime acceptance probe

`scripts/shared_history_probe.py` exercises the whole read contract against the live
service while sampling its own descriptors. It is read-only and safe against
production. It embeds positive controls, so a reported zero is self-justifying:

```
python scripts/shared_history_probe.py --selftest      # controls must pass
python scripts/shared_history_probe.py --seconds 30    # live read contract + FD sampling
```

The controls prove the detector actually fires (on macOS `os.readlink("/dev/fd/N")`
fails with EINVAL, so `F_GETPATH` is used; without that the sampler could never
detect anything and its zeros would be meaningless).

## 11. Known producer defect

Four endpoints — `/v1/metadata`, `/v1/features`, `/v1/funding`, `/v1/open-interest` —
return HTTP 500 on the live service for 442 of 478 symbols because the generic
dataset enumerator feeds ExFAT AppleDouble sidecars to DuckDB. This is a **producer**
defect, reproduced and root-caused in
`artifacts/shared-history-integration/SHARED_HISTORY_SERVICE_DEFECT.md`. It was not
fixed here: modifying the running single-writer production service is out of scope.
The integration reports these endpoints honestly as `DATA_UNAVAILABLE`.

## 12. Verification

    PYTEST = PASS             1 263 tests, 0 failures (83 new)
    RUFF   = PASS             check + format clean on all new files

Only `ruff check` is enforced by the repository (`select = ["E","F","I","UP","B","ASYNC"]`);
the new files additionally satisfy `ruff format`.