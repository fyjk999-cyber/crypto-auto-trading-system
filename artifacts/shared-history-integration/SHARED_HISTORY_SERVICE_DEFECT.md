# SHARED MARKET HISTORY SERVICE DEFECT — HTTP 500 ON FOUR ENDPOINTS

Status: **OPEN — REPRODUCED, ROOT-CAUSED, NOT FIXED (out of scope for the LowRisk integration)**

Discovered during: LOWRISK → SHARED MARKET HISTORY READ-ONLY INTEGRATION (reconnaissance)
Date of evidence: see the probe artifacts in this directory
Severity: blocks 4 of the 8 required read-contract endpoints for 92.5% of the universe

## 1. Symptom

Against the live service at `http://127.0.0.1:8770`:

| Endpoint | HTTP | Well-formed |
| --- | --- | --- |
| `/v1/health` | 200 | yes |
| `/v1/stats` | 200 | yes (slow: >10s, <25s) |
| `/v1/universe` | 200 | yes (478 symbols) |
| `/v1/latest` | 200 | yes |
| `/v1/candles` | 200 | yes |
| `/v1/regime/{symbol}` | 200 | yes |
| `/v1/analogs/{symbol}` | 200 | yes |
| `/v1/metadata/{symbol}` | **500** | no |
| `/v1/features/{symbol}` | **500** | no |
| `/v1/funding/{symbol}` | **500** | no |
| `/v1/open-interest/{symbol}` | **500** | no |

All four failures return the same body:

```json
{"error":"internal_error","message":"InvalidInputException"}
```

## 2. Root cause

`InvalidInputException` is DuckDB's error for a file that is not valid Parquet. The
on-disk ExFAT volume carries macOS AppleDouble sidecar files (`._<name>.parquet`)
beside every real partition, and the generic dataset file enumerator does not filter
them:

    file: src/shared_market_history/storage/parquet_store.py
    func: ParquetStore._dataset_files()
    line: files = sorted(base.rglob("*.parquet"))

Every `._*.parquet` sidecar matched by that `rglob` is passed to
`read_parquet([...])`, which aborts the whole read.

The candle path is unaffected because it uses a strict month-partition glob that
cannot match a sidecar:

    line: files = sorted(base.glob("*/" + timeframe + "/[0-9][0-9][0-9][0-9]/[0-9][0-9].parquet"))

`/v1/metadata` and `/v1/features` fail through the same helper (metadata computes
per-dataset coverage; features has no backing dataset at all).

## 3. Reproduction

```
$ python3 -c "
import duckdb, pathlib
R = pathlib.Path('/Volumes/My PSSD/SharedMarketHistory/parquet')
files = sorted((R/'funding'/'BTCUSDT').rglob('*.parquet'))
ad = [f for f in files if f.name.startswith('._')]
print('funding files:', len(files), 'AppleDouble:', len(ad))
con = duckdb.connect()
for label, fl in (('WITH sidecars', files),
                  ('WITHOUT sidecars', [f for f in files if not f.name.startswith('._')])):
    try:
        n = con.execute('SELECT count(*) FROM read_parquet(?)', [[str(f) for f in fl]]).fetchone()[0]
        print(' ', label, '-> OK rows=', n)
    except Exception as e:
        print(' ', label, '->', type(e).__name__, str(e).splitlines()[0][:80])
"
funding files: 7 AppleDouble: 3
  WITH sidecars    -> InvalidInputException Invalid Input Error: No magic bytes found at end of file '/Volumes/...
  WITHOUT sidecars -> OK rows= 311
```

The schema is not the problem: the on-disk column sets for `funding` and
`open_interest` match `FUNDING_SCHEMA` / `OI_SCHEMA` exactly.

## 4. Causal control

Symbols whose partition tree happens to contain **no** sidecar serve correctly, and
symbols that do contain a sidecar fail. The split is identical for both datasets:

| Dataset | Symbols WITH `._` sidecars | Symbols WITHOUT | Total |
| --- | --- | --- | --- |
| funding | 442 → HTTP 500 | 36 → HTTP 200 | 478 |
| open_interest | 442 → HTTP 500 | 36 → HTTP 200 | 478 |

Sampled pairs:

| Endpoint | Symbol | Sidecars | HTTP |
| --- | --- | --- | --- |
| `/v1/funding/0GUSDT` | 0GUSDT | yes | 500 |
| `/v1/funding/AKEUSDT` | AKEUSDT | no | 200 |
| `/v1/open-interest/0GUSDT` | 0GUSDT | yes | 500 |
| `/v1/open-interest/AKEUSDT` | AKEUSDT | no | 200 |

Sidecar totals across the volume: candles 31 207, funding 1 246, open_interest 867.

This is a one-cause defect: 442/478 = 92.5% of the universe is affected on both
affected datasets.

## 5. Proposed fix (not applied)

Exclude AppleDouble sidecars where the file list is built:

```python
files = sorted(p for p in base.rglob("*.parquet") if not p.name.startswith("._"))
```

A repository-wide guard on every `rglob("*.parquet")` would be preferable, since the
strict candle glob only accidentally avoids the same class of bug.

## 6. Why it was not fixed here

* The LowRisk directive forbids modifying the running production service in place,
  and this work is an integration/landing task, not a Shared History remediation.
* The deployed service is a single-writer production process; patching it would
  change the producer under an active writer lease.
* The LowRisk integration handles the condition **correctly and honestly**: these
  endpoints surface as `DATA_UNAVAILABLE` with reason `SHARED_HISTORY_HTTP_ERROR`.
  No value is invented, zero-filled or silently substituted.

## 7. Effect on acceptance

Classified as a factual runtime defect of the **producer**, requiring a separate
remediation phase. It does not invalidate the LowRisk integration, which delivers
the full read interface and fails closed on every unavailable endpoint.

    SHARED_HISTORY_SERVICE_ACCEPTANCE = PARTIAL
      AVAILABLE   : health, stats, universe, latest, candles, regime, analogs
      UNAVAILABLE : metadata, features, funding, open-interest  (this defect)
    LOWRISK_INTEGRATION_ENGINEERING_ACCEPTANCE = PASS